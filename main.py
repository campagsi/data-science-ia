import sys
from datetime import date
from typing import Any

from src.cli.console_app import Console_APP
from src.config import Settings, load_config
from src.database.connection import DatabaseConnection
from src.ingestion.data_client import DataClient
from src.logger import configurar_logs, logger, registrar_resultados_validacao, registrar_resumo
from src.repository.estado_repository import EstadoRepository
from src.repository.leitura_repository import LeituraRepository
from src.repository.parametro_repository import ParametroRepository
from src.security import configurar_seguranca
from src.services.analytics_service import AnaliticsService
from src.services.normalization_service import NormalizationService
from src.services.parametro_service import ParametroService
from src.services.report_service import ReportService
from src.services.validation_service import ValidationService


def run_pipeline() -> dict[str, int]:
    """
    Executa a ingestão: coleta, normalização, cadastro de parâmetros, validação
    e gravação idempotente no banco. Devolve o resumo da execução.
    """
    settings = load_config()
    raw_data = DataClient(settings).fetch_data()
    normalized_data = NormalizationService().normalize(raw_data)

    # O schema é mantido por sql/ddl_banco_relacional.sql e sql/migrations/.
    database = DatabaseConnection(settings.azure_sql_connectionstring)

    # Parâmetros novos são cadastrados antes da validação, que usa as faixas de
    # Parametros e as siglas de Estados lidas do banco.
    parametros = ParametroService(ParametroRepository(database)).sincronizar(
        NormalizationService.descobrir_parametros(normalized_data)
    )
    siglas = {estado.sigla for estado in EstadoRepository(database).get_all()}
    resultados = ValidationService(
        faixas=ParametroService.faixas(parametros),
        siglas_estados=siglas,
        parametros_validos=set(parametros),
    ).validate_data(normalized_data)
    validacao = registrar_resultados_validacao(resultados)
    validated_data = ValidationService.registros_validos(resultados)

    gravacao = LeituraRepository(database).save_readings(
        validated_data, parametros, settings.fonte_dados
    )

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


def gerar_relatorio(database: DatabaseConnection) -> dict[str, Any]:
    """
    Análise estatística e relatório da Parte 1.

    Ainda consulta o modelo antigo (Cidades e Leituras larga); será adaptada ao
    modelo 3FN na fase de analytics e, até lá, não é chamada pela ingestão.
    """
    indicadores = AnaliticsService(database).calculate_metrics(
        cidade_id=1,
        data_inicio=date(2026, 6, 1),
        data_fim=date(2026, 12, 1),
    )
    return ReportService().generate_report(indicadores)


def iniciar_aplicacao() -> Settings:
    """Prepara logs, configuração e chaves antes de qualquer etapa da aplicação."""
    configurar_logs()
    settings = load_config()
    configurar_seguranca(settings.chave_criptografia, settings.pepper_hash)
    logger.info("Configuração carregada e segurança inicializada.")
    return settings


def _exibir_resultados(resultados: dict[str, Any]) -> None:
    """Registra no log o relatório textual produzido pelo pipeline."""
    texto = ReportService().format_report(resultados)
    if texto:
        logger.info(f"Relatório da execução:\n{texto}")


if __name__ == "__main__":
    try:
        iniciar_aplicacao()
        if "--ingestao" in sys.argv[1:]:
            run_pipeline()
        else:
            console_app = Console_APP()
            console_app.run()
    except Exception as erro:
        logger.critical(f"{type(erro).__name__}: {erro}")
        raise SystemExit(1) from erro
