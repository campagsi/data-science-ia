"""Testes do teste da API do BI feito pelo dashboard (src/ui/api_bi.py)."""
import pytest
import requests

from src.ui import api_bi


class _Resposta:
    def __init__(self, status=200, corpo=None, url="", reason="OK", json_invalido=False):
        self.status_code = status
        self._corpo = corpo
        self.url = url
        self.reason = reason
        self._json_invalido = json_invalido

    def json(self):
        if self._json_invalido:
            raise ValueError("sem JSON")
        return self._corpo


class _Get:
    """Substitui requests.get e guarda as chamadas recebidas."""

    def __init__(self, resposta=None, erro=None):
        self.resposta = resposta or _Resposta(corpo=[])
        self.erro = erro
        self.chamadas = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if self.erro:
            raise self.erro
        return self.resposta


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("FONTE_DADOS", "http://api-bi:8000/")
    monkeypatch.delenv("CHAVE_API_BI", raising=False)


def test_url_base_usa_fonte_dados_sem_barra_final():
    assert api_bi.url_base() == "http://api-bi:8000"


def test_url_base_padrao_local(monkeypatch):
    monkeypatch.delenv("FONTE_DADOS")
    assert api_bi.url_base() == "http://127.0.0.1:8000"


def test_rota_desconhecida_e_recusada():
    with pytest.raises(ValueError, match="Rota desconhecida"):
        api_bi.consultar("../data-set", {}, _Get())


def test_dimensao_resume_linhas_colunas_e_amostra():
    linhas = [{"estacao_sk": i, "nome": f"E{i}"} for i in range(1, 31)]
    get = _Get(_Resposta(corpo=linhas, url="http://api-bi:8000/api/v1/bi/estacoes"))

    resultado = api_bi.consultar("estacoes", {"inicio": "2026-01-01"}, get)

    assert get.chamadas[0]["url"] == "http://api-bi:8000/api/v1/bi/estacoes"
    assert get.chamadas[0]["params"] == {}  # dimensões ignoram filtros
    assert resultado["ok"] and resultado["status"] == 200
    assert (resultado["total"], resultado["linhas"]) == (30, 30)
    assert resultado["colunas"] == ["estacao_sk", "nome"]
    assert len(resultado["amostra"]) == api_bi.LINHAS_AMOSTRA


def test_medicoes_repassa_filtros_e_paginacao_e_le_o_envelope():
    corpo = {"pagina": 2, "por_pagina": 1, "total": 5, "total_paginas": 5, "tem_proxima": True,
             "dados": [{"registro_codigo": "R2", "valor_lido": 1.5}]}
    get = _Get(_Resposta(corpo=corpo))
    args = {"inicio": "2026-06-01", "fim": "", "estacao_sk": "3", "pagina": "2", "por_pagina": "1",
            "apenas_outliers": "true", "rota": "medicoes"}

    resultado = api_bi.consultar("medicoes", args, get)

    assert get.chamadas[0]["params"] == {"inicio": "2026-06-01", "estacao_sk": "3",
                                         "apenas_outliers": "true", "pagina": "2", "por_pagina": "1"}
    assert resultado["total"] == 5 and resultado["linhas"] == 1
    assert resultado["paginacao"]["total_paginas"] == 5


def test_medicoes_diarias_nao_repassa_paginacao():
    get = _Get()
    api_bi.consultar("medicoes/diarias", {"parametro_sk": "2", "pagina": "3"}, get)
    assert get.chamadas[0]["params"] == {"parametro_sk": "2"}


def test_chave_configurada_vai_no_header(monkeypatch):
    monkeypatch.setenv("CHAVE_API_BI", "segredo")
    get = _Get()

    resultado = api_bi.consultar("tempo", {}, get)

    assert get.chamadas[0]["headers"] == {"X-API-Key": "segredo"}
    assert "segredo" not in str(resultado)
    assert api_bi.chave_configurada()


def test_sem_chave_nao_envia_header():
    get = _Get()
    api_bi.consultar("tempo", {}, get)
    assert get.chamadas[0]["headers"] == {}


