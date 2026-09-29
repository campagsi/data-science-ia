import sys
from datetime import date
from typing import Any

from src.cli.console_app import Console_APP
from src.config import load_config
from src.database.connection import DatabaseConnection
from src.database.criar_tabelas import criar_tabelas
from src.ingestion.data_client import DataClient
from src.repository.leitura_repository import LeituraRepository
from src.services.analytics_service import AnaliticsService
from src.services.normalization_service import NormalizationService
from src.services.report_service import ReportService
from src.services.validation_service import ValidationService


def run_pipeline() -> dict[str, Any]:
    """Coordena configuração, ingestão, persistência, análise e relatório."""
    settings = load_config()
    raw_data = DataClient(settings).fetch_data()
    normalized_data = NormalizationService().normalize(raw_data)
    validated_data = ValidationService().validate_data(normalized_data)

    database = DatabaseConnection(settings.azure_sql_connectionstring)
    criar_tabelas()
    LeituraRepository(database).save_readings(validated_data)

    service = AnaliticsService(database)
    indicadores = service.calculate_metrics(
        cidade_id=1,
        data_inicio=date(2026, 6, 1),
        data_fim=date(2026, 12, 1),
    )
    return ReportService().generate_report(indicadores)


def _exibir_resultados(resultados: dict[str, Any]) -> None:
    """Exibe no console o relatório textual produzido pelo pipeline."""
    texto = ReportService().format_report(resultados)
    if texto:
        print(texto)


if __name__ == "__main__":
    try:
        # _exibir_resultados(run_pipeline())
        console_app = Console_APP()
        console_app.run()
    except Exception as erro:
        print(f"{type(erro).__name__}: {erro}", file=sys.stderr)
        raise SystemExit(1) from erro
