"""
Fábrica do agente: monta todas as peças a partir da configuração.

Conceito
--------
Composition root (raiz de composição): o ÚNICO lugar que sabe qual LLM, qual
banco e quais limites usar. O resto do código recebe as peças prontas
(injeção de dependência) e não lê variável de ambiente nenhuma.

    load_config_agente()  →  ClienteAnthropic (Claude Haiku 5.5) ou ClienteOpenAI (DA11)
                          →  DatabaseConnection(AGENTE_SQL_CONNECTIONSTRING)  (só leitura, POL-01)
                          →  ConsultaDados → RegistroFerramentas
                          →  índice da documentação (data/agente) → Recuperador → buscar_documentacao
                          →  índice dos dias (data/agente/dias) → BuscaDeDias → dias_semelhantes
                          →  modelo treinado (data/agente/modelos/previsao), hash conferido → prever
                          →  Conversas (10 turnos)
                          →  Agente (limites da POL-07)

Para estudo e testes, llm, consulta e recuperador podem ser passados prontos
(ex.: o LLM roteirizado e os dados de exemplo em memória), sem chave e sem banco.
No modo simulado, a documentação só entra se o recuperador for passado: assim os
testes nunca dependem do índice real nem do download do modelo de embeddings.

Documentação: docs/agente/arquitetura.md § 2 e § 9
"""
from pathlib import Path

from src.agente.conversa import Conversas
from src.agente.dias.indice import BuscaDeDias
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.ferramentas.consulta_dados import ConsultaDados
from src.agente.llm.base import LLMClient
from src.agente.orquestrador import Agente
from src.agente.rag.recuperador import Recuperador
from src.config import FORNECEDORES_REAIS, ConfigAgente, load_config_agente
from src.previsao.persistencia import ModeloPrevisao
from src.logger import logger


def criar_agente(
    cfg: ConfigAgente | None = None,
    llm: LLMClient | None = None,
    consulta: ConsultaDados | None = None,
    recuperador: Recuperador | None = None,
    dias: BuscaDeDias | None = None,
    modelo_previsao: ModeloPrevisao | None = None,
) -> Agente:
    """
    Agente pronto, com as peças da configuração ou as recebidas.

    Args:
        cfg: configuração. None = load_config_agente() (lê o .env).
        llm: cliente de LLM pronto. None = ClienteAnthropic da configuração.
        consulta: acesso aos dados pronto. None = Azure SQL com o usuário só de leitura.
        recuperador: busca na documentação pronta. None = o índice salvo em
            AGENTE_DIR_INDICE (só com o fornecedor anthropic).
        dias: busca no índice dos dias pronta. None = o índice salvo em
            AGENTE_DIR_INDICE/dias (só com o fornecedor anthropic).
        modelo_previsao: modelo de previsão pronto. None = o salvo em
            AGENTE_DIR_INDICE/modelos/previsao, se o hash conferir (só com o fornecedor anthropic).

    Returns:
        Agente com os limites da configuração.

    Raises:
        ValueError: fornecedor "simulado" sem llm, ou sem consulta e sem
            AGENTE_SQL_CONNECTIONSTRING.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> from src.agente.llm.roteirizado import LLMRoteirizado
        >>> agente = criar_agente(ConfigAgente("simulado"), LLMRoteirizado([]), consulta_de_exemplo())
        >>> type(agente).__name__
        'Agente'
    """
    cfg = cfg or load_config_agente()
    if llm is None:
        llm = llm_da_config(cfg)
    if consulta is None:
        if not cfg.sql_connectionstring:
            raise ValueError("sem AGENTE_SQL_CONNECTIONSTRING: passe consulta=consulta_de_exemplo() para estudo offline")
        from src.database.connection import DatabaseConnection

        consulta = ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))
    if cfg.llm_fornecedor in FORNECEDORES_REAIS:
        embedder = embedder_da_config(cfg)
        # Cuidado: "is None", e não "or": uma BuscaDeDias vazia tem len 0 e seria trocada.
        recuperador = recuperador_da_documentacao(cfg, embedder) if recuperador is None else recuperador
        dias = busca_de_dias_da_config(cfg, embedder) if dias is None else dias
        modelo_previsao = modelo_previsao_da_config(cfg) if modelo_previsao is None else modelo_previsao
    return Agente(
        llm=llm,
        registro=criar_registro(consulta, cfg.max_linhas, recuperador, dias, modelo_previsao),
        conversas=Conversas(max_turnos=cfg.historico_turnos),
        obter_cobertura=consulta.cobertura,
        max_ferramentas=cfg.max_ferramentas,
        max_tokens_pergunta=cfg.max_tokens_pergunta,
        prazo_segundos=cfg.prazo_pergunta_segundos,
    )


