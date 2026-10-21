"""Testes da API do Power BI sobre a camada Gold (Parquet)."""
import os

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.bi_controller import BiController
from src.api.bi_service import BiService
from src.api.gold_repository import GoldIndisponivelError, GoldRepository


def _gravar_gold(pasta):
    pd.DataFrame(
        {
            "estacao_sk": [1, 2],
            "estacao_codigo": ["EST-1", "EST-2"],
            "estacao_nome": ["Centro", "Norte"],
            "cidade_estado": ["Campinas/SP", "Santos/SP"],
            "municipio": ["Campinas", "Santos"],
            "estacao_latitude": [-22.9, -23.9],
            "estacao_longitude": [-47.0, -46.3],
        }
    ).to_parquet(pasta / "estacoes.parquet", index=False)
    pd.DataFrame(
        {
            "parametro_sk": [1, 2],
            "codigo_parametro": ["TEMP", "PH"],
            "campo": ["temperatura", "ph"],
            "unidade_medida": ["°C", None],
        }
    ).to_parquet(pasta / "parametros.parquet", index=False)
    datas = pd.date_range("2026-06-01", "2026-06-03", freq="D")
    pd.DataFrame(
        {
            "tempo_sk": datas.strftime("%Y%m%d").astype("int64"),
            "data": datas,
            "ano": datas.year,
            "mes": datas.month,
            "dia": datas.day,
        }
    ).to_parquet(pasta / "tempo.parquet", index=False)
    pd.DataFrame(
        {
            "registro_codigo": ["R1", "R2", "R3", "R4", "R5"],
            "estacao_sk": [1, 1, 2, 1, 2],
            "parametro_sk": [1, 1, 1, 2, 1],
            "tempo_sk": [20260601, 20260601, 20260602, 20260603, 20260603],
            "data_hora_leitura": pd.to_datetime(
                [
                    "2026-06-01 10:00",
                    "2026-06-01 22:00",
                    "2026-06-02 08:00",
                    "2026-06-03 09:00",
                    "2026-06-03 23:59",
                ]
            ),
            "valor_lido": [20.0, 30.0, 25.0, 7.0, 99.0],
            "media_movel": [20.0, 25.0, 25.0, 7.0, 62.0],
            "indicador_outlier": [False, False, False, False, True],
        }
    ).to_parquet(pasta / "medicoes.parquet", index=False)


@pytest.fixture
def pasta_gold(tmp_path):
    _gravar_gold(tmp_path)
    return tmp_path


@pytest.fixture
def cliente(pasta_gold, monkeypatch):
    monkeypatch.delenv("CHAVE_API_BI", raising=False)
    app = FastAPI()
    app.include_router(BiController(BiService(GoldRepository(pasta_gold))).router)
    return TestClient(app)


# --- Repository ---------------------------------------------------------------


def test_repository_sem_gold_informa_indisponivel(tmp_path):
    with pytest.raises(GoldIndisponivelError, match="Execute o pipeline"):
        GoldRepository(tmp_path).ler("medicoes")


def test_repository_reaproveita_cache_e_rele_quando_o_arquivo_muda(pasta_gold):
    repositorio = GoldRepository(pasta_gold)
    primeira = repositorio.ler("estacoes")
    assert repositorio.ler("estacoes") is primeira

    arquivo = pasta_gold / "estacoes.parquet"
    primeira.head(1).to_parquet(arquivo, index=False)
    os.utime(arquivo, ns=(1, 1))  # garante mtime diferente mesmo em disco rápido

    assert len(repositorio.ler("estacoes")) == 1


def test_repository_arquivo_corrompido_vira_indisponivel(pasta_gold):
    (pasta_gold / "tempo.parquet").write_bytes(b"nao e parquet")
    with pytest.raises(GoldIndisponivelError, match="tempo.parquet"):
        GoldRepository(pasta_gold).ler("tempo")


def test_repository_usa_variavel_de_ambiente(pasta_gold, monkeypatch):
    monkeypatch.setenv("DIRETORIO_GOLD", str(pasta_gold))
    assert len(GoldRepository().ler("parametros")) == 2


# --- Dimensões ----------------------------------------------------------------


@pytest.mark.parametrize("rota, total", [("estacoes", 2), ("parametros", 2), ("tempo", 3)])
def test_dimensoes_devolvem_todas_as_linhas(cliente, rota, total):
    resposta = cliente.get(f"/api/v1/bi/{rota}")
    assert resposta.status_code == 200
    assert len(resposta.json()) == total


