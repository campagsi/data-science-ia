import argparse
import sys
from datetime import date
from typing import Any

from src.cli.console_app import Console_APP
from src.config import Settings, load_config
from src.database.connection import DatabaseConnection
from src.ingestion.data_client import DataClient
from src.ingestion.extracao_dados import Extracao_Dados
from src.logger import (
    configurar_logs,
    logger,
    registrar_anomalias,
    registrar_resultados_validacao,
    registrar_resumo,
)
from src.repository.estado_repository import EstadoRepository
from src.repository.leitura_repository import LeituraRepository
from src.repository.parametro_repository import ParametroRepository
from src.security import configurar_seguranca
from src.services.analytics_service import AnaliticsService
from src.services.normalization_service import NormalizationService
from src.services.parametro_service import ParametroService
from src.services.report_service import ReportService
from src.services.validation_service import ValidationService

# Chaves do resumo da ingestão, na ordem em que aparecem no log.
_CAMPOS_RESUMO = (
    "recebidos",
    "rejeitados_na_normalizacao",
    "registros_validos",
    "registros_invalidos",
    "itens_descartados",
    "leituras_gravadas",
    "leituras_substituidas",
    "itens_gravados",
)


def run_pipeline() -> dict[str, int]:
    """
    Executa a ingestão: coleta, normalização, cadastro de parâmetros, validação
    e gravação idempotente no banco. Devolve o resumo da execução.

    Nenhum registro chega ao banco sem passar pela validação (etapa 5), e nada
    do que é recusado se perde: tudo vai para o log de rejeitados (etapa 6).
    """
    # 1. Coleta: busca o lote bruto (JSON) na API configurada em FONTE_DADOS,
    #    com novas tentativas para queda de conexão, 5xx e 429 e limite de
    #    requisições por minuto. Lote vazio encerra aqui, sem tocar no banco.
    settings = load_config()
    raw_data = DataClient(settings).fetch_data()
    if not raw_data:
        resumo = dict.fromkeys(_CAMPOS_RESUMO, 0)
        registrar_resumo(**resumo)
        return resumo

    # 2. Tratamento: texto vazio vira None, números e datas são convertidos,
    #    cada registro vira cabeçalho + itens (um por parâmetro) e CPF, nome e
    #    e-mail do operador são anonimizados. Valor que não pode ser convertido
    #    é rejeitado e logado aqui, sem derrubar o lote; medição vazia segue
    #    como None para a validação decidir.
    normalized_data = NormalizationService().normalize(raw_data)

    # O schema é mantido por sql/ddl_banco_relacional.sql e sql/migrations/.
    database = DatabaseConnection(settings.azure_sql_connectionstring)

    # 3. Parâmetros: os encontrados no lote (*_tipo_codigo) e ainda não
    #    cadastrados são inseridos em Parametros, sem faixa. Volta o mapa
    #    código → parâmetro aceito, com id e faixa de valores.
    parametros = ParametroService(ParametroRepository(database)).sincronizar(
        NormalizationService.descobrir_parametros(normalized_data)
    )

    # 4. Referência: siglas de Estados, para conferir o estado de cada leitura.
    siglas = {estado.sigla for estado in EstadoRepository(database).get_all()}

    # 5. Validação, antes de qualquer gravação. Não grava nem loga: devolve um
    #    resultado por registro (valido, campos_nulos, itens_invalidos, motivos).
    #    - completude: campo vital nulo rejeita a leitura; medição nula descarta
    #      só o item; leitura sem nenhuma medição válida é rejeitada;
    #    - acurácia: valor fora da faixa do parâmetro descarta só o item;
    #    - referência e validade: estado inexistente ou sigla inválida;
    #    - unicidade: registro repetido no lote e cadastro divergente.
    resultados = ValidationService(
        faixas=ParametroService.faixas(parametros),
        siglas_estados=siglas,
        parametros_validos=set(parametros),
    ).validate_data(normalized_data)

    # 6. Log de rejeitados a partir dos resultados: uma linha por leitura
    #    recusada e uma por medição descartada (sem dado pessoal).
    validacao = registrar_resultados_validacao(resultados)

    # 7. Filtro: só os registros com valido=True, já sem os itens descartados.
    validated_data = ValidationService.registros_validos(resultados)

    # 8. Gravação idempotente, numa única transação: municípios, operadores e
    #    estações por MERGE; leituras e itens substituindo as partições
    #    estação + dia. Reexecutar o mesmo período não duplica; se algo falhar,
    #    nada do lote fica gravado.
    gravacao = LeituraRepository(database).save_readings(
        validated_data, parametros, settings.fonte_dados
    )

    # 9. Resumo da execução no log (e retorno da função).
    resumo = {
        "recebidos": len(raw_data),
        "rejeitados_na_normalizacao": len(raw_data) - len(normalized_data),
        "registros_validos": validacao["registros_validos"],
        "registros_invalidos": validacao["registros_invalidos"],
        "itens_descartados": validacao["itens_invalidos"],
        "leituras_gravadas": gravacao["leituras_gravadas"],
        "leituras_substituidas": gravacao["leituras_removidas"],
        "itens_gravados": gravacao["itens_gravados"],
    }
    registrar_resumo(**resumo)
    return resumo


