"""
Dashboard (src/ui/app.py): filtros de estado, cidade e estação na lateral, e o
cabeçalho da página com a estação, a cidade e o estado escolhidos.

Usa o cliente de teste do Flask com medições e cadastros em memória (sem banco).
"""
import re
from datetime import datetime

import pytest

from src.models.estacao_model import EstacaoModel
from src.models.estado_model import EstadoModel
from src.ui import app as dashboard_module
from src.ui.app import create_app

# Estação → município: 1 e 2 no RJ (cidades diferentes), 3 em SP.
MUNICIPIO_DA_ESTACAO = {1: 10, 2: 20, 3: 30}
MUNICIPIOS = [
    {"id": 20, "nome": "Niterói", "sigla": "RJ"},
    {"id": 10, "nome": "Rio de Janeiro", "sigla": "RJ"},
    {"id": 30, "nome": "Santos", "sigla": "SP"},
]
ESTADOS = [EstadoModel(id_estado=1, sigla="RJ", nome="Rio de Janeiro"), EstadoModel(id_estado=2, sigla="SP", nome="São Paulo")]


def medicao(estacao_id: int, dia: int) -> dict:
    return {
        "estacao_id": estacao_id,
        "estacao_codigo": f"EST-{estacao_id}",
        "estacao": f"Estação {estacao_id}",
        "codigo_parametro": "TIP-PH",
        "parametro": "pH",
        "unidade_medida": "pH",
        "data_hora": datetime(2026, 6, dia, 10),
        "valor": 7.0 + dia / 10,
        "codigo_registro": f"R{estacao_id}-{dia}",
    }


def estacao(estacao_id: int) -> EstacaoModel:
    return EstacaoModel(id_estacao=estacao_id, codigo_estacao=f"EST-{estacao_id}", nome=f"Estação {estacao_id}",
                        municipio_id=MUNICIPIO_DA_ESTACAO[estacao_id], latitude=-22.9, longitude=-43.2)


def montar(monkeypatch, localizacao_falha: bool = False):
    medicoes = [medicao(numero, dia) for numero in (1, 2, 3) for dia in range(1, 6)]
    monkeypatch.setattr(dashboard_module, "load_config", lambda: type("C", (), {"azure_sql_connectionstring": "x"})())
    monkeypatch.setattr(dashboard_module.LeituraRepository, "get_medicoes", lambda self: medicoes)
    if localizacao_falha:
        def falhar(self):
            raise ConnectionError("sem banco")
        monkeypatch.setattr(dashboard_module.EstacaoRepository, "get_all", falhar)
    else:
        monkeypatch.setattr(dashboard_module.EstacaoRepository, "get_all", lambda self: [estacao(n) for n in (1, 2, 3)])
    monkeypatch.setattr(dashboard_module.MunicipioRepository, "get_com_estacoes", lambda self: MUNICIPIOS)
    monkeypatch.setattr(dashboard_module.EstadoRepository, "get_all", lambda self: ESTADOS)
    dashboard_module.limpar_cache()
    aplicacao = create_app()
    aplicacao.config.update(TESTING=True)
    return aplicacao.test_client()


@pytest.fixture
def cliente(monkeypatch):
    yield montar(monkeypatch)
    dashboard_module.limpar_cache()


def estacoes_na_tabela(html: str) -> set[str]:
    """Códigos de estação da tabela de medições."""
    tabela = html.split('<th>Data e hora</th>', 1)[1]
    return set(re.findall(r"<td>(EST-\d)</td>", tabela))


def test_lateral_tem_filtros_de_estado_cidade_e_estacao(cliente):
    html = cliente.get("/").get_data(as_text=True)

    assert '<option value="RJ" >RJ · Rio de Janeiro</option>' in html
    assert '<option value="SP" >SP · São Paulo</option>' in html
    assert '<option value="20" data-uf="RJ" >Niterói (RJ)</option>' in html
    assert '<option value="3" data-uf="SP" data-municipio="30" >EST-3 · Estação 3</option>' in html
    assert html.index('id="state-filter"') < html.index('id="city-filter"') < html.index('id="station-filter"')


def test_estacao_selecionada_mostra_estacao_cidade_e_estado_no_cabecalho(cliente):
    html = cliente.get("/?estacao=2").get_data(as_text=True)

    assert "<title>Leituras da estação EST-2 | Dados Ambientais</title>" in html
    assert "<h1>Leituras da estação</h1>" in html
    assert '<p class="station-name">EST-2 · Estação 2</p>' in html
    assert re.search(r'<p class="station-place">Cidade: Niterói <span class="eyebrow-dot">·</span> Estado: Rio de Janeiro \(RJ\)</p>', html)
    assert '<span class="chip">EST-2 · Estação 2</span>' in html
    assert '<option value="2" data-uf="RJ" data-municipio="20" selected>EST-2 · Estação 2</option>' in html
    assert estacoes_na_tabela(html) == {"EST-2"}


def test_filtro_por_estado_mostra_so_as_estacoes_do_estado(cliente):
    html = cliente.get("/?estado=SP").get_data(as_text=True)

    assert estacoes_na_tabela(html) == {"EST-3"}
    assert '<p class="station-name">Todas as estações</p>' in html
    assert "Cidade: todas" in html and "Estado: São Paulo (SP)" in html
    assert '<span class="chip">SP</span>' in html
    assert '<option value="SP" selected>SP · São Paulo</option>' in html


def test_filtro_por_cidade_mostra_so_as_estacoes_da_cidade(cliente):
    html = cliente.get("/?estado=RJ&municipio=10").get_data(as_text=True)

    assert estacoes_na_tabela(html) == {"EST-1"}
    assert "Cidade: Rio de Janeiro" in html and "Estado: Rio de Janeiro (RJ)" in html
    assert '<span class="chip">Rio de Janeiro</span>' in html


def test_csv_respeita_o_filtro_de_estado(cliente):
    csv = cliente.get("/exportar.csv?estado=RJ").get_data(as_text=True)

    assert "EST-1" in csv and "EST-2" in csv and "EST-3" not in csv


def test_sem_estacao_o_titulo_fica_no_plural(cliente):
    html = cliente.get("/").get_data(as_text=True)

    assert "<h1>Leituras das estações</h1>" in html
    assert '<p class="station-name">Todas as estações</p>' in html
    assert "station-place" not in html
    assert " selected>EST-" not in html


def test_estacao_inexistente_nao_quebra_a_pagina(cliente):
    resposta = cliente.get("/?estacao=99")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "<h1>Leituras das estações</h1>" in html
    assert '<p class="station-name">Todas as estações</p>' in html


def test_sem_localizacao_a_pagina_segue_so_com_o_filtro_de_estacao(monkeypatch):
    cliente = montar(monkeypatch, localizacao_falha=True)
    resposta = cliente.get("/?estacao=1")
    html = resposta.get_data(as_text=True)
    dashboard_module.limpar_cache()

    assert resposta.status_code == 200
    assert 'id="state-filter"' not in html and 'id="city-filter"' not in html
    assert '<p class="station-name">EST-1 · Estação 1</p>' in html
    assert "station-place" not in html
    assert estacoes_na_tabela(html) == {"EST-1"}
