"""
Base do agente: saber se está em dia e atualizar (painel da página /agente e comandos do main.py).

Conceito
--------
O agente depende de três artefatos gerados fora do laço de perguntas:

    documentacao   índice da documentação (RAG)    depende dos .md       --indexar
    dias           índice dos resumos diários      depende do banco      --indexar-dias
    previsao       modelo de previsão              depende do banco      --treinar-previsao

Cada um tem uma situação:

- ausente: nunca foi gerado (ou é de outro modelo de embeddings);
- desatualizado: os documentos ou os dados mudaram desde a última atualização;
- atualizado: em dia;
- indisponivel: não dá para conferir nem atualizar (sem AGENTE_SQL_CONNECTIONSTRING
  ou com o banco fora do ar). Só vale para os dois que dependem do banco.

Como saber se mudou, sem refazer o trabalho:

- documentacao: os ids dos trechos (sha256 de modelo + arquivo + seção + texto,
  rag/indexador.py) são recalculados sem vetorizar nada e comparados com os do
  índice salvo;
- dias e previsao: a ASSINATURA dos dados (ConsultaDados.assinatura(): quantidade,
  período e checksum do conteúdo) é gravada a cada atualização e comparada com a
  atual. Reingerir os mesmos dados não muda a assinatura, então não obriga a
  retreinar à toa.

PainelDaBase roda a atualização em segundo plano (uma por vez) para a web:
treinar a previsão leva cerca de 1 minuto, e a requisição HTTP não fica presa.

Documentação: docs/agente/arquitetura.md § 11 e docs/manual-execucao.md (agente)
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logger import logger

ITENS = ("documentacao", "dias", "previsao")
NOMES = {"documentacao": "Documentação (RAG)", "dias": "Dias semelhantes", "previsao": "Modelo de previsão"}
# Situações em que o botão de atualizar fica habilitado.
PENDENTES = ("ausente", "desatualizado")
ARQUIVO_ESTADO_DOCUMENTACAO = "estado_documentacao.json"
ARQUIVO_ESTADO_DIAS = "estado.json"
SEM_CONEXAO = "A variável AGENTE_SQL_CONNECTIONSTRING deve estar configurada para atualizar os dias e a previsão."
# O estado é recalculado no máximo a cada 30 s (cada cálculo consulta o banco e relê os .md).
TTL_ESTADO_SEGUNDOS = 30


def situacao(chave: str, motivo: str = "", atualizado_em: str | None = None) -> dict:
    """
    Situação de um artefato, no formato devolvido ao painel.

    Example:
        >>> situacao("ausente", "rode a atualização")["situacao"]
        'ausente'
    """
    return {"situacao": chave, "motivo": motivo, "atualizado_em": atualizado_em}


def _agora() -> str:
    """Instante atual em ISO, sem microssegundos."""
    return datetime.now().isoformat(timespec="seconds")


def _ler_json(caminho: Path) -> dict | None:
    """Conteúdo do JSON, ou None se não existe ou está corrompido."""
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gravar_json(caminho: Path, dados: dict) -> None:
    """Grava o JSON, criando a pasta."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _consulta_do_banco(cfg):
    """ConsultaDados com o usuário só de leitura do agente, sem cache reaproveitado."""
    if not cfg.sql_connectionstring:
        raise ValueError(SEM_CONEXAO)
    from src.agente.ferramentas.consulta_dados import ConsultaDados
    from src.database.connection import DatabaseConnection

    return ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))


def _embedder(cfg, embedder):
    """O embedder recebido ou o da configuração (criar o objeto não baixa o modelo)."""
    if embedder is not None:
        return embedder
    from src.agente.fabrica import embedder_da_config

    return embedder_da_config(cfg)


# --- Situação de cada artefato -----------------------------------------------------------


