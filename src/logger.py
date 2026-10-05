"""
Configuração única de logs do projeto.

Nenhum outro módulo chama logging.basicConfig ou print: todos obtêm o logger
com logging.getLogger(NOME_LOGGER). As regras estão em docs/seguranca-lgpd.md.
"""

import logging
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

logger = logging.getLogger(NOME_LOGGER)
logger_rejeitados = logging.getLogger(NOME_LOGGER_REJEITADOS)

__rejeicoes: Counter = Counter()


def configurar_logs(pasta: Path = PASTA_LOGS) -> dict[str, Path]:
    """
    Configura o log da execução (console + arquivo) e o log de rejeitados.

    Deve ser chamada uma única vez, no início do main.py. Retorna o caminho
    dos dois arquivos criados.
    """
    pasta = Path(pasta)
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

    __rejeicoes.clear()
    return arquivos


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


def contar_rejeicoes() -> dict[str, int]:
    """Quantidade de rejeições registradas por nível desde a última configuração."""
    return dict(__rejeicoes)


def registrar_resumo(**contagens: int) -> None:
    """Registra a linha INFO de resumo da execução."""
    texto = " ".join(f"{nome}={valor}" for nome, valor in contagens.items())
    logger.info(f"Resumo da ingestão: {texto}")
