"""Leitura do dataset da API em JSON puro e compactado em gzip."""
import gzip
import json

import pytest

from src.api.dataset_repository import DatasetRepository

REGISTROS = [{"id": 1, "cidade_estado": "SP"}, {"id": 2, "cidade_estado": "RJ"}]


def test_le_dataset_compactado_em_gzip(tmp_path):
    caminho = tmp_path / "data_set.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(REGISTROS, arquivo)

    assert DatasetRepository(caminho).get_all() == REGISTROS


def test_le_dataset_em_json_puro(tmp_path):
    caminho = tmp_path / "data_set.json"
    caminho.write_text(json.dumps(REGISTROS), encoding="utf-8")

    assert DatasetRepository(caminho).get_all() == REGISTROS


def test_dataset_padrao_e_o_arquivo_compactado_do_modulo():
    dataset = DatasetRepository().get_all()

    assert isinstance(dataset, list)
    assert dataset


def test_arquivo_inexistente_gera_runtime_error(tmp_path):
    with pytest.raises(RuntimeError, match="nao foi encontrado"):
        DatasetRepository(tmp_path / "ausente.json.gz").get_all()


def test_gzip_corrompido_gera_runtime_error(tmp_path):
    caminho = tmp_path / "data_set.json.gz"
    caminho.write_bytes(b"isto nao e gzip")

    with pytest.raises(RuntimeError, match="gzip invalido"):
        DatasetRepository(caminho).get_all()


def test_json_invalido_dentro_do_gzip_gera_runtime_error(tmp_path):
    caminho = tmp_path / "data_set.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        arquivo.write("{nao e json")

    with pytest.raises(RuntimeError, match="JSON invalido"):
        DatasetRepository(caminho).get_all()


def test_json_que_nao_e_lista_gera_runtime_error(tmp_path):
    caminho = tmp_path / "data_set.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump({"id": 1}, arquivo)

    with pytest.raises(RuntimeError, match="lista de registros"):
        DatasetRepository(caminho).get_all()
