"""Coleta resiliente da API (item 3.1 do enunciado, fase 18)."""
import json

import pytest
import requests

import src.ingestion.data_client as data_client
from src.config import Settings

URL = "http://api-de-teste/api/v1/data-set"


class RespostaFalsa:
    def __init__(self, dados=None, status=200, corpo=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = corpo if corpo is not None else json.dumps(dados).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")

    def json(self):
        return json.loads(self.content)


class Ambiente:
    """requests.get com respostas em sequência e relógio simulado (sem esperar de verdade)."""

    def __init__(self, monkeypatch, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.esperas = []
        self.agora = 0.0
        monkeypatch.setattr(data_client.requests, "get", self.get)

    def get(self, url, timeout):
        self.chamadas.append((url, timeout, self.agora))
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.agora += segundos

    def cliente(self, **kwargs):
        settings = Settings(fonte_dados="http://api-de-teste/", azure_sql_connectionstring="x")
        return data_client.DataClient(settings, dormir=self.dormir, relogio=lambda: self.agora, **kwargs)


def test_consulta_o_endpoint_da_api(monkeypatch):
    ambiente = Ambiente(monkeypatch, RespostaFalsa([{"estacao_codigo": "EST-1"}]))

    assert ambiente.cliente().fetch_data() == [{"estacao_codigo": "EST-1"}]
    assert ambiente.chamadas == [(URL, data_client.TIMEOUT, 0.0)]
    assert ambiente.esperas == []


@pytest.mark.parametrize(
    "falha",
    [
        requests.ConnectionError("conexão recusada"),
        requests.Timeout("tempo esgotado"),
        RespostaFalsa(status=503),
        RespostaFalsa(status=500),
    ],
)
def test_falha_transitoria_tenta_de_novo_com_espera_crescente(monkeypatch, falha, logs_temporarios):
    ambiente = Ambiente(monkeypatch, falha, falha, RespostaFalsa([{"a": 1}]))

    dados = ambiente.cliente(espera_inicial=1, requisicoes_por_minuto=600).fetch_data()

    assert dados == [{"a": 1}]
    assert len(ambiente.chamadas) == 3
    assert ambiente.esperas == [1, 2]
    avisos = [linha for linha in logs_temporarios("pipeline") if "[WARNING]" in linha]
    assert len(avisos) == 2 and "tentativa 1 de 4" in avisos[0]


def test_esgotadas_as_tentativas_falha_com_erro_de_fonte(monkeypatch, logs_temporarios):
    erro = requests.ConnectionError("conexão recusada")
    ambiente = Ambiente(monkeypatch, erro, erro, erro)

    with pytest.raises(data_client.FonteIndisponivelError, match="3 tentativas"):
        ambiente.cliente(tentativas=3, requisicoes_por_minuto=600).fetch_data()

    assert len(ambiente.chamadas) == 3
    assert any("[ERROR]" in linha and "API indisponível" in linha for linha in logs_temporarios("pipeline"))


def test_http_429_respeita_o_retry_after(monkeypatch):
    ambiente = Ambiente(
        monkeypatch, RespostaFalsa(status=429, headers={"Retry-After": "7"}), RespostaFalsa([{"a": 1}])
    )

    ambiente.cliente(espera_inicial=1, requisicoes_por_minuto=600).fetch_data()

    assert ambiente.esperas == [7]


def test_limite_de_requisicoes_por_minuto_espaca_as_tentativas(monkeypatch):
    erro = RespostaFalsa(status=503)
    ambiente = Ambiente(monkeypatch, erro, erro, RespostaFalsa([{"a": 1}]))

    # 6 por minuto = uma a cada 10 s; a espera do backoff (1 s, 2 s) é menor.
    ambiente.cliente(espera_inicial=1, requisicoes_por_minuto=6).fetch_data()

    instantes = [instante for *_, instante in ambiente.chamadas]
    assert instantes == [0, 10, 20]


@pytest.mark.parametrize("status", [400, 404])
def test_erro_do_cliente_nao_tenta_de_novo(monkeypatch, status):
    ambiente = Ambiente(monkeypatch, RespostaFalsa(status=status))

    with pytest.raises(requests.HTTPError):
        ambiente.cliente().fetch_data()

    assert len(ambiente.chamadas) == 1


@pytest.mark.parametrize("resposta", [RespostaFalsa([]), RespostaFalsa(corpo=b""), RespostaFalsa(corpo=b"  ")])
def test_resposta_vazia_devolve_lote_vazio_com_warning(monkeypatch, resposta, logs_temporarios):
    ambiente = Ambiente(monkeypatch, resposta)

    assert ambiente.cliente().fetch_data() == []
    assert any("[WARNING]" in linha and "lote vazio" in linha for linha in logs_temporarios("pipeline"))


@pytest.mark.parametrize("resposta", [{"registros": []}, "texto", None])
def test_rejeita_resposta_que_nao_e_lista(monkeypatch, resposta):
    ambiente = Ambiente(monkeypatch, RespostaFalsa(resposta))

    with pytest.raises(ValueError, match="lista"):
        ambiente.cliente().fetch_data()


def test_rejeita_json_invalido(monkeypatch):
    ambiente = Ambiente(monkeypatch, RespostaFalsa(corpo=b"<html>erro</html>"))

    with pytest.raises(ValueError, match="JSON válido"):
        ambiente.cliente().fetch_data()


def test_rejeita_registro_que_nao_e_objeto(monkeypatch):
    ambiente = Ambiente(monkeypatch, RespostaFalsa([{}, "x"]))

    with pytest.raises(ValueError, match="objetos JSON"):
        ambiente.cliente().fetch_data()