def test_api_fora_do_ar_orienta_como_iniciar():
    resultado = api_bi.consultar("estacoes", {}, _Get(erro=requests.ConnectionError("recusada")))

    assert resultado["ok"] is False and resultado["status"] is None
    assert "http://api-bi:8000" in resultado["mensagem"]
    assert "uvicorn" in resultado["mensagem"]


@pytest.mark.parametrize(
    "resposta, mensagem",
    [
        (_Resposta(503, {"detail": "Camada Gold não encontrada"}), "Camada Gold não encontrada"),
        (_Resposta(401, {"detail": "Chave de API inválida ou ausente."}), "Chave de API inválida"),
        (_Resposta(422, {"detail": [{"loc": ["query", "inicio"], "msg": "Input should be a valid date"}]}),
         "inicio: Input should be a valid date"),
        (_Resposta(500, reason="Internal Server Error", json_invalido=True), "Internal Server Error"),
    ],
)
def test_erros_da_api_trazem_o_detalhe(resposta, mensagem):
    resultado = api_bi.consultar("medicoes", {}, _Get(resposta))
    assert resultado["ok"] is False
    assert resultado["status"] == resposta.status_code
    assert mensagem in resultado["mensagem"]


def test_resposta_200_sem_json_e_falha():
    resultado = api_bi.consultar("estacoes", {}, _Get(_Resposta(json_invalido=True)))
    assert resultado["ok"] is False and "JSON" in resultado["mensagem"]


def test_verificar_todas_chama_cada_rota_sem_amostra():
    get = _Get(_Resposta(corpo=[{"a": 1}]))

    resultados = api_bi.verificar_todas(get)

    assert [r["rota"] for r in resultados] == list(api_bi.ROTAS_BI)
    assert all(r["ok"] and "amostra" not in r for r in resultados)
    medicoes = next(c for c in get.chamadas if c["url"].endswith("/medicoes"))
    assert medicoes["params"] == {"por_pagina": "1"}


class _GetPorUrl(_Get):
    """Responde conforme o final da URL; /health separado das rotas do BI."""

    def __init__(self, health, rotas):
        super().__init__()
        self.health, self.rotas = health, rotas

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.chamadas.append({"url": url, "params": params})
        if url.endswith("/health"):
            if isinstance(self.health, Exception):
                raise self.health
            return self.health
        return self.rotas(url)


def test_status_api_fora_do_ar_nao_chama_as_rotas():
    get = _GetPorUrl(requests.ConnectionError("recusada"), lambda url: pytest.fail("chamou rota"))

    situacao = api_bi.status(get)

    assert situacao["api"]["online"] is False and "uvicorn" in situacao["api"]["mensagem"]
    assert situacao["rotas"] == [] and situacao["gold_disponivel"] is False
    assert len(get.chamadas) == 1


def test_status_gold_vazia_traz_a_mensagem_da_api():
    get = _GetPorUrl(_Resposta(corpo={"status": "ok"}),
                     lambda url: _Resposta(503, {"detail": "Camada Gold não encontrada"}))

    situacao = api_bi.status(get)

    assert situacao["api"]["online"] is True
    assert situacao["rotas_ok"] == 0 and situacao["gold_disponivel"] is False
    assert "Camada Gold não encontrada" in situacao["gold_mensagem"]
    assert situacao["total_medicoes"] is None


def test_status_gold_disponivel_informa_total_de_medicoes():
    def rotas(url):
        if url.endswith("/medicoes"):
            return _Resposta(corpo={"total": 104582, "pagina": 1, "total_paginas": 104582, "dados": [{"a": 1}]})
        return _Resposta(corpo=[{"a": 1}])

    situacao = api_bi.status(_GetPorUrl(_Resposta(corpo={"status": "ok"}), rotas))

    assert situacao["gold_disponivel"] is True and situacao["gold_mensagem"] is None
    assert situacao["rotas_ok"] == len(api_bi.ROTAS_BI)
    assert situacao["total_medicoes"] == 104582
