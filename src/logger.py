"""
Configuração única de logs do projeto.

Nenhum outro módulo chama logging.basicConfig ou print: todos obtêm o logger
com logging.getLogger(NOME_LOGGER). As regras estão em docs/seguranca-lgpd.md.
"""

import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

FORMATO = "%(asctime)s - [%(levelname)s] - %(message)s"
NOME_LOGGER = "DataScienceIA_Logger"
NOME_LOGGER_REJEITADOS = "DataScienceIA_Rejeitados"
PASTA_LOGS = Path(__file__).resolve().parents[1] / "logs"

# Campos que identificam pessoa: o valor nunca vai para o log, nem anonimizado.
CAMPOS_PESSOAIS = frozenset(
    {
        "operador_cpf",
        "operador_nome_completo",
        "operador_email",
        "cpf_hash",
        "nome_hash",
        "email_criptografado",
    }
)

# Marca as linhas do cabeçalho de cada arquivo (etapa que o criou e por quê).
MARCADOR_CABECALHO = "[cabeçalho]"

_SO_LEITURA = (
    "nenhum. Esta etapa não importa dados, por isso o arquivo tem só este cabeçalho"
)

# Etapa → como foi executada, o que faz e o que cada arquivo registra.
ETAPAS = {
    "ingestao": {
        "execucao": "Ingestão (python main.py --ingestao)",
        "objetivo": "coleta o lote na API, normaliza, anonimiza, valida e grava no banco 3FN",
        "pipeline": "andamento, avisos, erros e a linha 'Resumo da ingestão' com recebidos, "
        "válidos, inválidos e gravados. O que não foi importado está em {rejeitados}",
        "rejeitados": "uma linha por leitura recusada (nivel=leitura) ou medição descartada "
        "(nivel=item), com etapa, campo e motivo; valores pessoais nunca aparecem",
    },
    "analise": {
        "execucao": "Análise estatística (python main.py --analise)",
        "objetivo": "lê as medições gravadas, calcula as métricas e sinaliza anomalias (IQR e Z-Score)",
        "pipeline": "o relatório estatístico em INFO e uma linha WARNING 'Alerta de qualidade' "
        "por medição anômala",
        "rejeitados": _SO_LEITURA,
    },
    "consulta": {
        "execucao": "Consulta interativa (python main.py)",
        "objetivo": "abre a CLI de consulta às métricas e anomalias do banco",
        "pipeline": "início da aplicação e eventuais erros; as consultas aparecem só na tela",
        "rejeitados": _SO_LEITURA,
    },
    "agente": {
        "execucao": "Agente analítico (python main.py --agente ou --pergunta)",
        "objetivo": "responde perguntas em linguagem natural com um LLM e ferramentas só de leitura",
        "pipeline": "uma linha por pergunta (com CPF, e-mail e telefone mascarados), por ferramenta "
        "executada e por resposta (tokens e tempo), e uma linha WARNING 'guardrail=POL-xx' por "
        "política de segurança acionada; o texto das respostas não é registrado",
        "rejeitados": _SO_LEITURA,
    },
    "indexacao": {
        "execucao": "Indexação do agente (python main.py --indexar ou --indexar-dias)",
        "objetivo": "divide a documentação em trechos (ou gera os resumos diários), vetoriza os novos e atualiza o índice",
        "pipeline": "a linha 'Indexação' (documentação) ou 'Indexação dos dias' com o modelo, as contagens e o tempo",
        "rejeitados": _SO_LEITURA,
    },
    "previsao": {
        "execucao": "Treino da previsão (python main.py --treinar-previsao)",
        "objetivo": "avalia cada parâmetro e horizonte com validação temporal contra dois baselines e grava o modelo aprovado",
        "pipeline": "a linha 'Treino da previsão' com as combinações, as aprovadas, o tempo e o caminho do relatório",
        "rejeitados": _SO_LEITURA,
    },
    "laudo": {
        "execucao": "Laudos de anomalias (python main.py --laudo)",
        "objetivo": "classifica a causa provável de cada anomalia do período com o LLM (few-shot), valida o JSON e grava o CSV e o Markdown",
        "pipeline": "os laudos descartados (guardrail=POL-06 ou POL-03, com o motivo) e a linha 'Laudos' com as contagens",
        "rejeitados": _SO_LEITURA,
    },
    "avaliacao": {
        "execucao": "Avaliação do agente (python -m src.agente.avaliacao)",
        "objetivo": "faz as perguntas do golden set ao agente, mede seleção, números, recuperação e segurança e gera o relatório",
        "pipeline": "as perguntas e os guardrails de cada caso (como na etapa agente) e a linha 'Avaliação' com o caminho do relatório",
        "rejeitados": _SO_LEITURA,
    },
    "coleta": {
        "execucao": "Coleta avulsa (python -m src.ingestion.importar_dados)",
        "objetivo": "só busca o lote na API para conferência, sem validar nem gravar",
        "pipeline": "tentativas de conexão com a API e a quantidade de registros recebidos",
        "rejeitados": _SO_LEITURA,
    },
}