def estado_da_documentacao(cfg, embedder=None, raiz: Path | None = None) -> dict:
    """
    Compara os trechos dos documentos de hoje com os do índice salvo, sem vetorizar.

    Args:
        cfg: ConfigIndice ou ConfigAgente (dir_indice, vetores, embeddings_modelo).
        embedder: modelo de embeddings (só o nome é usado). None = o da configuração.
        raiz: raiz do projeto, de onde vem o corpus.

    Example:
        >>> import tempfile
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.config import ConfigIndice
        >>> estado_da_documentacao(ConfigIndice(dir_indice=Path(tempfile.mkdtemp())), EmbedderSimulado())["situacao"]
        'ausente'
    """
    from src.agente.rag.indexador import RAIZ_PROJETO, arquivos_do_corpus, id_do_trecho, trechos_do_corpus
    from src.agente.rag.vector_store import abrir_indice

    embedder = _embedder(cfg, embedder)
    raiz = raiz or RAIZ_PROJETO
    store = abrir_indice(cfg.vetores, cfg.dir_indice)
    if store is None or store.modelo != embedder.modelo:
        return situacao("ausente", "o índice da documentação ainda não foi gerado com este modelo")
    registro = _ler_json(cfg.dir_indice / ARQUIVO_ESTADO_DOCUMENTACAO) or {}
    desejados = {id_do_trecho(embedder.modelo, trecho) for trecho in trechos_do_corpus(arquivos_do_corpus(raiz), raiz)}
    if desejados != store.ids():
        return situacao("desatualizado", "a documentação mudou desde a última indexação", registro.get("atualizado_em"))
    return situacao("atualizado", "", registro.get("atualizado_em"))


def estado_dos_dias(cfg, assinatura: dict | None, embedder=None) -> dict:
    """
    Índice dos dias contra a assinatura atual dos dados.

    Args:
        cfg: configuração (dir_indice, vetores).
        assinatura: ConsultaDados.assinatura(), ou None se o banco não está acessível.
        embedder: modelo de embeddings (só o nome). None = o da configuração.

    Example:
        >>> from src.config import ConfigIndice
        >>> estado_dos_dias(ConfigIndice(), None)["situacao"]
        'indisponivel'
    """
    from src.agente.dias.indice import PASTA_DIAS
    from src.agente.rag.vector_store import abrir_indice

    if assinatura is None:
        return situacao("indisponivel", "o banco do agente não está acessível (AGENTE_SQL_CONNECTIONSTRING)")
    store = abrir_indice(cfg.vetores, cfg.dir_indice / PASTA_DIAS)
    if store is None or store.modelo != _embedder(cfg, embedder).modelo:
        return situacao("ausente", "o índice dos dias ainda não foi gerado")
    registro = _ler_json(cfg.dir_indice / PASTA_DIAS / ARQUIVO_ESTADO_DIAS) or {}
    if registro.get("assinatura") != assinatura:
        return situacao("desatualizado", "os dados do banco mudaram desde a última indexação", registro.get("atualizado_em"))
    return situacao("atualizado", "", registro.get("atualizado_em"))


def estado_da_previsao(cfg, assinatura: dict | None) -> dict:
    """
    Modelo de previsão contra a assinatura atual, sem carregar o pickle.

    Também acusa o modelo que o agente recusaria (POL-12): arquivo alterado ou
    treinado com outra versão do scikit-learn.

    Example:
        >>> import tempfile
        >>> from src.config import ConfigIndice
        >>> estado_da_previsao(ConfigIndice(dir_indice=Path(tempfile.mkdtemp())), {"medicoes": 0})["situacao"]
        'ausente'
    """
    from importlib.metadata import version

    from src.agente.fabrica import pasta_do_modelo_de_previsao
    from src.previsao.persistencia import ARQUIVO_METADADOS, ARQUIVO_MODELO, sha256_do_arquivo

    if assinatura is None:
        return situacao("indisponivel", "o banco do agente não está acessível (AGENTE_SQL_CONNECTIONSTRING)")
    pasta = pasta_do_modelo_de_previsao(cfg.dir_indice)
    metadados = _ler_json(pasta / ARQUIVO_METADADOS)
    if metadados is None or not (pasta / ARQUIVO_MODELO).exists():
        return situacao("ausente", "o modelo de previsão ainda não foi treinado")
    criado_em = metadados.get("criado_em")
    if sha256_do_arquivo(pasta / ARQUIVO_MODELO) != metadados.get("sha256"):
        return situacao("desatualizado", "o arquivo do modelo foi alterado e seria recusado (POL-12)", criado_em)
    if metadados.get("versao_sklearn") != version("scikit-learn"):
        return situacao("desatualizado", "o modelo é de outra versão do scikit-learn e seria recusado (POL-12)", criado_em)
    if metadados.get("assinatura_dados") != assinatura:
        return situacao("desatualizado", "os dados do banco mudaram desde o último treino", criado_em)
    return situacao("atualizado", "", criado_em)


