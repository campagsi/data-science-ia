"""
Analytics no modelo 3FN com o dataset completo gravado (fases 13 a 15).

O banco é carregado uma vez para o módulo (fixture banco_carregado) e os
testes só leem. As consultas de sql/queries_analiticas.sql precisam bater com
o AnaliticsService.
"""
from collections import Counter
from datetime import date

import pytest

import main
from src.repository import EstacaoRepository, LeituraRepository, MunicipioRepository
from src.services.analytics_service import AnaliticsService

@pytest.fixture(scope="module")
def analise(banco_carregado):
    return AnaliticsService(banco_carregado).calculate_metrics()


def _consulta(database, lote: str) -> list[tuple]:
    return [tuple(linha) for linha in database.fetch_all(lote)]


def test_get_medicoes_devolve_todos_os_itens_gravados(banco_carregado):
    medicoes = LeituraRepository(banco_carregado).get_medicoes()
    itens_gravados = banco_carregado.fetch_one("SELECT COUNT(*) FROM dbo.Leitura_Itens")[0]
    leituras_gravadas = banco_carregado.fetch_one("SELECT COUNT(*) FROM dbo.Leituras")[0]

    assert len(medicoes) == itens_gravados
    assert len({m["codigo_registro"] for m in medicoes}) == leituras_gravadas
    assert set(medicoes[0]) == {
        "estacao_id", "estacao_codigo", "estacao", "codigo_registro", "data_hora",
        "codigo_parametro", "parametro", "unidade_medida", "valor",
    }
    ordem = [(m["estacao_codigo"], m["codigo_parametro"], m["data_hora"]) for m in medicoes]
    assert ordem == sorted(ordem)


def test_get_medicoes_filtra_por_dia_periodo_estacao_e_parametro(banco_carregado):
    repositorio = LeituraRepository(banco_carregado)
    dias = sorted({m["data_hora"].date() for m in repositorio.get_medicoes(codigos_parametro=["TIP-PH"])})
    dia, fim = dias[1], dias[5]

    um_dia = repositorio.get_medicoes(data_inicio=dia)
    periodo = repositorio.get_medicoes(data_inicio=dia, data_fim=fim)
    estacao_id = um_dia[0]["estacao_id"]
    so_ph = repositorio.get_medicoes(estacao_id=estacao_id, data_inicio=dia, codigos_parametro=["TIP-PH"])

    assert {m["data_hora"].date() for m in um_dia} == {dia}
    assert {m["data_hora"].date() for m in periodo} == set(dias[1:6])
    assert 0 < len(um_dia) < len(periodo) < len(repositorio.get_medicoes())
    assert {m["codigo_parametro"] for m in so_ph} == {"TIP-PH"}
    assert len(so_ph) == sum(1 for m in um_dia if m["codigo_parametro"] == "TIP-PH")
    assert repositorio.get_medicoes(estacao_id=-1) == []


def test_municipios_e_estacoes_para_a_cli(banco_carregado):
    municipios = MunicipioRepository(banco_carregado).get_com_estacoes()
    estacoes_repository = EstacaoRepository(banco_carregado)

    assert len(municipios) > 1
    for municipio in municipios:
        estacoes = estacoes_repository.get_by_municipio(municipio["id"])
        assert estacoes
        for estacao in estacoes:
            assert estacoes_repository.get_by_codigo(estacao.codigo_estacao) == estacao
        assert LeituraRepository(banco_carregado).get_medicoes(
            municipio_id=municipio["id"], data_inicio=date(2000, 1, 1)
        ) == []
    assert estacoes_repository.get_by_codigo("NAO-EXISTE") is None


def test_analise_cobre_os_11_parametros(banco_carregado, analise):
    assert analise["leituras"] > 0
    estacoes = EstacaoRepository(banco_carregado).get_all()
    assert len(analise["estatisticas"]) == len(estacoes) * 11
    assert sum(e["Quantidade"] for e in analise["estatisticas"]) == analise["medicoes"]
    assert sum(e["Anomalias"] for e in analise["estatisticas"]) == len(analise["anomalias"])
    assert {a["Alerta"] for a in analise["anomalias"]} <= {"IQR", "ZSCORE", "IQR+ZSCORE"}