def embedder_da_config(cfg: ConfigAgente):
    """
    O EmbedderFastembed da configuração, compartilhado pela documentação e pelos dias.

    O modelo só é carregado na primeira vetorização: criar o objeto não baixa nada.

    Example:
        >>> embedder_da_config(ConfigAgente("anthropic")).dimensoes
        384
    """
    from src.agente.rag.embeddings import EmbedderFastembed

    return EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos")


def llm_da_config(cfg: ConfigAgente) -> LLMClient:
    """
    O cliente do LLM do fornecedor configurado (AGENTE_LLM_FORNECEDOR).

    Raises:
        ValueError: fornecedor "simulado", que não tem LLM de verdade.

    Example:
        >>> llm_da_config(ConfigAgente("openai", "gpt-4.1-mini", openai_api_key="sk-x")).modelo
        'gpt-4.1-mini'
    """
    # Por quê: imports aqui, e não no topo, para os testes e exemplos offline
    # não carregarem o SDK do fornecedor.
    if cfg.llm_fornecedor == "anthropic":
        from src.agente.llm.cliente_anthropic import ClienteAnthropic

        return ClienteAnthropic.de_config(cfg)
    if cfg.llm_fornecedor == "openai":
        from src.agente.llm.cliente_openai import ClienteOpenAI

        return ClienteOpenAI.de_config(cfg)
    raise ValueError("o fornecedor simulado é só para testes e estudo: passe llm=LLMRoteirizado(...)")


def pasta_do_modelo_de_previsao(dir_indice: Path) -> Path:
    """
    Onde --treinar-previsao grava o modelo e onde o agente o procura.

    Example:
        >>> pasta_do_modelo_de_previsao(Path("data/agente")).as_posix()
        'data/agente/modelos/previsao'
    """
    return dir_indice / "modelos" / "previsao"


def modelo_previsao_da_config(cfg: ConfigAgente) -> ModeloPrevisao | None:
    """
    O modelo de previsão salvo, ou None (com aviso no log) se não existe ou não confere (POL-12).

    Example:
        >>> import tempfile
        >>> modelo_previsao_da_config(ConfigAgente("anthropic", dir_indice=Path(tempfile.mkdtemp()))) is None
        True
    """
    from src.previsao.persistencia import carregar_modelo

    modelo = carregar_modelo(pasta_do_modelo_de_previsao(cfg.dir_indice))
    if modelo is None:
        logger.warning("Agente: modelo de previsão ausente ou recusado; rode python main.py --treinar-previsao")
    return modelo


def busca_de_dias_da_config(cfg: ConfigAgente, embedder=None) -> BuscaDeDias | None:
    """
    Busca no índice dos dias, ou None (com aviso no log) se ele não existe.

    Sem índice (falta rodar python main.py --indexar-dias), o agente continua
    respondendo, só sem dias_semelhantes.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> busca_de_dias_da_config(ConfigAgente("anthropic", dir_indice=Path(tempfile.mkdtemp()))) is None
        True
    """
    from src.agente.dias.indice import abrir_busca_de_dias

    busca = abrir_busca_de_dias(embedder or embedder_da_config(cfg), cfg.dir_indice, cfg.vetores)
    if busca is None:
        logger.warning("Agente: índice dos dias não encontrado ou de outro modelo; rode python main.py --indexar-dias")
    return busca


def recuperador_da_documentacao(cfg: ConfigAgente, embedder=None) -> Recuperador | None:
    """
    Recuperador sobre o índice salvo, ou None (com aviso no log) se não der para usar a documentação.

    Sem índice (falta rodar python main.py --indexar) ou com índice de outro modelo,
    o agente continua respondendo números, só sem buscar_documentacao.

    Raises:
        ValueError: AGENTE_VETORES desconhecido.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> recuperador_da_documentacao(ConfigAgente("anthropic", dir_indice=Path(tempfile.mkdtemp()))) is None
        True
    """
    from src.agente.rag.vector_store import abrir_indice

    store = abrir_indice(cfg.vetores, cfg.dir_indice)
    if store is None:
        logger.warning("Agente: índice da documentação não encontrado; rode python main.py --indexar")
        return None
    if store.modelo != cfg.embeddings_modelo:
        logger.warning(f"Agente: índice criado com outro modelo ({store.modelo}); rode python main.py --indexar")
        return None
    return Recuperador(embedder or embedder_da_config(cfg), store)
