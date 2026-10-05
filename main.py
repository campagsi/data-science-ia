from datetime import date
from typing import Any

from src.cli.console_app import Console_APP
from src.config import Settings, load_config
from src.database.connection import DatabaseConnection
from src.ingestion.data_client import DataClient
from src.logger import configurar_logs, logger, registrar_resultados_validacao
from src.repository.leitura_repository import LeituraRepository
from src.security import configurar_seguranca
from src.services.analytics_service import AnaliticsService
from src.services.normalization_service import NormalizationService
from src.services.report_service import ReportService
from src.services.validation_service import ValidationService


def run_pipeline() -> dict[str, Any]:
    """Coordena configuração, ingestão, persistência, análise e relatório."""
    settings = load_config()
    raw_data = DataClient(settings).fetch_data()
    normalized_data = NormalizationService().normalize(raw_data)
    # Faixas de Parametros e siglas de Estados passam a vir do banco na fase 8.
    resultados = ValidationService().validate_data(normalized_data)
    registrar_resultados_validacao(resultados)
    validated_data = ValidationService.registros_validos(resultados)

    # O schema é mantido por sql/ddl_banco_relacional.sql e sql/migrations/.
    database = DatabaseConnection(settings.azure_sql_connectionstring)
    LeituraRepository(database).save_readings(validated_data)

    service = AnaliticsService(database)
    indicadores = service.calculate_metrics(
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
        # _exibir_resultados(run_pipeline())
        console_app = Console_APP()
        console_app.run()
    except Exception as erro:
        logger.critical(f"{type(erro).__name__}: {erro}")
        raise SystemExit(1) from erro
