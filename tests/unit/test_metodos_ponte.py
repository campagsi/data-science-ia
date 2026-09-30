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


def test_insert_estacao_delega_para_create_many(monkeypatch):
    monkeypatch.setattr(EstacaoRepository, "create_many", lambda self, estacoes: ("create_many", estacoes))

    assert EstacaoRepository(object()).insert_estacao(["e1"]) == ("create_many", ["e1"])


def test_insert_leituras_delega_para_create_many(monkeypatch):
    monkeypatch.setattr(LeituraRepository, "create_many", lambda self, leituras: ("create_many", leituras))

    assert LeituraRepository(object()).insert_leituras(["l1"]) == ("create_many", ["l1"])


def test_save_readings_persiste_na_ordem_dentro_da_transacao(monkeypatch):
    eventos = []

    class DatabaseFalso:
        @contextmanager
        def transaction(self):
            eventos.append("inicio")
            yield self
            eventos.append("commit")

    database = DatabaseFalso()
    for nome in ("importar_cidades", "importar_operadores", "importar_estacoes", "importar_leituras"):
        monkeypatch.setattr(
            importar_dados,
            nome,
            lambda dados, db, nome=nome: eventos.append((nome, len(dados), db is database)),
        )

    resultado = LeituraRepository(database).save_readings([{}, {}])

    assert resultado == {"registros": 2}
    assert eventos == [
        "inicio",
        ("importar_cidades", 2, True),
        ("importar_operadores", 2, True),
        ("importar_estacoes", 2, True),
        ("importar_leituras", 2, True),
        "commit",
    ]


def test_save_readings_interrompe_o_lote_na_primeira_falha(monkeypatch):
    chamadas = []

    class DatabaseFalso:
        @contextmanager
        def transaction(self):
            yield self

    def falhar(dados, db):
        raise RuntimeError("Falha ao importar Operadores")

    monkeypatch.setattr(importar_dados, "importar_cidades", lambda d, db: chamadas.append("cidades"))
    monkeypatch.setattr(importar_dados, "importar_operadores", falhar)
    monkeypatch.setattr(importar_dados, "importar_estacoes", lambda d, db: chamadas.append("estacoes"))
    monkeypatch.setattr(importar_dados, "importar_leituras", lambda d, db: chamadas.append("leituras"))

    with pytest.raises(RuntimeError, match="Operadores"):
        LeituraRepository(DatabaseFalso()).save_readings([{}])

    assert chamadas == ["cidades"]
