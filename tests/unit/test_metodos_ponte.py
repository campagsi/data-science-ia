"""Métodos-ponte do diagrama de sequência e controle de transação."""
from contextlib import contextmanager

import pytest

import src.database.connection as connection_module
import src.ingestion.importar_dados as importar_dados
from src.database.connection import DatabaseConnection
from src.repository.estacao_repository import EstacaoRepository
from src.repository.leitura_repository import LeituraRepository


class ConexaoFalsa:
    """Imita a conexão do mssql_python: commit ao sair sem erro, rollback com erro."""

    def __init__(self):
        self.executados = []
        self.resultado = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.resultado = "rollback" if exc_type else "commit"

    def cursor(self):
        conexao = self

        class Cursor:
            rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, sql, params=()):
                conexao.executados.append(sql)

            def executemany(self, sql, params):
                conexao.executados.append(sql)

        return Cursor()


def test_connect_usa_string_de_conexao(monkeypatch):
    recebido = []
    monkeypatch.setattr(connection_module, "connect", lambda cs: recebido.append(cs) or "conexao")

    assert DatabaseConnection("Server=teste").connect() == "conexao"
    assert recebido == ["Server=teste"]


def test_transacao_usa_uma_unica_conexao_e_faz_commit(monkeypatch):
    conexoes = []

    def connect_falso(cs):
        conexoes.append(ConexaoFalsa())
        return conexoes[-1]

    monkeypatch.setattr(connection_module, "connect", connect_falso)
    database = DatabaseConnection("Server=teste")

    with database.transaction():
        database.execute("INSERT 1")
        database.execute_many("INSERT 2", [(1,)])

    assert len(conexoes) == 1
    assert conexoes[0].executados == ["INSERT 1", "INSERT 2"]
    assert conexoes[0].resultado == "commit"


def test_transacao_faz_rollback_quando_falha(monkeypatch):
    conexao = ConexaoFalsa()
    monkeypatch.setattr(connection_module, "connect", lambda cs: conexao)
    database = DatabaseConnection("Server=teste")

    with pytest.raises(RuntimeError, match="falha no lote"):
        with database.transaction():
            database.execute("INSERT 1")
            raise RuntimeError("falha no lote")

    assert conexao.resultado == "rollback"


def test_transacao_nao_pode_ser_aninhada(monkeypatch):
    monkeypatch.setattr(connection_module, "connect", lambda cs: ConexaoFalsa())
    database = DatabaseConnection("Server=teste")

    with database.transaction():
        with pytest.raises(RuntimeError, match="transação ativa"):
            with database.transaction():
                pass


def test_insert_estacao_delega_para_merge_many(monkeypatch):
    monkeypatch.setattr(EstacaoRepository, "merge_many", lambda self, estacoes: ("merge_many", estacoes))

    assert EstacaoRepository(object()).insert_estacao(["e1"]) == ("merge_many", ["e1"])


def test_insert_leituras_delega_para_substituir_leituras(monkeypatch):
    monkeypatch.setattr(
        LeituraRepository, "substituir_leituras", lambda self, leituras, itens: ("substituir", leituras, itens)
    )

    assert LeituraRepository(object()).insert_leituras(["l1"], ["i1"]) == ("substituir", ["l1"], ["i1"])


@pytest.fixture
def estados_falsos(monkeypatch):
    from src.models import EstadoModel
    from src.repository.estado_repository import EstadoRepository

    monkeypatch.setattr(
        EstadoRepository, "get_all", lambda self: [EstadoModel(id_estado=19, sigla="RJ", nome="Rio de Janeiro")]
    )


def test_save_readings_persiste_na_ordem_dentro_da_transacao(monkeypatch, estados_falsos):
    eventos = []

    class DatabaseFalso:
        @contextmanager
        def transaction(self):
            eventos.append("inicio")
            yield self
            eventos.append("commit")

    database = DatabaseFalso()
    monkeypatch.setattr(
        importar_dados, "importar_municipios",
        lambda dados, estados, db: eventos.append(("municipios", estados, db is database))
        or {("Rio de Janeiro", "RJ"): 7},
    )
    monkeypatch.setattr(
        importar_dados, "importar_operadores",
        lambda dados, municipios, db: eventos.append(("operadores", municipios)) or {"OP-1": 3},
    )
    monkeypatch.setattr(
        importar_dados, "importar_estacoes",
        lambda dados, municipios, db: eventos.append(("estacoes", municipios)) or {"EST-1": 5},
    )
    monkeypatch.setattr(
        importar_dados, "importar_leituras",
        lambda dados, operadores, estacoes, parametros, fonte, db: eventos.append(
            ("leituras", operadores, estacoes, parametros, fonte)
        ) or {"leituras_removidas": 0, "leituras_gravadas": 2, "itens_gravados": 20},
    )

    resultado = LeituraRepository(database).save_readings([{}, {}], {"TIP-PH": "ph"}, "http://api-de-teste")

    assert resultado == {
        "municipios": 1, "operadores": 1, "estacoes": 1,
        "leituras_removidas": 0, "leituras_gravadas": 2, "itens_gravados": 20,
    }
    assert eventos == [
        "inicio",
        ("municipios", {"RJ": 19}, True),
        ("operadores", {("Rio de Janeiro", "RJ"): 7}),
        ("estacoes", {("Rio de Janeiro", "RJ"): 7}),
        ("leituras", {"OP-1": 3}, {"EST-1": 5}, {"TIP-PH": "ph"}, "http://api-de-teste"),
        "commit",
    ]


def test_save_readings_interrompe_o_lote_na_primeira_falha(monkeypatch, estados_falsos):
    chamadas = []

    class DatabaseFalso:
        @contextmanager
        def transaction(self):
            yield self

    def falhar(*args):
        raise RuntimeError("Falha ao importar Operadores")

    monkeypatch.setattr(importar_dados, "importar_municipios", lambda *a: chamadas.append("municipios") or {})
    monkeypatch.setattr(importar_dados, "importar_operadores", falhar)
    monkeypatch.setattr(importar_dados, "importar_estacoes", lambda *a: chamadas.append("estacoes") or {})
    monkeypatch.setattr(importar_dados, "importar_leituras", lambda *a: chamadas.append("leituras") or {})

    with pytest.raises(RuntimeError, match="Operadores"):
        LeituraRepository(DatabaseFalso()).save_readings([{}], {}, "http://api-de-teste")

    assert chamadas == ["municipios"]
