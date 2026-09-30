from datetime import date

import pandas as pd
import pytest

from src.services.report_service import ReportService

ESTATISTICAS = [
    {
        "Medição": "pH",
        "Unidade": "ph",
        "Quantidade": 3,
        "Média": 7.1,
        "Mediana": 7.0,
        "Desvio Padrão": 0.1,
    }
]
OUTLIER = {
    "Estação": "EST-1",
    "Variável": "ph",
    "Data": "2026-06-01",
    "Valor": 9.123,
    "Limite Inferior": 6.456,
    "Limite Superior": 8.789,
}


@pytest.fixture
def indicadores():
    return {
        "escopo": {"cidade_id": 1},
        "periodo": {"data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30)},
        "meteorologica": {
            "analise": {"Quantide Leituras": 3, "Estatísticas": ESTATISTICAS},
            "outliers": pd.DataFrame([OUTLIER]),
        },
        "qualidade_agua": {
            "analise": {"Quantide Leituras": 3, "Estatísticas": ESTATISTICAS},
            "outliers": [OUTLIER],
        },
        "ignorado": {"analise": {}, "outliers": []},
    }


def test_generate_report_preserva_escopo_periodo_e_grupos(indicadores):
    relatorio = ReportService().generate_report(indicadores)

    assert relatorio["escopo"] == {"cidade_id": 1}
    assert relatorio["periodo"] == indicadores["periodo"]
    assert set(relatorio["grupos"]) == {"meteorologica", "qualidade_agua"}


def test_generate_report_converte_outliers_para_registros(indicadores):
    relatorio = ReportService().generate_report(indicadores)

    for grupo in relatorio["grupos"].values():
        assert grupo["outliers"] == [OUTLIER]
        assert grupo["analise"]["Estatísticas"] == ESTATISTICAS


def test_format_report_exibe_estatisticas_e_outliers(indicadores):
    servico = ReportService()

    texto = servico.format_report(servico.generate_report(indicadores))

    assert texto.count("pH") >= 2
    assert "9.12" in texto
    assert "6.46" in texto


def test_format_report_sem_leituras_e_sem_outliers():
    relatorio = {
        "grupos": {
            "meteorologica": {"analise": {"Estatísticas": []}, "outliers": []},
        }
    }

    texto = ReportService().format_report(relatorio)

    assert texto == "Nenhuma leitura encontrada.\nNenhum outlier identificado pelo método IQR."