def estado_da_base(cfg, consulta=None, embedder=None) -> dict:
    """
    Situação dos três artefatos: {"documentacao": {...}, "dias": {...}, "previsao": {...}}.

    Args:
        cfg: ConfigIndice (load_config_indice) ou ConfigAgente.
        consulta: ConsultaDados pronto. None = o banco de AGENTE_SQL_CONNECTIONSTRING, se configurado.
        embedder: modelo de embeddings (só o nome). None = o da configuração.

    Example:
        >>> import tempfile
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.config import ConfigIndice
        >>> base = estado_da_base(ConfigIndice(dir_indice=Path(tempfile.mkdtemp())), consulta_de_exemplo(), EmbedderSimulado())
        >>> {item: base[item]["situacao"] for item in ITENS}
        {'documentacao': 'ausente', 'dias': 'ausente', 'previsao': 'ausente'}
    """
    embedder = _embedder(cfg, embedder)
    assinatura = None
    try:
        if consulta is None and cfg.sql_connectionstring:
            consulta = _consulta_do_banco(cfg)
        if consulta is not None:
            assinatura = consulta.assinatura()
    except Exception as erro:
        # Cuidado (POL-10): só o tipo do erro; a mensagem pode citar a connection string.
        logger.error(f"Base do agente: não foi possível ler a assinatura dos dados erro={type(erro).__name__}")
    return {
        "documentacao": estado_da_documentacao(cfg, embedder),
        "dias": estado_dos_dias(cfg, assinatura, embedder),
        "previsao": estado_da_previsao(cfg, assinatura),
    }


# --- Atualização --------------------------------------------------------------------------


def atualizar_documentacao(cfg, embedder=None):
    """
    Indexa a documentação (idempotente) e registra quando.

    Returns:
        ResumoIndexacao (também no log).

    Example:
        >>> import tempfile
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.config import ConfigIndice
        >>> cfg = ConfigIndice(dir_indice=Path(tempfile.mkdtemp()))
        >>> atualizar_documentacao(cfg, EmbedderSimulado()).inseridos > 0, estado_da_documentacao(cfg, EmbedderSimulado())["situacao"]
        (True, 'atualizado')
    """
    from src.agente.rag.indexador import indexar

    resumo = indexar(_embedder(cfg, embedder), cfg.dir_indice, vetores=cfg.vetores)
    _gravar_json(cfg.dir_indice / ARQUIVO_ESTADO_DOCUMENTACAO, {"atualizado_em": _agora()})
    return resumo


def atualizar_dias(cfg, consulta=None, embedder=None):
    """
    Indexa os resumos diários e grava a assinatura dos dados usados.

    A assinatura é lida ANTES das medições: se uma ingestão entrar no meio, o
    painel acusa "desatualizado" na próxima conferência, e não o contrário.

    Raises:
        ValueError: sem consulta e sem AGENTE_SQL_CONNECTIONSTRING.

    Example:
        >>> import tempfile
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.config import ConfigIndice
        >>> cfg, consulta = ConfigIndice(dir_indice=Path(tempfile.mkdtemp())), consulta_de_exemplo()
        >>> atualizar_dias(cfg, consulta, EmbedderSimulado()).chunks
        1
        >>> estado_dos_dias(cfg, consulta.assinatura(), EmbedderSimulado())["situacao"]
        'atualizado'
    """
    from src.agente.dias.indice import PASTA_DIAS, indexar_dias
    from src.agente.ferramentas.consulta_dados import FiltroMedicoes

    consulta = consulta or _consulta_do_banco(cfg)
    assinatura = consulta.assinatura()
    resumo = indexar_dias(consulta.medicoes(FiltroMedicoes()), _embedder(cfg, embedder), cfg.dir_indice, cfg.vetores)
    _gravar_json(cfg.dir_indice / PASTA_DIAS / ARQUIVO_ESTADO_DIAS, {"atualizado_em": _agora(), "assinatura": assinatura})
    return resumo


