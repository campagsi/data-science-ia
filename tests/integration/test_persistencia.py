"""
Persistência idempotente no modelo 3FN (fase 8) com o dataset completo da API.

Cada teste parte do banco com só os 27 estados e os 11 parâmetros do DML
(fixture database) e grava o lote preparado como na run_pipeline() (fixture lote).
"""
import copy
from collections import defaultdict

import pytest

import src.ingestion.importar_dados as importar_dados
from src.api.dataset_repository import DatasetRepository
from src.repository.leitura_repository import LeituraRepository
from src.security import descriptografar_email

FONTE = "http://api-de-teste"


def _gravar(database, lote, registros=None):
    return LeituraRepository(database).save_readings(
        lote["validos"] if registros is None else registros, lote["parametros"], FONTE
    )


def _vazia(database, sql: str) -> bool:
    return database.fetch_all(sql) == []


def _estado(database) -> list[tuple]:
    """Leituras e itens gravados, para comparar o banco antes e depois de uma falha."""
    return [
        tuple(linha)
        for linha in database.fetch_all(
            "SELECT L.id_leitura, L.codigo_registro, I.parametro_id, I.valor "
            "FROM dbo.Leituras L JOIN dbo.Leitura_Itens I ON I.leitura_id = L.id_leitura "
            "ORDER BY L.id_leitura, I.parametro_id"
        )
    ]


def test_save_readings_grava_todas_as_entidades(database, contagens, lote):
    validos = lote["validos"]
    itens = sum(len(r["itens"]) for r in validos)

    resumo = _gravar(database, lote)

    assert len(validos) == 9806 and itens == 104582
    assert resumo == {
        "municipios": 1,
        "operadores": 1,
        "estacoes": 1,
        "leituras_removidas": 0,
        "leituras_gravadas": len(validos),
        "itens_gravados": itens,
    }
    assert contagens() == {
        "Estados": 27,
        "Municipios": 1,
        "Estacoes": 1,
        "Operadores": 1,
        "Parametros": 11,
        "Leituras": len(validos),
        "Leitura_Itens": itens,
    }
    assert database.fetch_one("SELECT DISTINCT fonte FROM dbo.Leituras")[0] == FONTE


def test_reprocessar_o_lote_substitui_sem_duplicar(database, contagens, lote):
    _gravar(database, lote)
    antes = contagens()

    resumo = _gravar(database, lote)

    assert contagens() == antes
    assert resumo["leituras_removidas"] == resumo["leituras_gravadas"] == len(lote["validos"])
    # Consultas da fase 9 de docs/todo-idempotencia.md: todas devem voltar vazias.
    assert _vazia(database, "SELECT estacao_id, data_hora FROM dbo.Leituras GROUP BY estacao_id, data_hora HAVING COUNT(*) > 1")
    assert _vazia(database, "SELECT codigo_registro FROM dbo.Leituras GROUP BY codigo_registro HAVING COUNT(*) > 1")
    assert _vazia(
        database,
        "SELECT L.id_leitura FROM dbo.Leituras L "
        "WHERE NOT EXISTS (SELECT 1 FROM dbo.Leitura_Itens I WHERE I.leitura_id = L.id_leitura)",
    )
    assert _vazia(
        database,
        "SELECT I.valor FROM dbo.Leitura_Itens I JOIN dbo.Parametros P ON P.id_parametro = I.parametro_id "
        "WHERE (P.valor_minimo IS NOT NULL AND I.valor < P.valor_minimo) "
        "OR (P.valor_maximo IS NOT NULL AND I.valor > P.valor_maximo)",
    )


def test_operador_gravado_sem_dado_pessoal_em_claro(database, lote):
    _gravar(database, lote)
    emails = {r["operador_email"] for r in DatasetRepository().get_all()}

    operadores = database.fetch_all(
        "SELECT nome_hash, cpf_hash, email_criptografado FROM dbo.Operadores"
    )

    for nome_hash, cpf_hash, email in operadores:
        assert len(nome_hash) == len(cpf_hash) == 64
        assert "@" not in email
        assert descriptografar_email(email) in emails


def test_backfill_de_um_dia_altera_so_aquela_particao(database, lote):
    _gravar(database, lote)
    por_dia = defaultdict(list)
    for registro in lote["validos"]:
        por_dia[registro["data_hora_ciclo"].date()].append(registro)
    dia = sorted(por_dia)[len(por_dia) // 2]

    # Reenvio do dia com um registro a menos e uma medição corrigida.
    reenvio = copy.deepcopy(por_dia[dia][1:])
    reenvio[0]["itens"][0]["valor"] += 0.5
    outros_dias = (
        "SELECT L.id_leitura, I.parametro_id, I.valor FROM dbo.Leituras L "
        "JOIN dbo.Leitura_Itens I ON I.leitura_id = L.id_leitura "
        "WHERE CAST(L.data_hora AS DATE) <> ? ORDER BY 1, 2"
    )
    antes = [tuple(linha) for linha in database.fetch_all(outros_dias, (dia,))]

    resumo = _gravar(database, lote, reenvio)

    assert resumo["leituras_removidas"] == len(por_dia[dia])
    assert resumo["leituras_gravadas"] == len(reenvio)
    assert [tuple(linha) for linha in database.fetch_all(outros_dias, (dia,))] == antes
    codigos = {
        linha[0]
        for linha in database.fetch_all(
            "SELECT codigo_registro FROM dbo.Leituras WHERE CAST(data_hora AS DATE) = ?", (dia,)
        )
    }
    assert codigos == {r["registro_codigo"] for r in reenvio}
    corrigido = reenvio[0]["itens"][0]
    valor = database.fetch_one(
        "SELECT I.valor FROM dbo.Leitura_Itens I "
        "JOIN dbo.Leituras L ON L.id_leitura = I.leitura_id "
        "JOIN dbo.Parametros P ON P.id_parametro = I.parametro_id "
        "WHERE L.codigo_registro = ? AND P.codigo_parametro = ?",
        (reenvio[0]["registro_codigo"], corrigido["codigo_parametro"]),
    )[0]
    assert valor == pytest.approx(corrigido["valor"])


@pytest.fixture
def simular_falha(monkeypatch):
    """
    Devolve uma função que, ao ser chamada, faz importar_leituras gravar leituras
    e itens de verdade e falhar logo depois, ainda dentro da transação.
    """
    original = importar_dados.importar_leituras

    def gravar_e_falhar(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("falha simulada no meio da carga")

    return lambda: monkeypatch.setattr(importar_dados, "importar_leituras", gravar_e_falhar)


def test_falha_na_primeira_carga_nao_deixa_nada_gravado(database, contagens, lote, simular_falha):
    simular_falha()

    with pytest.raises(RuntimeError, match="falha simulada"):
        _gravar(database, lote)

    assert contagens() == {
        "Estados": 27,
        "Municipios": 0,
        "Estacoes": 0,
        "Operadores": 0,
        "Parametros": 11,
        "Leituras": 0,
        "Leitura_Itens": 0,
    }


def test_falha_no_reprocessamento_preserva_a_carga_anterior(database, contagens, lote, simular_falha):
    _gravar(database, lote)
    antes = (contagens(), _estado(database))
    simular_falha()

    with pytest.raises(RuntimeError, match="falha simulada"):
        _gravar(database, lote)

    assert (contagens(), _estado(database)) == antes