def test_consulta_de_metricas_bate_com_o_servico(banco_carregado, consultas_analiticas, analise):
    sql = {(linha[0], linha[2]): linha for linha in _consulta(banco_carregado, consultas_analiticas[0])}
    nomes_estacoes = {
        estacao.nome: estacao.codigo_estacao
        for estacao in EstacaoRepository(banco_carregado).get_all()
    }
    servico = {
        (nomes_estacoes[e["Estação"]], e["Código"]): e
        for e in analise["estatisticas"]
    }

    assert set(sql) == set(servico)
    for chave, (_, _, _, _, unidade, quantidade, media, desvio, variancia, minimo, maximo) in sql.items():
        e = servico[chave]
        assert (unidade, quantidade) == (e["Unidade"], e["Quantidade"])
        assert media == pytest.approx(e["Média"])
        assert desvio == pytest.approx(e["Desvio Padrão"])
        assert variancia == pytest.approx(e["Variância"])
        assert (minimo, maximo) == pytest.approx((e["Mínimo"], e["Máximo"]))


def test_consulta_de_quartis_bate_com_o_servico(banco_carregado, consultas_analiticas, analise):
    nomes_estacoes = {
        estacao.nome: estacao.codigo_estacao
        for estacao in EstacaoRepository(banco_carregado).get_all()
    }
    servico = {
        (nomes_estacoes[e["Estação"]], e["Código"]): e
        for e in analise["estatisticas"]
    }

    linhas = _consulta(banco_carregado, consultas_analiticas[1])

    assert len(linhas) == len(servico)
    for estacao, codigo, mediana, q1, q3, iqr, inferior, superior in linhas:
        e = servico[(estacao, codigo)]
        assert (mediana, q1, q3, iqr) == pytest.approx((e["Mediana"], e["Q1"], e["Q3"], e["IQR"]))
        assert (inferior, superior) == pytest.approx((e["Limite Inferior"], e["Limite Superior"]))


def test_consulta_de_anomalias_bate_com_o_servico(banco_carregado, consultas_analiticas, analise):
    nomes = dict(banco_carregado.fetch_all("SELECT codigo_parametro, nome FROM dbo.Parametros"))

    sql = {
        (registro, nomes[codigo], alerta)
        for _, codigo, registro, _, _, _, alerta in _consulta(banco_carregado, consultas_analiticas[2])
    }
    servico = {(a["Registro"], a["Parâmetro"], a["Alerta"]) for a in analise["anomalias"]}

    assert sql == servico
    assert len(servico) > 0


def test_consultas_de_volume(banco_carregado, consultas_analiticas):
    por_dia = _consulta(banco_carregado, consultas_analiticas[3])
    por_parametro = _consulta(banco_carregado, consultas_analiticas[4])
    leituras_gravadas = banco_carregado.fetch_one("SELECT COUNT(*) FROM dbo.Leituras")[0]
    itens_gravados = banco_carregado.fetch_one("SELECT COUNT(*) FROM dbo.Leitura_Itens")[0]

    assert sum(linha[2] for linha in por_dia) == leituras_gravadas
    assert sum(linha[3] for linha in por_dia) == itens_gravados
    assert len(por_parametro) == 11
    assert sum(linha[2] for linha in por_parametro) == itens_gravados


def test_analise_pelo_main_registra_cada_anomalia_no_log(banco_carregado, analise, logs_temporarios):
    estacao = EstacaoRepository(banco_carregado).get_all()[0]

    relatorio = main.gerar_relatorio(banco_carregado, estacao.codigo_estacao)

    linhas = logs_temporarios("pipeline")
    alertas = [linha for linha in linhas if "Alerta de qualidade" in linha]
    assert relatorio["escopo"] == {"estacao_id": estacao.id_estacao}
    assert len(alertas) == len(relatorio["anomalias"])
    assert all("[WARNING]" in linha for linha in alertas)
    assert Counter(linha.split("alerta=")[1].split()[0] for linha in alertas) == Counter(
        a["Alerta"] for a in relatorio["anomalias"]
    )
    assert any("Relatório da execução" in linha for linha in linhas)