logger = logging.getLogger(NOME_LOGGER)
logger_rejeitados = logging.getLogger(NOME_LOGGER_REJEITADOS)

__rejeicoes: Counter = Counter()


def configurar_logs(etapa: str, pasta: Path | None = None) -> dict[str, Path]:
    """
    Configura o log da execução (console + arquivo) e o log de rejeitados.

    Deve ser chamada uma única vez, no início da execução. etapa (chave de
    ETAPAS) identifica quem criou os arquivos: ela vai para o cabeçalho de
    cada um. A pasta padrão é logs/ na raiz do projeto; a variável de ambiente
    PASTA_LOGS a substitui (usada pelos testes para não misturar seus arquivos
    com os de cargas reais). Retorna o caminho dos dois arquivos criados.
    """
    if etapa not in ETAPAS:
        raise ValueError(f"Etapa de log desconhecida: {etapa}")
    pasta = Path(pasta or os.environ.get("PASTA_LOGS") or PASTA_LOGS)
    pasta.mkdir(parents=True, exist_ok=True)

    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivos = {
        "pipeline": pasta / f"pipeline_{carimbo}.log",
        "rejeitados": pasta / f"rejeitados_{carimbo}.log",
    }

    logging.basicConfig(
        level=logging.INFO,
        format=FORMATO,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(arquivos["pipeline"], encoding="utf-8"),
        ],
        force=True,
    )

    # Os rejeitados vão só para o arquivo próprio: são milhares de linhas por
    # lote e poluiriam o console. O total aparece no resumo da execução.
    for handler in list(logger_rejeitados.handlers):
        logger_rejeitados.removeHandler(handler)
        handler.close()

    handler_rejeitados = logging.FileHandler(arquivos["rejeitados"], encoding="utf-8")
    handler_rejeitados.setFormatter(logging.Formatter(FORMATO))
    logger_rejeitados.addHandler(handler_rejeitados)
    logger_rejeitados.setLevel(logging.INFO)
    logger_rejeitados.propagate = False

    __escrever_cabecalho(etapa, arquivos)
    __rejeicoes.clear()
    return arquivos


def __escrever_cabecalho(etapa: str, arquivos: dict[str, Path]) -> None:
    """
    Primeiras linhas de cada arquivo: etapa que o criou, por quê e o que contém.

    Saem no mesmo formato das demais (data - [INFO] - mensagem), marcadas com
    MARCADOR_CABECALHO, e só nos arquivos, sem passar pelo console.
    """
    descricao = ETAPAS[etapa]
    comum = [
        f"Etapa: {descricao['execucao']}.",
        "Por que existe: cada execução cria um par de arquivos (pipeline e rejeitados) "
        f"com a data/hora de início no nome; esta execução {descricao['objetivo']}.",
    ]
    linhas = {
        "pipeline": comum
        + [
            f"Conteúdo: {descricao['pipeline'].format(rejeitados=arquivos['rejeitados'].name)}."
        ],
        "rejeitados": comum + [f"Conteúdo: {descricao['rejeitados']}."],
    }
    alvos = {
        "pipeline": [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.FileHandler)
        ],
        "rejeitados": logger_rejeitados.handlers,
    }
    for nome, handlers in alvos.items():
        for texto in linhas[nome]:
            registro = logging.LogRecord(
                NOME_LOGGER,
                logging.INFO,
                __file__,
                0,
                f"{MARCADOR_CABECALHO} {texto}",
                None,
                None,
            )
            for handler in handlers:
                handler.handle(registro)


def registrar_rejeicao(
    etapa: str,
    nivel: str,
    campo: str,
    motivo: str,
    registro: str | None = None,
    valor=None,
    severidade: int = logging.WARNING,
) -> None:
    """
    Registra uma linha no log de rejeitados, no mesmo formato para todas as etapas.

    nivel: "leitura" (registro inteiro), "item" (uma medição) ou "parametro".
    Para campos pessoais, o valor é omitido mesmo que seja informado.
    """
    partes = [f"etapa={etapa}", f"nivel={nivel}"]
    if registro is not None:
        partes.append(f"registro={registro}")
    partes.append(f"campo={campo}")
    if valor is not None and campo not in CAMPOS_PESSOAIS:
        partes.append(f"valor={valor}")
    partes.append(f'motivo="{motivo}"')

    logger_rejeitados.log(severidade, " ".join(partes))
    __rejeicoes[nivel] += 1


