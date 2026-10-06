from datetime import date, datetime

import pandas as pd
import pytest

from src.services.report_service import COLUNAS_ANOMALIAS, ReportService

ESTATISTICA = {
    "Estação": "Estação Norte", "Código": "TIP-PH", "Parâmetro": "pH", "Unidade": "pH",
    "Quantidade": 3, "Média": 7.1234, "Mediana": 7.0, "Desvio Padrão": 0.1, "Variância": 0.01,
    "Q1": 6.9, "Q3": 7.3, "IQR": 0.4, "Mínimo": 6.8, "Máximo": 7.5,
    "Limite Inferior": 6.3, "Limite Superior": 7.9, "Anomalias": 1,
}
ANOMALIA = {
    "Estação": "Estação Norte", "Parâmetro": "pH", "Unidade": "pH", "Data": datetime(2026, 6, 1, 3),
    "Registro": "R-1", "Valor": 9.123, "Limite Inferior": 6.456, "Limite Superior": 8.789,
    "Z-Score": 3.456, "Alerta": "IQR+ZSCORE",
}


@pytest.fixture
def indicadores():
    return {
        "escopo": {"estacao_id": 1},
        "periodo": {"data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30)},
        "leituras": 3,
        "medicoes": 3,
        "estatisticas": [ESTATISTICA],
        "anomalias": [ANOMALIA],
    }


def test_generate_report_preserva_todos_os_campos(indicadores):
    assert ReportService().generate_report(indicadores) == indicadores


def test_generate_report_com_indicadores_vazios():
    assert ReportService().generate_report({}) == {
        "escopo": {}, "periodo": {}, "leituras": 0, "medicoes": 0, "estatisticas": [], "anomalias": [],
    }


def test_format_report_exibe_metricas_e_anomalias_arredondadas(indicadores):
    texto = ReportService().format_report(ReportService().generate_report(indicadores))

    assert "Leituras analisadas: 3 | medições: 3 | anomalias: 1" in texto
    assert "Variância" in texto and "IQR" in texto and "Z-Score" in texto
    assert "7.12" in texto and "9.12" in texto and "3.46" in texto
    assert "IQR+ZSCORE" in texto


def test_format_report_sem_anomalias(indicadores):
    indicadores["anomalias"] = []

    texto = ReportService().format_report(ReportService().generate_report(indicadores))

    assert "Nenhuma anomalia identificada (IQR e Z-Score)." in texto


def test_format_report_sem_leituras():
    assert ReportService().format_report(ReportService().generate_report({})) == "Nenhuma leitura encontrada."


def test_salvar_csv_cria_a_pasta_e_os_dois_arquivos(indicadores, tmp_path):
    arquivos = ReportService().salvar_csv(indicadores, tmp_path / "relatorios")

    estatisticas = pd.read_csv(arquivos["estatisticas"], sep=";", encoding="utf-8-sig")
    anomalias = pd.read_csv(arquivos["anomalias"], sep=";", encoding="utf-8-sig")
    assert list(estatisticas.columns) == list(ESTATISTICA)
    assert anomalias.loc[0, "Alerta"] == "IQR+ZSCORE"


def test_salvar_csv_sem_anomalias_mantem_o_cabecalho(indicadores, tmp_path):
    indicadores["anomalias"] = []

    arquivos = ReportService().salvar_csv(indicadores, tmp_path)

    cabecalho = arquivos["anomalias"].read_text(encoding="utf-8-sig").splitlines()[0]
    assert cabecalho.split(";") == list(COLUNAS_ANOMALIAS) + ["Unidade"]
