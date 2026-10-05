"""
Testes de integração com SQL Server.

Executados somente quando TEST_SQL_MASTER_CONNECTIONSTRING aponta para o banco
master de uma instância de teste, por exemplo:

    Server=localhost\\SQLEXPRESS;Database=master;Trusted_Connection=yes;Encrypt=no

Cada sessão cria um banco descartável e o remove ao final.
"""
import os
import re
import uuid
from pathlib import Path

import pytest

MASTER = os.getenv("TEST_SQL_MASTER_CONNECTIONSTRING", "")
RAIZ = Path(__file__).resolve().parents[2]
# Ordem de limpeza: tabelas filhas antes das mães.
TABELAS = (
    "Leitura_Itens",
    "Leituras",
    "Parametros",
    "Estacoes",
    "Operadores",
    "Municipios",
    "Estados",
)


def _admin(sql: str) -> None:
    from mssql_python import connect

    with connect(MASTER, autocommit=True) as conexao, conexao.cursor() as cursor:
        cursor.execute(sql)


def _lotes(script: Path) -> list[str]:
    """Separa um script SQL nos lotes delimitados por GO."""
    texto = script.read_text(encoding="utf-8-sig")
    return [lote for lote in re.split(r"^\s*GO\s*$", texto, flags=re.MULTILINE | re.IGNORECASE) if lote.strip()]


def _criar_schema(database) -> None:
    """Aplica o DDL, as migrations em ordem de nome (V001, V002...) e o DML de domínio."""
    scripts = [RAIZ / "sql" / "ddl_banco_relacional.sql"]
    scripts += sorted((RAIZ / "sql" / "migrations").glob("V*.sql"))
    scripts.append(RAIZ / "sql" / "dml_populacao.sql")
    for script in scripts:
        for lote in _lotes(script):
            database.execute(lote)


@pytest.fixture(scope="session")
def connection_string():
    if not MASTER:
        pytest.skip("TEST_SQL_MASTER_CONNECTIONSTRING não configurada")

    nome = f"pipeline_teste_{uuid.uuid4().hex[:8]}"
    remover = (
        f"IF DB_ID('{nome}') IS NOT NULL BEGIN "
        f"ALTER DATABASE {nome} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE {nome}; END"
    )
    _admin(f"CREATE DATABASE {nome}")
    try:
        from src.database.connection import DatabaseConnection

        cs = MASTER.replace("Database=master", f"Database={nome}")
        _criar_schema(DatabaseConnection(cs))
        yield cs
    finally:
        _admin(remover)


@pytest.fixture
def database(connection_string):
    """
    Conexão com o banco de teste, limpo a cada teste.

    Todas as tabelas são esvaziadas e o DML de domínio é reaplicado, para que
    cada teste comece só com os 27 estados e os 11 parâmetros conhecidos
    (sem parâmetros cadastrados por um teste anterior).
    """
    from src.database.connection import DatabaseConnection

    db = DatabaseConnection(connection_string)
    for tabela in TABELAS:
        db.execute(f"DELETE FROM dbo.{tabela}")
        if tabela != "Leitura_Itens":  # PK composta, sem IDENTITY
            db.execute(f"DBCC CHECKIDENT ('dbo.{tabela}', RESEED, 0) WITH NO_INFOMSGS")
    for lote in _lotes(RAIZ / "sql" / "dml_populacao.sql"):
        db.execute(lote)
    return db


@pytest.fixture(scope="session")
def registros_completos():
    """Registros do dataset da API que possuem todas as medições."""
    from src.api.dataset_repository import DatasetRepository
    from src.services.normalization_service import NormalizationService
    from src.services.validation_service import ValidationService

    normalizados = NormalizationService().normalize(DatasetRepository().get_all())
    completos = [
        r for r in normalizados
        if all(
            r.get(campo) is not None
            for campo in ValidationService._REQUIRED_FIELDS + NormalizationService._FLOAT_FIELDS
        )
    ]
    return ValidationService().validate_data(completos)


@pytest.fixture
def contagens(database):
    """Quantidade de registros por tabela no banco de teste."""
    return lambda: {
        t: database.fetch_one(f"SELECT COUNT(*) FROM dbo.{t}")[0] for t in reversed(TABELAS)
    }
