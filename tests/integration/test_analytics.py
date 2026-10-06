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

ITENS_GRAVADOS = 104582
LEITURAS_GRAVADAS = 9806


@pytest.fixture(scope="module")
def analise(banco_carregado):
    return AnaliticsService(banco_carregado).calculate_metrics()


def _consulta(database, lote: str) -> list[tuple]:
    return [tuple(linha) for linha in database.fetch_all(lote)]


def test_get_medicoes_devolve_todos_os_itens_gravados(banco_carregado):
    medicoes = LeituraRepository(banco_carregado).get_medicoes()

    assert len(medicoes) == ITENS_GRAVADOS
    assert len({m["codigo_registro"] for m in medicoes}) == LEITURAS_GRAVADAS
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
    assert 0 < len(um_dia) < len(periodo) < ITENS_GRAVADOS
    assert {m["codigo_parametro"] for m in so_ph} == {"TIP-PH"}
    assert len(so_ph) == sum(1 for m in um_dia if m["codigo_parametro"] == "TIP-PH")
    assert repositorio.get_medicoes(estacao_id=-1) == []


def test_municipios_e_estacoes_para_a_cli(banco_carregado):
    (municipio,) = MunicipioRepository(banco_carregado).get_com_estacoes()
    (estacao,) = EstacaoRepository(banco_carregado).get_by_municipio(municipio["id"])

    assert municipio["sigla"] == "RJ"
    assert EstacaoRepository(banco_carregado).get_by_codigo(estacao.codigo_estacao) == estacao
    assert EstacaoRepository(banco_carregado).get_by_codigo("NAO-EXISTE") is None
    assert LeituraRepository(banco_carregado).get_medicoes(municipio_id=municipio["id"], data_inicio=date(2000, 1, 1)) == []


def test_analise_cobre_os_11_parametros(analise):
    assert analise["leituras"] == LEITURAS_GRAVADAS
    assert analise["medicoes"] == ITENS_GRAVADOS
    assert len(analise["estatisticas"]) == 11
    assert sum(e["Quantidade"] for e in analise["estatisticas"]) == ITENS_GRAVADOS
    assert sum(e["Anomalias"] for e in analise["estatisticas"]) == len(analise["anomalias"])
    assert {a["Alerta"] for a in analise["anomalias"]} <= {"IQR", "ZSCORE", "IQR+ZSCORE"}


def test_consulta_de_metricas_bate_com_o_servico(banco_carregado, consultas_analiticas, analise):
    sql = {linha[2]: linha for linha in _consulta(banco_carregado, consultas_analiticas[0])}
    servico = {e["Código"]: e for e in analise["estatisticas"]}

    assert set(sql) == set(servico)
    for codigo, (_, _, _, _, unidade, quantidade, media, desvio, variancia, minimo, maximo) in sql.items():
        e = servico[codigo]
        assert (unidade, quantidade) == (e["Unidade"], e["Quantidade"])
        assert media == pytest.approx(e["Média"])
        assert desvio == pytest.approx(e["Desvio Padrão"])
        assert variancia == pytest.approx(e["Variância"])
        assert (minimo, maximo) == pytest.approx((e["Mínimo"], e["Máximo"]))


def test_consulta_de_quartis_bate_com_o_servico(banco_carregado, consultas_analiticas, analise):
    servico = {e["Código"]: e for e in analise["estatisticas"]}

    linhas = _consulta(banco_carregado, consultas_analiticas[1])

    assert len(linhas) == 11
    for _, codigo, mediana, q1, q3, iqr, inferior, superior in linhas:
        e = servico[codigo]
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

    assert sum(linha[2] for linha in por_dia) == LEITURAS_GRAVADAS
    assert sum(linha[3] for linha in por_dia) == ITENS_GRAVADOS
    assert len(por_parametro) == 11
    assert sum(linha[2] for linha in por_parametro) == ITENS_GRAVADOS


def test_analise_pelo_main_registra_cada_anomalia_no_log(banco_carregado, analise, logs_temporarios):
    (estacao,) = EstacaoRepository(banco_carregado).get_all()

    relatorio = main.gerar_relatorio(banco_carregado, estacao.codigo_estacao)

    linhas = logs_temporarios("pipeline")
    alertas = [linha for linha in linhas if "Alerta de qualidade" in linha]
    assert relatorio["escopo"] == {"estacao_id": estacao.id_estacao}
    assert len(alertas) == len(relatorio["anomalias"]) == len(analise["anomalias"])
    assert all("[WARNING]" in linha for linha in alertas)
    assert Counter(linha.split("alerta=")[1].split()[0] for linha in alertas) == Counter(
        a["Alerta"] for a in analise["anomalias"]
    )
    assert any("Relatório da execução" in linha for linha in linhas)
