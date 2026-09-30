from datetime import date

import pytest

from src.repository.leitura_repository import LeituraRepository


def test_save_readings_persiste_entidades_relacionadas(database, contagens, registros_completos):
    LeituraRepository(database).save_readings(registros_completos)

    assert contagens() == {
        "Cidades": 10,
        "Operadores": 25,
        "Estacoes": 30,
        "Leituras": len(registros_completos),
    }
    orfas = database.fetch_one(
        "SELECT COUNT(*) FROM dbo.Leituras L LEFT JOIN dbo.Estacoes E ON E.id = L.estacao_id WHERE E.id IS NULL"
    )[0]
    assert orfas == 0


def test_falha_em_leituras_desfaz_o_lote_inteiro(database, contagens, registro_normalizado):
    invalido = dict(registro_normalizado, fonte=None)

    with pytest.raises((RuntimeError, ValueError)):
        LeituraRepository(database).save_readings([invalido])

    assert contagens() == {"Cidades": 0, "Operadores": 0, "Estacoes": 0, "Leituras": 0}


def test_consultas_filtram_por_periodo(database, registros_completos):
    LeituraRepository(database).save_readings(registros_completos)
    repositorio = LeituraRepository(database)
    cidade_id = database.fetch_one("SELECT id FROM dbo.Cidades WHERE nome = 'Rio de Janeiro'")[0]

    def contar(filtro: str, *params) -> int:
        return database.fetch_one(
            "SELECT COUNT(*) FROM dbo.Leituras L JOIN dbo.Estacoes E ON E.id = L.estacao_id "
            f"WHERE E.cidade_id = ? {filtro}",
            (cidade_id, *params),
        )[0]

    todas = repositorio.get_leituras_meteorologicas_by_cidade(cidade_id)
    um_dia = repositorio.get_leituras_meteorologicas_by_cidade(cidade_id, date(2026, 6, 1))
    periodo = repositorio.get_leituras_qualidade_agua_by_cidade(cidade_id, date(2026, 6, 1), date(2026, 6, 30))

    assert len(todas) == contar("")
    assert len(um_dia) == contar("AND CAST(L.data_hora AS DATE) = ?", date(2026, 6, 1))
    assert len(periodo) == contar("AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?", date(2026, 6, 1), date(2026, 6, 30))
    assert 0 < len(um_dia) < len(periodo) < len(todas)
    assert {"estacao", "data_hora", "temperatura"} <= set(todas[0])


def test_consulta_sem_leituras_devolve_none(database):
    assert LeituraRepository(database).get_leituras_meteorologicas_by_estacao(999) is None


@pytest.mark.xfail(
    strict=True,
    reason="Idempotência pendente: o schema atual não possui restrições UNIQUE (Fase 7).",
)
def test_reprocessar_o_lote_nao_duplica_leituras(database, contagens, registros_completos):
    LeituraRepository(database).save_readings(registros_completos)
    antes = contagens()

    try:
        LeituraRepository(database).save_readings(registros_completos)
    except RuntimeError:
        pass

    assert contagens() == antes