def gerar_relatorio(
    database: DatabaseConnection,
    codigo_estacao: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> dict[str, Any]:
    """
    Análise estatística das medições gravadas (item 3.4 do enunciado).

    Sem estação, analisa todas. Registra o relatório em INFO e cada medição
    anômala em WARNING no log da execução. Devolve o relatório estruturado.
    """
    analise = AnaliticsService(database)
    estacao_id = None
    if codigo_estacao is not None:
        estacao = analise.buscar_estacao_por_codigo(codigo_estacao)
        if estacao is None:
            raise ValueError(f"Estação não cadastrada: {codigo_estacao}")
        estacao_id = estacao.id_estacao

    relatorio = ReportService().generate_report(
        analise.calculate_metrics(
            estacao_id=estacao_id, data_inicio=data_inicio, data_fim=data_fim
        )
    )
    _exibir_resultados(relatorio)
    registrar_anomalias(relatorio["anomalias"])
    return relatorio


def iniciar_aplicacao(etapa: str) -> Settings:
    """
    Prepara logs, configuração e chaves antes de qualquer etapa da aplicação.

    etapa ("ingestao", "analise" ou "consulta") vai para o cabeçalho dos logs.
    """
    configurar_logs(etapa)
    settings = load_config()
    configurar_seguranca(settings.chave_criptografia, settings.chave_hash)
    logger.info("Configuração carregada e segurança inicializada.")
    return settings


def _exibir_resultados(resultados: dict[str, Any]) -> None:
    """Registra no log o relatório textual produzido pelo pipeline."""
    texto = ReportService().format_report(resultados)
    if texto:
        logger.info(f"Relatório da execução:\n{texto}")


def ler_argumentos(argv: list[str]) -> argparse.Namespace:
    """Sem argumentos abre a CLI; --ingestao carrega o banco; --analise gera o relatório."""
    parser = argparse.ArgumentParser(description="Pipeline de dados ambientais")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--ingestao", action="store_true", help="coleta, valida e grava no banco"
    )
    modo.add_argument(
        "--analise",
        action="store_true",
        help="estatística e outliers das medições gravadas",
    )
    parser.add_argument(
        "--estacao", metavar="CODIGO", help="código da estação (padrão: todas)"
    )
    parser.add_argument(
        "--inicio",
        type=date.fromisoformat,
        metavar="AAAA-MM-DD",
        help="sozinha, analisa só esse dia",
    )
    parser.add_argument("--fim", type=date.fromisoformat, metavar="AAAA-MM-DD")
    argumentos = parser.parse_args(argv)

    if not argumentos.analise and (
        argumentos.estacao or argumentos.inicio or argumentos.fim
    ):
        parser.error("--estacao, --inicio e --fim só valem com --analise")
    if argumentos.fim and not argumentos.inicio:
        parser.error("--fim exige --inicio")
    if argumentos.inicio and argumentos.fim and argumentos.inicio > argumentos.fim:
        parser.error("--inicio não pode ser maior que --fim")
    return argumentos


def etapa_da_execucao(argumentos: argparse.Namespace) -> str:
    """Etapa registrada no cabeçalho dos logs (chave de src.logger.ETAPAS)."""
    if argumentos.ingestao:
        return "ingestao"
    if argumentos.analise:
        return "analise"
    return "consulta"


if __name__ == "__main__":
    argumentos = ler_argumentos(sys.argv[1:])
    try:
        settings = iniciar_aplicacao(etapa_da_execucao(argumentos))
        Extracao_Dados().execute()

        # if argumentos.ingestao:
        #     run_pipeline()
        # elif argumentos.analise:
        #     gerar_relatorio(
        #         DatabaseConnection(settings.azure_sql_connectionstring),
        #         argumentos.estacao,
        #         argumentos.inicio,
        #         argumentos.fim,
        #     )
        # else:
        #     console_app = Console_APP()
        #     console_app.run()
    except Exception as erro:
        logger.critical(f"{type(erro).__name__}: {erro}")
        raise SystemExit(1) from erro
