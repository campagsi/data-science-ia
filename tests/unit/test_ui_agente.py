"""
Página web do agente (src/ui/agente.py) com o cliente de teste do Flask e o LLM roteirizado.

Cobre os códigos 200, 400, 401, 429 e 503, a conversa de 3 turnos do aceite da
Fase 7 e as políticas da web: POL-07 (limite por IP), POL-09 (HTML seguro e CSP)
e POL-10 (chave de acesso, nada secreto na página).
"""
import logging
import re

import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.fabrica import criar_agente
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.config import ConfigAgente
from src.ui.app import create_app


def montar(roteiro, monkeypatch, **ambiente):
    """Aplicação com um agente offline; ambiente define AGENTE_LIMITE_WEB / AGENTE_CHAVE_WEB."""
    for variavel in ("AGENTE_LIMITE_WEB", "AGENTE_CHAVE_WEB"):
        monkeypatch.delenv(variavel, raising=False)
    for variavel, valor in ambiente.items():
        monkeypatch.setenv(variavel, valor)
    llm = LLMRoteirizado(roteiro)
    aplicacao = create_app(lambda: criar_agente(ConfigAgente("simulado"), llm, consulta_de_exemplo()))
    aplicacao.config.update(TESTING=True)
    return aplicacao.test_client(), llm


def perguntar(cliente, pergunta, conversa_id=None, **cabecalhos):
    """POST /agente/perguntar."""
    return cliente.post("/agente/perguntar", json={"pergunta": pergunta, "conversa_id": conversa_id}, headers=cabecalhos)


def test_pagina_tem_csp_e_nenhum_script_embutido(monkeypatch):
    cliente, _ = montar([], monkeypatch)

    resposta = cliente.get("/agente")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "script-src 'self'" in resposta.headers["Content-Security-Policy"]
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []  # POL-09: só scripts com src
    assert "X-API-Key" not in html  # sem chave configurada, nem o campo aparece


def test_dashboard_tem_link_para_o_agente(monkeypatch):
    from src.ui import app as dashboard_module

    monkeypatch.setattr(dashboard_module, "load_config", lambda: type("C", (), {"azure_sql_connectionstring": "x"})())
    monkeypatch.setattr(dashboard_module.LeituraRepository, "get_medicoes", lambda self: [])
    monkeypatch.setattr(dashboard_module, "_localizacao_das_estacoes", lambda database: {})
    dashboard_module.limpar_cache()
    cliente, _ = montar([], monkeypatch)

    assert 'href="/agente"' in cliente.get("/").get_data(as_text=True)


def test_pergunta_com_ferramenta_devolve_resposta_html_fontes_e_uso(monkeypatch):
    cliente, _ = montar([
        RespostaLLM(chamadas=[ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})], motivo_parada="ferramentas", tokens_entrada=900),
        RespostaLLM(texto="O pH médio foi **7,3** (4 medições).", tokens_entrada=1100, tokens_saida=20),
    ], monkeypatch)

    dados = perguntar(cliente, "Qual o pH médio?").get_json()

    assert dados["resposta_html"] == "<p>O pH médio foi <strong>7,3</strong> (4 medições).</p>\n"
    assert dados["fontes"] == [{"tipo": "ferramenta", "descricao": 'resumo_estatistico(parametros=["TIP-PH"])'}]
    assert dados["uso"] == {"tokens_entrada": 2000, "tokens_saida": 20}
    assert dados["conversa_id"].startswith("c-")


def test_conversa_de_tres_turnos_com_continuacao(monkeypatch):
    """Aceite da Fase 7: "e em julho?" continua a conversa anterior."""
    cliente, llm = montar([RespostaLLM(texto="Em junho, o pH ficou na faixa."), RespostaLLM(texto="Julho: sem dados."), RespostaLLM(texto="Agosto: sem dados.")], monkeypatch)

    primeira = perguntar(cliente, "pH médio em junho?").get_json()
    perguntar(cliente, "E em julho?", primeira["conversa_id"])
    perguntar(cliente, "E em agosto?", primeira["conversa_id"])

    textos = [m.texto for m in llm.chamadas_recebidas[2].mensagens]
    assert textos == ["pH médio em junho?", "Em junho, o pH ficou na faixa.", "E em julho?", "Julho: sem dados.", "E em agosto?"]