def test_dimensao_serializa_datas_iso_e_nulos(cliente):
    tempo = cliente.get("/api/v1/bi/tempo").json()
    assert tempo[0]["data"].startswith("2026-06-01T00:00:00")
    parametros = cliente.get("/api/v1/bi/parametros").json()
    assert parametros[1]["unidade_medida"] is None


def test_sem_gold_responde_503(tmp_path, monkeypatch):
    monkeypatch.delenv("CHAVE_API_BI", raising=False)
    app = FastAPI()
    app.include_router(BiController(BiService(GoldRepository(tmp_path))).router)
    resposta = TestClient(app).get("/api/v1/bi/estacoes")
    assert resposta.status_code == 503


# --- Medições -----------------------------------------------------------------


def test_medicoes_pagina_em_ordem_cronologica(cliente):
    corpo = cliente.get("/api/v1/bi/medicoes", params={"por_pagina": 2}).json()

    assert (corpo["total"], corpo["total_paginas"], corpo["tem_proxima"]) == (5, 3, True)
    assert [m["registro_codigo"] for m in corpo["dados"]] == ["R1", "R2"]

    ultima = cliente.get("/api/v1/bi/medicoes", params={"por_pagina": 2, "pagina": 3}).json()
    assert [m["registro_codigo"] for m in ultima["dados"]] == ["R5"]
    assert ultima["tem_proxima"] is False


def test_medicoes_pagina_alem_do_fim_vem_vazia(cliente):
    corpo = cliente.get("/api/v1/bi/medicoes", params={"pagina": 9}).json()
    assert corpo["dados"] == [] and corpo["total"] == 5


def test_medicoes_filtro_de_data_inclui_o_dia_final_inteiro(cliente):
    corpo = cliente.get(
        "/api/v1/bi/medicoes", params={"inicio": "2026-06-02", "fim": "2026-06-03"}
    ).json()
    assert [m["registro_codigo"] for m in corpo["dados"]] == ["R3", "R4", "R5"]


def test_medicoes_filtros_de_estacao_parametro_e_outlier(cliente):
    corpo = cliente.get(
        "/api/v1/bi/medicoes", params={"estacao_sk": 1, "parametro_sk": 1}
    ).json()
    assert [m["registro_codigo"] for m in corpo["dados"]] == ["R1", "R2"]

    outliers = cliente.get("/api/v1/bi/medicoes", params={"apenas_outliers": True}).json()
    assert [m["registro_codigo"] for m in outliers["dados"]] == ["R5"]


@pytest.mark.parametrize(
    "params",
    [
        {"inicio": "2026-06-03", "fim": "2026-06-01"},
        {"pagina": 0},
        {"por_pagina": 50001},
        {"inicio": "01/06/2026"},
    ],
)
def test_medicoes_parametros_invalidos_respondem_422(cliente, params):
    assert cliente.get("/api/v1/bi/medicoes", params=params).status_code == 422


def test_medicoes_diarias_agrega_por_dia_estacao_e_parametro(cliente):
    diarias = cliente.get("/api/v1/bi/medicoes/diarias").json()

    assert diarias[0] == {
        "tempo_sk": 20260601,
        "estacao_sk": 1,
        "parametro_sk": 1,
        "quantidade": 2,
        "media": 25.0,
        "minimo": 20.0,
        "maximo": 30.0,
        "outliers": 0,
    }
    assert len(diarias) == 4
    assert diarias[-1]["outliers"] == 1


def test_medicoes_diarias_recorte_vazio(cliente):
    resposta = cliente.get("/api/v1/bi/medicoes/diarias", params={"estacao_sk": 99})
    assert resposta.json() == []


# --- Chave de API -------------------------------------------------------------


def test_chave_configurada_exige_header(cliente, monkeypatch):
    monkeypatch.setenv("CHAVE_API_BI", "segredo-bi")

    assert cliente.get("/api/v1/bi/estacoes").status_code == 401
    assert cliente.get("/api/v1/bi/estacoes", headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente.get("/api/v1/bi/estacoes", headers={"X-API-Key": "segredo-bi"}).status_code == 200


def test_app_principal_registra_rotas_do_bi():
    from src.api.app import create_app

    caminhos = set(create_app().openapi()["paths"])
    assert {"/api/v1/data-set", "/api/v1/bi/medicoes", "/api/v1/bi/medicoes/diarias"} <= caminhos
