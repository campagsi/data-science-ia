"""Testes das rotas web do dashboard Flask."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.ui import app as dashboard_module


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        dashboard_module,
        "load_config",
        lambda: SimpleNamespace(azure_sql_connectionstring="Server=local"),
    )
    monkeypatch.setattr(
        dashboard_module.LeituraRepository,
        "get_medicoes",
        lambda self: [],
    )
    # Cidade e estado das estações: cobertos em test_ui_dashboard.py; aqui, sem banco.
    monkeypatch.setattr(dashboard_module, "_localizacao_das_estacoes", lambda database: {})
    dashboard_module.limpar_cache()
    dashboard_module.app.config.update(TESTING=True)
    yield dashboard_module.app.test_client()
    dashboard_module.limpar_cache()


def _medicao(registro, data_hora, valor, estacao_id=8, codigo="TIP-PH", parametro="pH", unidade="pH"):
    return {
        "estacao_id": estacao_id,
        "estacao_codigo": f"EST-{estacao_id}",
        "estacao": "Estação de teste",
        "codigo_registro": registro,
        "data_hora": data_hora,
        "codigo_parametro": codigo,
        "parametro": parametro,
        "unidade_medida": unidade,
        "valor": valor,
    }


def _usar_medicoes(monkeypatch, medicoes):
    monkeypatch.setattr(dashboard_module.LeituraRepository, "get_medicoes", lambda self: medicoes)


def test_dashboard_renderiza_estado_vazio(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Ainda não há medições" in response.get_data(as_text=True)


def test_dashboard_aplica_filtros_e_calcula_metricas(client, monkeypatch):
    medicoes = [
        {
            "estacao_id": 8,
            "estacao_codigo": "EST-SP-001",
            "estacao": "Estação de teste",
            "codigo_registro": "R-1",
            "data_hora": datetime(2026, 6, 12, 10),
            "codigo_parametro": "TIP-PH",
            "parametro": "pH",
            "unidade_medida": "pH",
            "valor": 7.2,
        },
        {
            "estacao_id": 9,
            "estacao_codigo": "EST-RJ-001",
            "estacao": "Outra estação",
            "codigo_registro": "R-2",
            "data_hora": datetime(2026, 6, 12, 11),
            "codigo_parametro": "TIP-PH",
            "parametro": "pH",
            "unidade_medida": "pH",
            "valor": 8.1,
        },
    ]
    _usar_medicoes(monkeypatch, medicoes)

    response = client.get("/?estacao=8&parametro=TIP-PH&inicio=2026-06-12&fim=2026-06-12")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "R-1" in body
    assert "R-2" not in body
    assert "7,200" in body
    assert "12/06/2026 10:00" in body


def test_dashboard_pagina_a_tabela_de_medicoes(client, monkeypatch):
    medicoes = [_medicao(f"R-{hora:02d}", datetime(2026, 6, 12, hora), 7.0) for hora in range(24)]
    _usar_medicoes(monkeypatch, medicoes)

    primeira = client.get("/?por_pagina=10").get_data(as_text=True)
    terceira = client.get("/?por_pagina=10&pagina=3").get_data(as_text=True)

    # Mais recentes primeiro: a primeira página vai de R-23 a R-14.
    assert "R-23" in primeira and "R-14" in primeira
    assert "R-13" not in primeira
    assert "1–10 de 24" in primeira
    assert 'aria-current="page">1<' in primeira
    assert "R-03" in terceira and "R-00" in terceira
    assert "R-04" not in terceira
    assert "21–24 de 24" in terceira


def test_dashboard_pagina_fora_do_intervalo_vai_para_a_ultima(client, monkeypatch):
    _usar_medicoes(monkeypatch, [_medicao(f"R-{i}", datetime(2026, 6, 12, i), 7.0) for i in range(12)])

    body = client.get("/?por_pagina=10&pagina=99").get_data(as_text=True)

    assert "11–12 de 12" in body


def test_dashboard_nao_embute_todas_as_medicoes_no_html(client, monkeypatch):
    _usar_medicoes(monkeypatch, [
        _medicao(f"R-{i:03d}", datetime(2026, 6, 12, i % 24, i % 60), 7.0) for i in range(300)
    ])

    body = client.get("/").get_data(as_text=True)

    assert body.count("<td>R-") == 25
    assert "data-period-chart" in body
    assert "/api/serie" in body


def test_api_serie_agrega_por_hora_e_respeita_filtros(client, monkeypatch):
    _usar_medicoes(monkeypatch, [
        _medicao("R-1", datetime(2026, 6, 12, 10, 0), 6.0),
        _medicao("R-2", datetime(2026, 6, 12, 10, 30), 8.0),
        _medicao("R-3", datetime(2026, 6, 12, 11, 0), 7.0),
        _medicao("R-4", datetime(2026, 6, 12, 11, 0), 30.0, codigo="TIP-TMP", parametro="Temperatura", unidade="°C"),
        _medicao("R-5", datetime(2026, 6, 13, 9, 0), 9.0),
    ])

    resposta = client.get("/api/serie?codigo=TIP-PH&inicio=2026-06-12&fim=2026-06-12")

    assert resposta.status_code == 200
    assert resposta.json["unidade"] == "pH"
    assert resposta.json["pontos"] == [
        ["2026-06-12T10:00", 2, 14.0, 6.0, 8.0],
        ["2026-06-12T11:00", 1, 7.0, 7.0, 7.0],
    ]


def test_api_serie_exige_parametro(client):
    resposta = client.get("/api/serie")

    assert resposta.status_code == 400
    assert resposta.json["ok"] is False


def test_api_serie_inclui_anomalias_do_parametro(client, monkeypatch):
    valores = [7.0, 7.1, 6.9, 7.0, 7.2, 6.8, 7.1, 7.0, 6.9, 7.0, 25.0]
    _usar_medicoes(monkeypatch, [
        _medicao(f"R-{i}", datetime(2026, 6, 12, i), valor) for i, valor in enumerate(valores)
    ])

    anomalias = client.get("/api/serie?codigo=TIP-PH").json["anomalias"]

    assert anomalias == [["2026-06-12T10:00", 25.0, "IQR+ZSCORE"]]


def test_api_serie_informa_falha_do_banco(client, monkeypatch):
    def falhar(self):
        raise RuntimeError("sem banco")

    monkeypatch.setattr(dashboard_module.LeituraRepository, "get_medicoes", falhar)

    resposta = client.get("/api/serie?codigo=TIP-PH")

    assert resposta.status_code == 503
    assert "sem banco" not in resposta.get_data(as_text=True)


def test_exportar_csv_traz_todo_o_recorte(client, monkeypatch):
    _usar_medicoes(monkeypatch, [
        _medicao(f"R-{i:02d}", datetime(2026, 6, 12, i), 7.25) for i in range(24)
    ] + [_medicao("R-OUTRA", datetime(2026, 6, 12, 1), 1.0, estacao_id=9)])

    resposta = client.get("/exportar.csv?estacao=8")
    texto = resposta.get_data(as_text=True)
    linhas = texto.lstrip("﻿").splitlines()

    assert resposta.status_code == 200
    assert "attachment" in resposta.headers["Content-Disposition"]
    assert linhas[0] == "Data e hora;Registro;Estação;Parâmetro;Unidade;Valor"
    assert len(linhas) == 25
    assert linhas[1] == "2026-06-12 00:00;R-00;EST-8;pH;pH;7,250"
    assert "R-OUTRA" not in texto


def test_medicoes_ficam_em_cache_ate_a_ingestao(client, monkeypatch):
    consultas = []

    def contar(self):
        consultas.append(1)
        return [_medicao("R-1", datetime(2026, 6, 12, 10), 7.0)]

    monkeypatch.setattr(dashboard_module.LeituraRepository, "get_medicoes", contar)
    monkeypatch.setattr(dashboard_module, "iniciar_aplicacao", lambda etapa: None)
    monkeypatch.setattr(dashboard_module, "run_pipeline", lambda: {})

    client.get("/")
    client.get("/?pagina=2")
    client.get("/api/serie?codigo=TIP-PH")
    assert len(consultas) == 1

    client.post("/ingestao")
    client.get("/")
    assert len(consultas) == 2


def test_rota_ingestao_invoca_pipeline(client, monkeypatch):
    chamadas = []
    resumo = {"recebidos": 2, "registros_validos": 1, "leituras_gravadas": 1}
    monkeypatch.setattr(
        dashboard_module,
        "iniciar_aplicacao",
        lambda etapa: chamadas.append(etapa),
    )
    monkeypatch.setattr(dashboard_module, "run_pipeline", lambda: resumo)

    response = client.post("/ingestao")

    assert response.status_code == 200
    assert response.json == {"ok": True, "resumo": resumo}
    assert chamadas == ["ingestao"]


def test_rota_ingestao_nao_expoe_detalhes_da_excecao(client, monkeypatch):
    monkeypatch.setattr(dashboard_module, "iniciar_aplicacao", lambda etapa: None)

    def falhar():
        raise RuntimeError("detalhe de conexao sensivel")

    monkeypatch.setattr(dashboard_module, "run_pipeline", falhar)
    response = client.post("/ingestao")

    assert response.status_code == 500
    assert "RuntimeError" in response.json["mensagem"]
    assert "sensivel" not in response.get_data(as_text=True)


# --- Página "Testar API do BI" ------------------------------------------------


def test_pagina_api_bi_renderiza_servidor_e_situacao_da_chave(client, monkeypatch):
    monkeypatch.setenv("FONTE_DADOS", "http://api-bi:8000")
    monkeypatch.setenv("CHAVE_API_BI", "segredo-bi")

    html = client.get("/api-bi").get_data(as_text=True)

    assert "Testar API do BI" in html and "http://api-bi:8000" in html
    assert "configurada" in html and "segredo-bi" not in html


def test_dashboard_tem_link_para_a_pagina_da_api_bi(client):
    assert 'href="/api-bi"' in client.get("/").get_data(as_text=True)


def test_consulta_api_bi_repassa_rota_e_argumentos(client, monkeypatch):
    chamadas = []

    def consultar(rota, args):
        chamadas.append((rota, args.get("inicio")))
        return {"ok": True, "rota": rota}

    monkeypatch.setattr(dashboard_module.api_bi, "consultar", consultar)

    resposta = client.get("/api-bi/consulta?rota=medicoes&inicio=2026-06-01")

    assert resposta.status_code == 200 and resposta.get_json()["ok"]
    assert chamadas == [("medicoes", "2026-06-01")]


def test_consulta_api_bi_rota_invalida_responde_400(client):
    resposta = client.get("/api-bi/consulta?rota=data-set")
    assert resposta.status_code == 400
    assert "Rota desconhecida" in resposta.get_json()["mensagem"]


def test_status_api_bi_devolve_a_situacao_geral(client, monkeypatch):
    monkeypatch.setattr(dashboard_module.api_bi, "status", lambda: {"api": {"online": True}, "gold_disponivel": False})
    assert client.get("/api-bi/status").get_json() == {"api": {"online": True}, "gold_disponivel": False}