@pytest.mark.parametrize(
    "corpo",
    [None, [], {"texto": "x"}, {"pergunta": 7}, {"pergunta": "   "}, {"pergunta": "x" * 1001}, {"pergunta": "pH?", "conversa_id": 5}, {"pergunta": "pH?", "conversa_id": "a b"}],
)
def test_pedido_invalido_responde_400(monkeypatch, corpo):
    cliente, llm = montar([], monkeypatch)

    resposta = cliente.post("/agente/perguntar", json=corpo) if corpo is not None else cliente.post("/agente/perguntar", data="não é json")

    assert resposta.status_code == 400 and resposta.get_json()["erro"]
    assert llm.chamadas_recebidas == []


def test_chave_de_acesso_quando_configurada(monkeypatch):
    cliente, _ = montar([RespostaLLM(texto="Ok.")], monkeypatch, AGENTE_CHAVE_WEB="segredo-web")

    sem_chave = perguntar(cliente, "pH?")
    errada = perguntar(cliente, "pH?", **{"X-API-Key": "outra"})
    certa = perguntar(cliente, "pH?", **{"X-API-Key": "segredo-web"})
    pagina = cliente.get("/agente").get_data(as_text=True)

    assert (sem_chave.status_code, errada.status_code, certa.status_code) == (401, 401, 200)
    assert "segredo-web" not in pagina and "X-API-Key" in pagina  # POL-10: o campo aparece, a chave não


def test_limite_de_perguntas_por_ip(monkeypatch, caplog):
    cliente, _ = montar([RespostaLLM(texto="Ok."), RespostaLLM(texto="Ok.")], monkeypatch, AGENTE_LIMITE_WEB="2 per minute")

    codigos = [perguntar(cliente, "pH?").status_code for _ in range(3)]

    assert codigos == [200, 200, 429]
    assert "guardrail=POL-07 acao=limite_web" in caplog.text


def test_falha_do_provedor_responde_503(monkeypatch):
    cliente, _ = montar([ErroProvedorLLM("APITimeoutError")], monkeypatch)

    resposta = perguntar(cliente, "pH?")

    assert resposta.status_code == 503 and "Não consegui falar com o modelo" in resposta.get_json()["erro"]


def test_agente_sem_configuracao_responde_503_sem_detalhe(monkeypatch, caplog):
    def falhar():
        """Simula o .env sem as variáveis do agente."""
        raise ValueError("A variável ANTHROPIC_API_KEY=sk-ant-xyz deve estar configurada.")

    monkeypatch.delenv("AGENTE_LIMITE_WEB", raising=False)
    aplicacao = create_app(falhar)
    with caplog.at_level(logging.ERROR):
        resposta = aplicacao.test_client().post("/agente/perguntar", json={"pergunta": "pH?"})

    assert resposta.status_code == 503
    assert "erro=ValueError" in caplog.text and "sk-ant-xyz" not in caplog.text + resposta.get_data(as_text=True)


def test_html_do_llm_nunca_vira_script(monkeypatch):
    """POL-09 (risco LLM05): o que o LLM escrever como HTML chega ao navegador como texto."""
    malicioso = 'Veja <script>alert(1)</script> e <img src=x onerror="alert(2)"> e [clique](javascript:alert(3))'
    cliente, _ = montar([RespostaLLM(texto=malicioso)], monkeypatch)

    html = perguntar(cliente, "pH?").get_json()["resposta_html"]

    assert "<script" not in html and "<img" not in html and 'href="javascript:' not in html
    assert "&lt;script&gt;" in html
