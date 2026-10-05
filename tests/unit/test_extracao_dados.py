import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.extracao_dados import Extracao_Dados

DATA_REFERENCIA = "2026-10-05"


def test_inicializacao_diretorios(tmp_path):
    extracao_dados = Extracao_Dados(str(tmp_path / "data_lake"))
    extracao_dados._inicializar_diretorios()

    for camada in ("bronze", "silver"):
        assert (tmp_path / "data_lake" / camada).is_dir()


def test_extrair_dados_bronze_sem_parametro_dados(tmp_path, caplog):
    Extracao_Dados().extrair_dados_bronze(DATA_REFERENCIA, [])
    assert "Não há dados a serem importados." in caplog.messages


def test_extrair_dados_bronze_validos(tmp_path, caplog):
    dados_mock = [
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": True,
        },
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": True,
        },
    ]

    extracao_dados = Extracao_Dados(str(tmp_path / "datalake"))
    extracao_dados._inicializar_diretorios()

    extracao_dados.extrair_dados_bronze(DATA_REFERENCIA, dados_mock)

    log_invalidos_csv = (
        Path(extracao_dados.diretorio_bronze)
        / f"log_cidade_operadora_{DATA_REFERENCIA}.csv"
    )

    dados_validos_json = (
        Path(extracao_dados.diretorio_bronze)
        / f"cidade_operadora_{DATA_REFERENCIA}.json"
    )

    assert not log_invalidos_csv.exists()
    assert dados_validos_json.exists()

    dados_salvos_json = json.loads(dados_validos_json.read_text())

    assert len(dados_salvos_json) == len(dados_mock)


def test_extrair_dados_bronze_invalidos(tmp_path):
    dados_mock = [
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": False,
        },
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": False,
        },
    ]

    extracao_dados = Extracao_Dados(str(tmp_path / "datalake"))
    extracao_dados._inicializar_diretorios()

    extracao_dados.extrair_dados_bronze(DATA_REFERENCIA, dados_mock)

    log_invalidos_csv = (
        Path(extracao_dados.diretorio_bronze)
        / f"log_cidade_operadora_{DATA_REFERENCIA}.csv"
    )

    dados_validos_json = (
        Path(extracao_dados.diretorio_bronze)
        / f"cidade_operadora_{DATA_REFERENCIA}.json"
    )

    assert log_invalidos_csv.exists()
    assert not dados_validos_json.exists()

    log_csv = pd.read_csv(log_invalidos_csv, sep=";")

    assert len(log_csv) == len(dados_mock)


def test_extrair_dados_bronze(tmp_path):
    dados_mock = [
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": True,
        },
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": False,
        },
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": False,
        },
        {
            "condutividade_tipo_codigo": "TIP-CON",
            "is_valid": False,
        },
    ]

    extracao_dados = Extracao_Dados(str(tmp_path / "datalake"))
    extracao_dados._inicializar_diretorios()

    extracao_dados.extrair_dados_bronze(DATA_REFERENCIA, dados_mock)

    log_invalidos_csv = (
        Path(extracao_dados.diretorio_bronze)
        / f"log_cidade_operadora_{DATA_REFERENCIA}.csv"
    )

    dados_validos_json = (
        Path(extracao_dados.diretorio_bronze)
        / f"cidade_operadora_{DATA_REFERENCIA}.json"
    )

    assert log_invalidos_csv.exists()
    assert dados_validos_json.exists()

    log_csv = pd.read_csv(log_invalidos_csv, sep=";")
    dados_salvos_json = json.loads(dados_validos_json.read_text())

    assert len(dados_salvos_json) == len(
        [item for item in dados_mock if item["is_valid"] is True]
    )
    assert len(log_csv) == len(
        [item for item in dados_mock if item["is_valid"] is False]
    )
