"""Estatística e outliers por estação e parâmetro (CT-04, CT-05 e CT-14 do plano de testes)."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from src.services.analytics_service import (
    ALERTA_AMBOS,
    ALERTA_IQR,
    ALERTA_ZSCORE,
    AnaliticsService,
)

INICIO = datetime(2026, 6, 1)


def medicoes(valores, codigo="TIP-OXI", estacao="EST-1"):
    """Linhas no formato de LeituraRepository.get_medicoes(), uma por hora."""
    return [
        {
            "estacao_id": 1,
            "estacao_codigo": estacao,
            "estacao": f"Estação {estacao}",
            "codigo_registro": f"{estacao}-{codigo}-{i}",
            "data_hora": INICIO + timedelta(hours=i),
            "codigo_parametro": codigo,
            "parametro": f"Parâmetro {codigo}",
            "unidade_medida": "mg/L",
            "valor": valor,
        }
        for i, valor in enumerate(valores)
    ]


def analisar(linhas):
    return AnaliticsService.analisar_medicoes(linhas)


def test_ct04_amostra_uniforme_nao_gera_outlier():
    resultado = analisar(medicoes([430.0] * 10))

    (estatistica,) = resultado["estatisticas"]
    assert estatistica["IQR"] == 0
    assert estatistica["Desvio Padrão"] == 0
    assert estatistica["Variância"] == 0
    assert estatistica["Anomalias"] == 0
    assert resultado["anomalias"] == []


def test_ct05_ponto_destoante_e_sinalizado_por_iqr_e_zscore():
    valores = [6.0 + (i % 5) * 0.1 for i in range(99)] + [0.05]

    resultado = analisar(medicoes(valores))

    (anomalia,) = resultado["anomalias"]
    assert anomalia["Valor"] == 0.05
    assert anomalia["Valor"] < anomalia["Limite Inferior"]
    assert anomalia["Z-Score"] < -3
    assert anomalia["Alerta"] == ALERTA_AMBOS
    assert anomalia["Registro"] == "EST-1-TIP-OXI-99"
    assert resultado["estatisticas"][0]["Anomalias"] == 1


def test_metricas_exigidas_pelo_enunciado():
    valores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    serie = pd.Series(valores)

    (estatistica,) = analisar(medicoes(valores))["estatisticas"]

    assert estatistica["Quantidade"] == 8
    assert estatistica["Média"] == pytest.approx(4.5)
    assert estatistica["Mediana"] == pytest.approx(4.5)
    assert estatistica["Desvio Padrão"] == pytest.approx(serie.std())
    assert estatistica["Variância"] == pytest.approx(serie.var())
    assert estatistica["Q1"] == pytest.approx(serie.quantile(0.25))
    assert estatistica["Q3"] == pytest.approx(serie.quantile(0.75))
    assert estatistica["IQR"] == pytest.approx(serie.quantile(0.75) - serie.quantile(0.25))
    assert (estatistica["Mínimo"], estatistica["Máximo"]) == (1.0, 8.0)
    assert estatistica["Limite Inferior"] == pytest.approx(estatistica["Q1"] - 1.5 * estatistica["IQR"])
    assert estatistica["Limite Superior"] == pytest.approx(estatistica["Q3"] + 1.5 * estatistica["IQR"])
    assert (estatistica["Código"], estatistica["Unidade"]) == ("TIP-OXI", "mg/L")


def test_outlier_so_pelo_iqr():
    # 7 iguais e um ponto acima: fora do IQR (IQR = 0), mas com |Z| < 3.
    resultado = analisar(medicoes([10.0] * 7 + [12.0]))

    (anomalia,) = resultado["anomalias"]
    assert anomalia["Alerta"] == ALERTA_IQR
    assert abs(anomalia["Z-Score"]) <= 3


def test_outlier_so_pelo_zscore():
    # Bimodal (Q1 = 0, Q3 = 10, limite superior 25): o 24 fica dentro do IQR,
    # mas a mais de 3 desvios da média.
    resultado = analisar(medicoes([0.0] * 50 + [10.0] * 50 + [24.0]))

    (anomalia,) = resultado["anomalias"]
    assert anomalia["Valor"] == 24.0
    assert anomalia["Alerta"] == ALERTA_ZSCORE
    assert anomalia["Valor"] <= anomalia["Limite Superior"]
    assert anomalia["Z-Score"] > 3


def test_amostra_pequena_nao_aplica_iqr_e_um_valor_nao_tem_zscore():
    resultado = analisar(medicoes([1.0, 50.0, 2.0]) + medicoes([5.0], codigo="TIP-PH"))

    por_codigo = {e["Código"]: e for e in resultado["estatisticas"]}
    assert por_codigo["TIP-OXI"]["Limite Inferior"] is None
    assert por_codigo["TIP-OXI"]["Limite Superior"] is None
    assert por_codigo["TIP-PH"]["Desvio Padrão"] is None
    assert por_codigo["TIP-PH"]["Variância"] is None
    assert resultado["anomalias"] == []


def test_agrupa_por_estacao_e_parametro():
    linhas = (
        medicoes([1.0] * 5, codigo="TIP-PH", estacao="EST-1")
        + medicoes([2.0] * 6, codigo="TIP-PH", estacao="EST-2")
        + medicoes([3.0] * 7, codigo="TIP-OXI", estacao="EST-1")
    )

    resultado = analisar(linhas)

    grupos = {(e["Estação"], e["Código"]): (e["Quantidade"], e["Média"]) for e in resultado["estatisticas"]}
    assert grupos == {
        ("Estação EST-1", "TIP-OXI"): (7, 3.0),
        ("Estação EST-1", "TIP-PH"): (5, 1.0),
        ("Estação EST-2", "TIP-PH"): (6, 2.0),
    }
    assert resultado["medicoes"] == 18


def test_leituras_contam_registros_distintos():
    linhas = medicoes([1.0, 2.0], codigo="TIP-PH") + medicoes([3.0, 4.0], codigo="TIP-OXI")
    for linha in linhas:
        linha["codigo_registro"] = linha["codigo_registro"].rsplit("-", 1)[-1]

    resultado = analisar(linhas)

    assert (resultado["leituras"], resultado["medicoes"]) == (2, 4)


def test_sem_medicoes():
    assert analisar([]) == {"leituras": 0, "medicoes": 0, "estatisticas": [], "anomalias": []}


class RepositorioFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.filtros = None

    def get_medicoes(self, **filtros):
        self.filtros = filtros
        return self.linhas


def test_calculate_metrics_repassa_os_filtros_e_monta_o_escopo(monkeypatch):
    repositorio = RepositorioFalso(medicoes([1.0, 2.0]))
    service = AnaliticsService(object())
    monkeypatch.setattr(service, "_AnaliticsService__leitura_repository", repositorio)

    resultado = service.calculate_metrics(estacao_id=7, data_inicio=date(2026, 6, 1), data_fim=date(2026, 6, 30))

    assert repositorio.filtros == {
        "estacao_id": 7, "municipio_id": None,
        "data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30),
    }
    assert resultado["escopo"] == {"estacao_id": 7}
    assert resultado["periodo"] == {"data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30)}
    assert resultado["medicoes"] == 2