def registrar_resultados_validacao(
    resultados: list[dict], nivel: str = "leitura"
) -> dict[str, int]:
    """
    Grava no log de rejeitados o que a validação recusou e devolve as contagens.

    - Registro inválido: uma linha por motivo (os campos nulos vêm juntos numa
      linha só, ex.: campo=estacao_codigo,operador_codigo). As medições dele não
      são listadas, porque o registro inteiro não é gravado.
    - Registro válido: uma linha por medição descartada (nula ou fora da faixa).
    """
    contagens = Counter()
    for resultado in resultados:
        registro = resultado["registro_codigo"]
        if not resultado["valido"]:
            contagens["registros_invalidos"] += 1
            for motivo in resultado["motivos"]:
                registrar_rejeicao(
                    motivo["etapa"],
                    nivel,
                    motivo["campo"],
                    motivo["motivo"],
                    registro=registro,
                    valor=motivo["valor"],
                    severidade=logging.WARNING if nivel == "leitura" else logging.ERROR,
                )
            continue

        contagens["registros_validos"] += 1
        contagens["itens_validos"] += len(resultado["registro"]["itens"])
        contagens["itens_invalidos"] += len(resultado["itens_invalidos"])
        for item in resultado["itens_invalidos"]:
            registrar_rejeicao(
                item["etapa"],
                nivel,
                item["campo"],
                item["motivo"],
                registro=registro,
                valor=item["valor"],
                severidade=logging.WARNING if nivel == "leitura" else logging.ERROR,
            )

    return {
        chave: contagens[chave]
        for chave in (
            "registros_validos",
            "registros_invalidos",
            "itens_validos",
            "itens_invalidos",
        )
    }


def contar_rejeicoes() -> dict[str, int]:
    """Quantidade de rejeições registradas por nível desde a última configuração."""
    return dict(__rejeicoes)


def registrar_resumo(**contagens: int) -> None:
    """Registra a linha INFO de resumo da execução."""
    texto = " ".join(f"{nome}={valor}" for nome, valor in contagens.items())
    logger.info(f"Resumo da ingestão: {texto}")


def registrar_anomalias(anomalias: list[dict]) -> None:
    """
    Registra em WARNING, no log da execução, cada medição sinalizada pela
    análise (AnaliticsService): é a evidência da detecção de outliers.
    """
    for anomalia in anomalias:
        limites = (
            f"[{anomalia['Limite Inferior']:.4g}, {anomalia['Limite Superior']:.4g}]"
            if anomalia["Limite Inferior"] is not None
            else "[sem IQR]"
        )
        zscore = (
            f"{anomalia['Z-Score']:.2f}"
            if anomalia["Z-Score"] is not None
            else "indefinido"
        )
        logger.warning(
            f'Alerta de qualidade: alerta={anomalia["Alerta"]} estacao="{anomalia["Estação"]}" '
            f'registro={anomalia["Registro"]} parametro="{anomalia["Parâmetro"]}" '
            f"data_hora={anomalia['Data']} valor={anomalia['Valor']} limites_iqr={limites} zscore={zscore}"
        )


# --- Agente analítico (docs/agente/arquitetura.md § 12) ----------------------
# Recebem textos JÁ mascarados por src/security.py (pergunta) e nunca o texto
# completo da resposta nem trechos de documentos (volume e LGPD).


def registrar_pergunta_agente(conversa_id: str, pergunta_mascarada: str) -> None:
    """Linha INFO da pergunta recebida, já com CPF, e-mail e telefone mascarados (DA5)."""
    logger.info(f'Agente: pergunta conversa={conversa_id} texto="{pergunta_mascarada}"')


def registrar_chamada_ferramenta(
    conversa_id: str, ferramenta: str, argumentos_json: str, sucesso: bool, ms: int, erro: str | None = None
) -> None:
    """
    Linha da ferramenta executada: INFO no sucesso, WARNING no erro.

    Os argumentos bastam para reproduzir o cálculo, por isso entram no log.
    """
    if sucesso:
        logger.info(f"Agente: ferramenta={ferramenta} conversa={conversa_id} args={argumentos_json} sucesso=sim ms={ms}")
    else:
        logger.warning(
            f'Agente: ferramenta={ferramenta} conversa={conversa_id} args={argumentos_json} sucesso=nao ms={ms} erro="{erro}"'
        )


def registrar_resposta_agente(
    conversa_id: str, ferramentas: int, tokens_entrada: int, tokens_saida: int, ms: int
) -> None:
    """Linha INFO da resposta enviada: quantas ferramentas, tokens (custo) e tempo."""
    logger.info(
        f"Agente: resposta conversa={conversa_id} ferramentas={ferramentas} "
        f"tokens_entrada={tokens_entrada} tokens_saida={tokens_saida} ms={ms}"
    )


def registrar_guardrail(politica: str, conversa_id: str, **detalhes) -> None:
    """
    Linha WARNING de uma política de segurança acionada (POL-13), sem dado pessoal.

    Ex.: Agente: guardrail=POL-03 conversa=c-3f9a acao=correcao numeros=2
    """
    extras = "".join(f" {chave}={valor}" for chave, valor in detalhes.items())
    logger.warning(f"Agente: guardrail={politica} conversa={conversa_id}{extras}")


def registrar_falha_llm(conversa_id: str, tipo_erro: str) -> None:
    """Linha ERROR de falha do provedor do LLM: só o tipo do erro, nunca a chave nem a mensagem (POL-10)."""
    logger.error(f"Agente: falha no provedor de LLM conversa={conversa_id} erro={tipo_erro}")
