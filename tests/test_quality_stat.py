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

    configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], os.environ["CHAVE_HASH"])
    logging.disable(logging.CRITICAL)
    try:
        normalizados = NormalizationService().normalize(dataset)
    finally:
        logging.disable(logging.NOTSET)
    siglas = {registro["cidade_estado"] for registro in dataset if registro.get("cidade_estado")}
    return ValidationService(faixas=_faixas_do_dml(), siglas_estados=siglas).validate_data(normalizados)


def _validos(resultados):
    return [r for r in resultados if r["valido"]]


def test_todo_registro_recebido_tem_um_resultado(resultados, dataset):
    assert len(resultados) == len(dataset)


def test_dataset_tem_cobertura_geografica_operadores_cadencia_e_outliers(dataset):
    faixas = _faixas_do_dml()
    estacoes = {}
    cidades_por_estado = {}
    estacoes_por_operador = {}
    outliers = 0

    for registro in dataset:
        estacao = registro.get("estacao_codigo")
        operador = registro.get("operador_codigo")
        if estacao:
            estacoes.setdefault(estacao, []).append(registro)
            cidades_por_estado.setdefault(registro["cidade_estado"], set()).add(registro["cidade_nome"])
        if operador:
            estacoes_por_operador.setdefault(operador, set()).add(estacao)

        if any(
            isinstance(registro.get(campo := tipo[:-len("_tipo_codigo")]), (int, float))
            and (
                (faixas[codigo][0] is not None and registro[campo] < faixas[codigo][0])
                or (faixas[codigo][1] is not None and registro[campo] > faixas[codigo][1])
            )
            for tipo, codigo in registro.items()
            if tipo.endswith("_tipo_codigo") and codigo in faixas
        ):
            outliers += 1

    assert len(estacoes) == 6
    assert {"BA", "RJ", "SP"} <= cidades_por_estado.keys()
    assert all(len(cidades) >= 2 for cidades in cidades_por_estado.values())
    assert all(len({registro["operador_codigo"] for registro in registros if registro.get("operador_codigo")}) in {2, 4}
               for registros in estacoes.values())
    assert all(len(estacoes_do_operador) == 1 for estacoes_do_operador in estacoes_por_operador.values())
    assert all(
        len(registros) == 9888
        and all(
            count == 2
            for count in Counter(registro["data_hora_ciclo"][:13] for registro in registros).values()
        )
        for registros in estacoes.values()
    )
    assert outliers == round(len(dataset) * 0.10)


def test_leituras_rejeitadas_por_estacao_ou_operador_nulo(resultados, dataset):
    invalidos = [r for r in resultados if not r["valido"]]
    sem_estacao = [r for r in invalidos if "estacao_codigo" in r["campos_nulos"]]
    so_sem_operador = [
        r for r in invalidos
        if "estacao_codigo" not in r["campos_nulos"] and "operador_codigo" in r["campos_nulos"]
    ]

    assert len(invalidos) == sum(not r.get("estacao_codigo") or not r.get("operador_codigo") for r in dataset)
    assert len(sem_estacao) == sum(not r.get("estacao_codigo") for r in dataset)
    assert len(so_sem_operador) == sum(bool(r.get("estacao_codigo")) and not r.get("operador_codigo") for r in dataset)
    assert all(r["motivos"][0]["etapa"] == "completude" for r in invalidos)


def test_completude_medicoes_nulas_dos_registros_validos(resultados, dataset):
    nulos = [i for r in _validos(resultados) for i in r["itens_invalidos"] if i["etapa"] == "completude"]
    codigos_validos = {r["registro_codigo"] for r in _validos(resultados)}

    campos_medicao = [
        tipo[:-len("_tipo_codigo")]
        for tipo in dataset[0]
        if tipo.endswith("_tipo_codigo")
    ]
    esperados = sum(
        registro.get(campo) is None
        for registro in dataset
        if registro["registro_codigo"] in codigos_validos
        for campo in campos_medicao
    )
    assert len(nulos) == esperados


def test_acuracia_valores_fora_da_faixa_descartados_so_como_item(resultados, dataset):
    fora = Counter(
        i["campo"] for r in _validos(resultados) for i in r["itens_invalidos"] if i["etapa"] == "acuracia"
    )
    faixas = _faixas_do_dml()
    esperados = Counter()
    codigos_validos = {r["registro_codigo"] for r in _validos(resultados)}
    for registro in dataset:
        if registro["registro_codigo"] not in codigos_validos:
            continue
        for tipo, codigo in registro.items():
            if not tipo.endswith("_tipo_codigo") or codigo not in faixas:
                continue
            campo = tipo[:-len("_tipo_codigo")]
            valor = registro.get(campo)
            minimo, maximo = faixas[codigo]
            if isinstance(valor, (int, float)) and (
                (minimo is not None and valor < minimo) or (maximo is not None and valor > maximo)
            ):
                esperados[campo] += 1

    assert fora == esperados


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
    invalidos = [r for r in resultados if not r["valido"]]
    nulos = sum(i["etapa"] == "completude" for r in _validos(resultados) for i in r["itens_invalidos"])
    fora = sum(i["etapa"] == "acuracia" for r in _validos(resultados) for i in r["itens_invalidos"])

    assert contagens["registros_validos"] + contagens["registros_invalidos"] == len(dataset)
    assert len(linhas) == len(invalidos) + nulos + fora
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


def test_analise_cobre_as_leituras_e_os_11_parametros(analise, resultados):
    validos = _validos(resultados)
    assert analise["leituras"] == len(validos)
    assert analise["medicoes"] == sum(len(r["registro"]["itens"]) for r in validos)
    estacoes = {r["registro"]["estacao_codigo"] for r in validos}
    assert len(analise["estatisticas"]) == len(estacoes) * 11
    for estatistica in analise["estatisticas"]:
        assert estatistica["Variância"] == pytest.approx(estatistica["Desvio Padrão"] ** 2)
        assert estatistica["IQR"] == pytest.approx(estatistica["Q3"] - estatistica["Q1"])


def test_anomalias_por_iqr_e_zscore_com_o_dataset_atual(analise):
    por_alerta = Counter(a["Alerta"] for a in analise["anomalias"])
    assert sum(por_alerta.values()) == len(analise["anomalias"])
    assert set(por_alerta) <= {"IQR", "ZSCORE", "IQR+ZSCORE"}
    assert sum(e["Anomalias"] for e in analise["estatisticas"]) == len(analise["anomalias"])


def test_toda_anomalia_esta_fora_do_iqr_ou_acima_de_3_desvios(analise):
    for a in analise["anomalias"]:
        fora_iqr = a["Valor"] < a["Limite Inferior"] or a["Valor"] > a["Limite Superior"]
        fora_z = abs(a["Z-Score"]) > 3
        assert (fora_iqr, fora_z) == {"IQR": (True, False), "ZSCORE": (False, True), "IQR+ZSCORE": (True, True)}[a["Alerta"]]


def test_precipitacao_com_iqr_zero_sinaliza_toda_chuva(analise):
    """Limitação conhecida da regra IQR em dados com muitos zeros (docs/analise-estatistica.md)."""
    chuvas = [e for e in analise["estatisticas"] if e["Código"] == "TIP-CHU"]

    assert len(chuvas) == 6
    assert all(chuva["IQR"] == 0 for chuva in chuvas)
    assert all(a["Valor"] > 0 for a in analise["anomalias"] if a["Parâmetro"] == "precipitacao")
