import pytest
import requests

import src.ingestion.data_client as data_client
from src.config import Settings


class RespostaFalsa:
    def __init__(self, dados=None, erro_http=None):
        self.__dados = dados
        self.__erro_http = erro_http

    def raise_for_status(self):
        if self.__erro_http:
            raise self.__erro_http

    def json(self):
        return self.__dados


@pytest.fixture
def settings():
    return Settings(mock_api="http://api-de-teste/", azure_sql_connectionstring="x")


def test_fetch_data_consulta_endpoint_da_api(monkeypatch, settings):
    chamadas = []

    def get_falso(url, timeout):
        chamadas.append((url, timeout))
        return RespostaFalsa([{"estacao_codigo": "EST-1"}])

    monkeypatch.setattr(data_client.requests, "get", get_falso)

    dados = data_client.DataClient(settings).fetch_data()

    assert dados == [{"estacao_codigo": "EST-1"}]
    assert chamadas == [("http://api-de-teste/api/v1/data-set", 30)]


@pytest.mark.parametrize("resposta", [{"registros": []}, "texto", None])
def test_fetch_data_rejeita_resposta_que_nao_e_lista(monkeypatch, settings, resposta):
    monkeypatch.setattr(data_client.requests, "get", lambda *a, **k: RespostaFalsa(resposta))

    with pytest.raises(ValueError, match="lista"):
        data_client.DataClient(settings).fetch_data()


def test_fetch_data_rejeita_registro_que_nao_e_objeto(monkeypatch, settings):
    monkeypatch.setattr(data_client.requests, "get", lambda *a, **k: RespostaFalsa([{}, "x"]))

    with pytest.raises(ValueError, match="objetos JSON"):
        data_client.DataClient(settings).fetch_data()


def test_fetch_data_propaga_erro_http(monkeypatch, settings):
    erro = requests.HTTPError("500 Server Error")
    monkeypatch.setattr(data_client.requests, "get", lambda *a, **k: RespostaFalsa(erro_http=erro))

    with pytest.raises(requests.HTTPError):
        data_client.DataClient(settings).fetch_data()
