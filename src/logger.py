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

logger = logging.getLogger(NOME_LOGGER)
logger_rejeitados = logging.getLogger(NOME_LOGGER_REJEITADOS)

__rejeicoes: Counter = Counter()


def configurar_logs(pasta: Path | None = None) -> dict[str, Path]:
    """
    Configura o log da execução (console + arquivo) e o log de rejeitados.

    Deve ser chamada uma única vez, no início do main.py. A pasta padrão é
    logs/ na raiz do projeto; a variável de ambiente PASTA_LOGS a substitui
    (usada pelos testes para não misturar seus arquivos com os de cargas reais).
    Retorna o caminho dos dois arquivos criados.
    """
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


def registrar_resultados_validacao(resultados: list[dict]) -> dict[str, int]:
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
                    motivo["etapa"], "leitura", motivo["campo"], motivo["motivo"],
                    registro=registro, valor=motivo["valor"],
                )
            continue

        contagens["registros_validos"] += 1
        contagens["itens_validos"] += len(resultado["registro"]["itens"])
        contagens["itens_invalidos"] += len(resultado["itens_invalidos"])
        for item in resultado["itens_invalidos"]:
            registrar_rejeicao(
                item["etapa"], "item", item["campo"], item["motivo"],
                registro=registro, valor=item["valor"],
            )

    return {
        chave: contagens[chave]
        for chave in ("registros_validos", "registros_invalidos", "itens_validos", "itens_invalidos")
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
        zscore = f"{anomalia['Z-Score']:.2f}" if anomalia["Z-Score"] is not None else "indefinido"
        logger.warning(
            f"Alerta de qualidade: alerta={anomalia['Alerta']} estacao=\"{anomalia['Estação']}\" "
            f"registro={anomalia['Registro']} parametro=\"{anomalia['Parâmetro']}\" "
            f"data_hora={anomalia['Data']} valor={anomalia['Valor']} limites_iqr={limites} zscore={zscore}"
        )