def treinar_previsao(cfg, consulta=None, pasta_relatorios: Path | None = None) -> Path:
    """
    Treina e avalia o modelo de previsão, grava o modelo com a assinatura dos dados e o relatório.

    Args:
        cfg: configuração (dir_indice, sql_connectionstring).
        consulta: ConsultaDados pronto. None = o banco do agente.
        pasta_relatorios: onde gravar o relatório. None = relatorios/ na raiz do projeto.

    Returns:
        Caminho do relatório.

    Raises:
        ValueError: sem consulta e sem AGENTE_SQL_CONNECTIONSTRING.

    Example:
        >>> from src.config import ConfigIndice
        >>> treinar_previsao(ConfigIndice())
        Traceback (most recent call last):
        ...
        ValueError: A variável AGENTE_SQL_CONNECTIONSTRING deve estar configurada para atualizar os dias e a previsão.
    """
    from src.agente.fabrica import pasta_do_modelo_de_previsao
    from src.agente.ferramentas.consulta_dados import FiltroMedicoes
    from src.config import RAIZ_PROJETO
    from src.previsao.dados import PARAMETROS_ALVO
    from src.previsao.persistencia import salvar_modelo
    from src.previsao.relatorio import montar_relatorio_treino
    from src.previsao.treino import treinar

    consulta = consulta or _consulta_do_banco(cfg)
    inicio = time.monotonic()
    assinatura = consulta.assinatura()
    avaliacoes = treinar(consulta.medicoes(FiltroMedicoes(parametros=PARAMETROS_ALVO)))
    salvar_modelo(avaliacoes, pasta_do_modelo_de_previsao(cfg.dir_indice), assinatura=assinatura)
    relatorio = (pasta_relatorios or RAIZ_PROJETO / "relatorios") / f"previsao_{datetime.now():%Y%m%d_%H%M%S}.md"
    relatorio.parent.mkdir(parents=True, exist_ok=True)
    relatorio.write_text(montar_relatorio_treino(avaliacoes), encoding="utf-8")
    aprovados = sum(a.aprovado for a in avaliacoes)
    logger.info(f"Treino da previsão: combinacoes={len(avaliacoes)} aprovadas={aprovados} ms={int((time.monotonic() - inicio) * 1000)} relatorio={relatorio}")
    return relatorio


ATUALIZADORES: dict[str, Callable[[Any], Any]] = {
    "documentacao": atualizar_documentacao,
    "dias": atualizar_dias,
    "previsao": treinar_previsao,
}


# --- Painel da web ------------------------------------------------------------------------


