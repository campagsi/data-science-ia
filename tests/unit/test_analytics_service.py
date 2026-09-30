"""Cálculo estatístico com dados determinísticos (CT-04 e CT-05 do plano de testes)."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.services.analytics_service import AnaliticsService

INICIO = datetime(2026, 6, 1)


class DatabaseFalso:
    """Devolve linhas fixas para as consultas de qualidade da água e meteorológica."""

    def __init__(self, linhas_agua, linhas_meteorologicas=()):
        self.__linhas_agua = linhas_agua
        self.__linhas_meteorologicas = list(linhas_meteorologicas)

    def fetch_all(self, sql, params=None):
        if "temperatura_agua" in sql:
            return self.__linhas_agua
        return self.__linhas_meteorologicas


def linhas_agua(oxigenio, condutividade):
    # Colunas: temperatura_agua, ph, oxigenio_dissolvido, condutividade, turbidez, data_hora
    return [
        (22.0, 7.0, oxigenio[i], condutividade[i], 5.0, INICIO + timedelta(hours=i))
        for i in range(len(oxigenio))
    ]


def estatistica(analise, medicao):
    return next(e for e in analise["Estatísticas"] if e["Medição"] == medicao)


def test_ct04_amostra_uniforme_nao_gera_outlier():
    linhas = linhas_agua(oxigenio=[6.0] * 10, condutividade=[430.0] * 10)
    service = AnaliticsService(DatabaseFalso(linhas))

    analise, outliers = service.analisar_leituras_qualidade_agua_estacao(1)

    condutividade = estatistica(analise, "Condutividade elétrica a 25 °C")
    assert condutividade["Desvio Padrão"] == 0
    assert condutividade["Média"] == condutividade["Mediana"] == 430.0
    assert len(outliers) == 0


def test_ct05_ponto_destoante_e_identificado_como_outlier():
    oxigenio = [6.0 + (i % 5) * 0.1 for i in range(99)] + [0.05]
    linhas = linhas_agua(oxigenio=oxigenio, condutividade=[430.0] * 100)
    service = AnaliticsService(DatabaseFalso(linhas))

    analise, outliers = service.analisar_leituras_qualidade_agua_estacao(1)

    assert analise["Quantide Leituras"] == 100
    # Aceita DataFrame ou lista de registros como retorno de outliers.
    registros = pd.DataFrame(outliers).to_dict(orient="records")
    assert [(r["Variável"], r["Valor"]) for r in registros] == [("oxigenio_dissolvido", 0.05)]
    assert registros[0]["Valor"] < registros[0]["Limite Inferior"]


def test_calculate_metrics_consolida_os_dois_grupos():
    agua = linhas_agua(oxigenio=[6.0] * 5, condutividade=[430.0] * 5)
    # Colunas: temperatura, pressao, umidade, precipitacao, velocidade_vento, radiacao_solar, data_hora
    meteorologicas = [(20.0, 1013.0, 80.0, 0.0, 10.0, 0.0, INICIO + timedelta(hours=i)) for i in range(3)]
    service = AnaliticsService(DatabaseFalso(agua, meteorologicas))

    indicadores = service.calculate_metrics(estacao_id=1)

    assert indicadores["escopo"] == {"estacao_id": 1}
    assert indicadores["qualidade_agua"]["analise"]["Quantide Leituras"] == 5
    assert indicadores["meteorologica"]["analise"]["Quantide Leituras"] == 3


@pytest.mark.parametrize("kwargs", [{}, {"cidade_id": 1, "estacao_id": 1}])
def test_calculate_metrics_exige_um_unico_escopo(kwargs):
    with pytest.raises(ValueError):
        AnaliticsService(DatabaseFalso([])).calculate_metrics(**kwargs)
