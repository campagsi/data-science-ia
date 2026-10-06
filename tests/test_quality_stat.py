"""
Qualidade dos dados com o dataset completo da API (aceite das fases 5 e 6).

As faixas vêm do sql/dml_populacao.sql, as mesmas gravadas em Parametros.
Os números esperados foram conferidos com um cálculo independente feito
direto sobre o JSON bruto, sem usar o ValidationService.
"""
import re
from collections import Counter
from pathlib import Path

import pytest

import src.logger as log
from src.services.normalization_service import NormalizationService
from src.services.validation_service import ValidationService

RAIZ = Path(__file__).resolve().parents[1]


def _faixas_do_dml() -> dict:
    dml = (RAIZ / "sql" / "dml_populacao.sql").read_text(encoding="utf-8-sig")
    limite = lambda texto: None if texto == "NULL" else float(texto)
    return {
        codigo: (limite(minimo), limite(maximo))
        for codigo, minimo, maximo in re.findall(
            r"\('(TIP-[A-Z]+)',\s*N'[^']+',\s*N'[^']+',\s*(-?\d+|NULL),\s*(-?\d+|NULL)\)", dml
        )
    }


@pytest.fixture(scope="module")
def resultados(dataset):
    import logging

    from src.security import configurar_seguranca
    import os

    configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], os.environ["PEPPER_HASH"])
    logging.disable(logging.CRITICAL)
    try:
        normalizados = NormalizationService().normalize(dataset)
    finally:
        logging.disable(logging.NOTSET)
    return ValidationService(faixas=_faixas_do_dml(), siglas_estados={"RJ"}).validate_data(normalizados)


def _validos(resultados):
    return [r for r in resultados if r["valido"]]


def test_todo_registro_recebido_tem_um_resultado(resultados, dataset):
    assert len(resultados) == len(dataset) == 9888


def test_completude_82_leituras_rejeitadas_por_estacao_ou_operador_nulo(resultados):
    invalidos = [r for r in resultados if not r["valido"]]
    sem_estacao = [r for r in invalidos if "estacao_codigo" in r["campos_nulos"]]
    so_sem_operador = [
        r for r in invalidos
        if "estacao_codigo" not in r["campos_nulos"] and "operador_codigo" in r["campos_nulos"]
    ]

    assert len(invalidos) == 82
    assert len(sem_estacao) == 50
    assert len(so_sem_operador) == 32
    assert all(r["motivos"][0]["etapa"] == "completude" for r in invalidos)


def test_completude_medicoes_nulas_dos_registros_validos(resultados):
    nulos = [i for r in _validos(resultados) for i in r["itens_invalidos"] if i["etapa"] == "completude"]

    assert len(nulos) == 2681


def test_acuracia_valores_fora_da_faixa_descartados_so_como_item(resultados):
    fora = Counter(
        i["campo"] for r in _validos(resultados) for i in r["itens_invalidos"] if i["etapa"] == "acuracia"
    )

    assert sum(fora.values()) == 603
    assert fora["ph"] == 72
    assert fora["umidade"] == 69


def test_nenhum_item_gravavel_fica_fora_da_faixa(resultados):
    faixas = _faixas_do_dml()
    for registro in ValidationService.registros_validos(resultados):
        for item in registro["itens"]:
            minimo, maximo = faixas[item["codigo_parametro"]]
            assert item["valor"] is not None
            assert minimo is None or item["valor"] >= minimo
            assert maximo is None or item["valor"] <= maximo


def test_log_de_rejeitados_tem_tudo_o_que_nao_foi_importado(resultados, logs_temporarios, dataset):
    contagens = log.registrar_resultados_validacao(resultados)
    linhas = logs_temporarios("rejeitados")

    assert contagens["registros_validos"] + contagens["registros_invalidos"] == 9888
    assert len(linhas) == 82 + 2681 + 603
    texto = "\n".join(linhas)
    for registro in dataset[:50]:
        for campo in ("operador_cpf", "operador_email"):
            if registro[campo]:
                assert registro[campo] not in texto


# --- Estatística e outliers (aceite da fase 14) ---


@pytest.fixture(scope="module")
def analise(resultados):
    """Análise dos itens válidos, no formato de LeituraRepository.get_medicoes()."""
    from src.services.analytics_service import AnaliticsService

    medicoes = [
        {
            "estacao_id": 1,
            "estacao_codigo": r["registro"]["estacao_codigo"],
            "estacao": r["registro"]["estacao_nome"],
            "codigo_registro": r["registro_codigo"],
            "data_hora": r["registro"]["data_hora_ciclo"],
            "codigo_parametro": item["codigo_parametro"],
            "parametro": item["campo"],
            "unidade_medida": item["unidade_medida"],
            "valor": item["valor"],
        }
        for r in _validos(resultados)
        for item in r["registro"]["itens"]
    ]
    return AnaliticsService.analisar_medicoes(medicoes)


def test_analise_cobre_as_leituras_e_os_11_parametros(analise):
    assert (analise["leituras"], analise["medicoes"]) == (9806, 104582)
    assert len(analise["estatisticas"]) == 11
    for estatistica in analise["estatisticas"]:
        assert estatistica["Variância"] == pytest.approx(estatistica["Desvio Padrão"] ** 2)
        assert estatistica["IQR"] == pytest.approx(estatistica["Q3"] - estatistica["Q1"])


def test_anomalias_por_iqr_e_zscore_com_o_dataset_atual(analise):
    por_alerta = Counter(a["Alerta"] for a in analise["anomalias"])
    por_parametro = {e["Código"]: e["Anomalias"] for e in analise["estatisticas"]}

    assert por_alerta == {"IQR": 1528, "IQR+ZSCORE": 296}
    assert por_parametro == {
        "TIP-CHU": 1210, "TIP-CON": 101, "TIP-OXI": 76, "TIP-PH": 73, "TIP-PRE": 75, "TIP-RAD": 0,
        "TIP-TAG": 47, "TIP-TMP": 71, "TIP-TUR": 92, "TIP-UMI": 53, "TIP-VEN": 26,
    }


def test_toda_anomalia_esta_fora_do_iqr_ou_acima_de_3_desvios(analise):
    for a in analise["anomalias"]:
        fora_iqr = a["Valor"] < a["Limite Inferior"] or a["Valor"] > a["Limite Superior"]
        fora_z = abs(a["Z-Score"]) > 3
        assert (fora_iqr, fora_z) == {"IQR": (True, False), "ZSCORE": (False, True), "IQR+ZSCORE": (True, True)}[a["Alerta"]]


def test_precipitacao_com_iqr_zero_sinaliza_toda_chuva(analise):
    """Limitação conhecida da regra IQR em dados com muitos zeros (docs/analise-estatistica.md)."""
    (chuva,) = [e for e in analise["estatisticas"] if e["Código"] == "TIP-CHU"]

    assert chuva["IQR"] == 0
    assert all(a["Valor"] > 0 for a in analise["anomalias"] if a["Parâmetro"] == "precipitacao")