class PainelDaBase:
    """
    Estado da base (com cache curto) e a atualização em segundo plano, uma por vez.

    Args:
        verificar: devolve a situação dos três artefatos (estado_da_base).
        atualizar: atualiza um artefato pelo nome ("documentacao", "dias" ou "previsao").
        ttl_segundos: tempo de vida do estado em cache.
        relogio: tempo atual em segundos (injetável nos testes).

    Example:
        >>> base = {item: situacao("atualizado") for item in ITENS}
        >>> PainelDaBase(lambda: base, lambda item: None).iniciar("todos")
        (400, 'A base do agente já está em dia.')
    """

    def __init__(
        self,
        verificar: Callable[[], dict],
        atualizar: Callable[[str], Any],
        ttl_segundos: float = TTL_ESTADO_SEGUNDOS,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        """Guarda as funções e começa ocioso."""
        self.__verificar = verificar
        self.__atualizar = atualizar
        self.__ttl = ttl_segundos
        self.__relogio = relogio
        self.__lock = threading.Lock()
        self.__cache: tuple[float, dict] | None = None
        self.__thread: threading.Thread | None = None
        self.__tarefa: dict = {"executando": False, "etapa": None, "itens": [], "concluidos": [], "falhas": [], "terminou_em": None}
        # Chamado depois de uma atualização com sucesso (a web descarta o agente montado).
        self.ao_concluir: Callable[[], None] = lambda: None

    def itens(self) -> dict:
        """Situação dos artefatos, do cache ou recalculada."""
        with self.__lock:
            if self.__cache and self.__relogio() - self.__cache[0] < self.__ttl:
                return self.__cache[1]
        valor = self.__verificar()
        with self.__lock:
            self.__cache = (self.__relogio(), valor)
        return valor

    def estado(self) -> dict:
        """{"itens": situação com o nome de cada artefato, "tarefa": andamento da atualização}."""
        itens = {item: {**dados, "nome": NOMES[item]} for item, dados in self.itens().items()}
        with self.__lock:
            tarefa = {**self.__tarefa, "etapa_nome": NOMES.get(self.__tarefa["etapa"])}
        return {"itens": itens, "tarefa": tarefa}

    def invalidar(self) -> None:
        """Esquece o estado em cache (a próxima consulta recalcula)."""
        with self.__lock:
            self.__cache = None

    def dados_mudaram(self) -> None:
        """Depois de uma ingestão: recalcula o estado e descarta o agente montado (cache de 5 min)."""
        self.invalidar()
        self.ao_concluir()

    def iniciar(self, pedido: Any) -> tuple[int, str]:
        """
        Começa a atualização em segundo plano.

        Args:
            pedido: "todos" (os pendentes) ou uma lista de nomes de artefatos.

        Returns:
            (código HTTP, mensagem): 202 iniciada, 409 já há uma em andamento,
            400 pedido inválido ou item que não precisa (ou não pode) ser atualizado.
        """
        with self.__lock:
            if self.__tarefa["executando"]:
                return 409, "Já existe uma atualização em andamento."
        itens = self.itens()
        pendentes = [item for item in ITENS if itens[item]["situacao"] in PENDENTES]
        if pedido == "todos":
            escolhidos = pendentes
        elif isinstance(pedido, list) and pedido and all(isinstance(item, str) for item in pedido):
            desconhecidos = [item for item in pedido if item not in ITENS]
            if desconhecidos:
                return 400, f"Artefato desconhecido: {', '.join(desconhecidos)}."
            em_dia = [NOMES[item] for item in pedido if item not in pendentes]
            if em_dia:
                return 400, f"Não precisa ou não pode ser atualizado agora: {', '.join(em_dia)}."
            escolhidos = [item for item in ITENS if item in pedido]
        else:
            return 400, 'Envie {"itens": "todos"} ou uma lista de artefatos.'
        if not escolhidos:
            return 400, "A base do agente já está em dia."
        with self.__lock:
            if self.__tarefa["executando"]:
                return 409, "Já existe uma atualização em andamento."
            self.__tarefa = {"executando": True, "etapa": escolhidos[0], "itens": escolhidos, "concluidos": [], "falhas": [], "terminou_em": None}
            self.__thread = threading.Thread(target=self.__executar, args=(escolhidos,), name="atualizacao-base-agente", daemon=True)
            self.__thread.start()
        return 202, "Atualização iniciada."

    def aguardar(self, timeout: float | None = None) -> None:
        """Espera a atualização em andamento terminar (testes e encerramento)."""
        thread = self.__thread
        if thread is not None:
            thread.join(timeout)

    def __executar(self, itens: list[str]) -> None:
        """Atualiza cada artefato em ordem; a falha de um não impede os seguintes."""
        try:
            for item in itens:
                with self.__lock:
                    self.__tarefa["etapa"] = item
                logger.info(f"Base do agente: atualizando item={item}")
                try:
                    self.__atualizar(item)
                except Exception as erro:
                    # Cuidado (POL-10): só o tipo do erro, nunca a mensagem.
                    logger.error(f"Base do agente: falha item={item} erro={type(erro).__name__}")
                    with self.__lock:
                        self.__tarefa["falhas"].append(item)
                else:
                    with self.__lock:
                        self.__tarefa["concluidos"].append(item)
        finally:
            with self.__lock:
                self.__tarefa.update(executando=False, etapa=None, terminou_em=_agora())
                concluidos = list(self.__tarefa["concluidos"])
            self.invalidar()
            logger.info(f"Base do agente: atualização terminada concluidos={','.join(concluidos) or '-'}")
            if concluidos:
                self.ao_concluir()


def painel_da_configuracao() -> PainelDaBase:
    """
    PainelDaBase que lê a configuração do .env (load_config_indice) a cada uso.

    Example:
        >>> type(painel_da_configuracao()).__name__
        'PainelDaBase'
    """
    from src.config import load_config_indice

    return PainelDaBase(
        verificar=lambda: estado_da_base(load_config_indice()),
        atualizar=lambda item: ATUALIZADORES[item](load_config_indice()),
    )
