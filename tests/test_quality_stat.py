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
