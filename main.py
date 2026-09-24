from datetime import date
import sys
from typing import Any

import pandas as pd

from src.config import load_config
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

    criar_tabelas()
    LeituraRepository().save_readings(validated_data)

    service = AnaliticsService()
    indicadores = service.calculate_metrics(
        cidade_id=1,
        data_inicio=date(2026, 6, 1),
        data_fim=date(2026, 12, 1),
    )
    return ReportService().generate_report(indicadores)


def _exibir_resultados(resultados: dict[str, Any]) -> None:
    """Exibe no console os resultados produzidos pelo pipeline."""
    for grupo in resultados["grupos"].values():
        analise = grupo["analise"]
        outliers = pd.DataFrame(grupo["outliers"])

        if analise["Estatísticas"]:
            print(pd.DataFrame(analise["Estatísticas"]).to_string(index=False))
        else:
            print("Nenhuma leitura encontrada.")

        if outliers.empty:
            print("Nenhum outlier identificado pelo método IQR.")
        else:
            print(
                outliers.round(
                    {
                        "valor": 2,
                        "Valor": 2,
                        "Limite Inferior": 2,
                        "Limite Superior": 2,
                    }
                ).to_string(index=False)
            )


if __name__ == "__main__":
    try:
        _exibir_resultados(run_pipeline())
    except Exception as erro:
        print(f"{type(erro).__name__}: {erro}", file=sys.stderr)
        raise SystemExit(1) from erro
