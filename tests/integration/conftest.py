"""
Testes de integração com SQL Server.

Executados somente quando TEST_SQL_MASTER_CONNECTIONSTRING aponta para o banco
master de uma instância de teste, por exemplo:

    Server=localhost\\SQLEXPRESS;Database=master;Trusted_Connection=yes;Encrypt=no

Cada sessão cria um banco descartável e o remove ao final.
"""
import os
import uuid

import pytest

MASTER = os.getenv("TEST_SQL_MASTER_CONNECTIONSTRING", "")
TABELAS = ("Leituras", "Estacoes", "Operadores", "Cidades")


def _admin(sql: str) -> None:
    from mssql_python import connect

    with connect(MASTER, autocommit=True) as conexao, conexao.cursor() as cursor:
        cursor.execute(sql)


def _criar_schema(database) -> None:
    """
    Cria o schema atual de criar_tabelas.py em banco vazio.

    criar_tabelas() falha em banco vazio porque __criar_tabela_estacoes()
    executa ALTER TABLE Leituras antes de a tabela existir (pendência da
    Fase 7). Uma tabela Leituras provisória contorna a falha sem alterar o
    schema produzido.
    """
    import src.database.criar_tabelas as schema

    schema.database = database
    getattr(schema, "__criar_tabela_cidades")()
    getattr(schema, "__criar_tabela_operadores")()
    database.execute("CREATE TABLE dbo.Leituras (fonte VARCHAR(100))")
    getattr(schema, "__criar_tabela_estacoes")()
    database.execute("DROP TABLE dbo.Leituras")
    getattr(schema, "__criar_tabela_leituras")()


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
    """Conexão com o banco de teste, com as tabelas vazias a cada teste."""
    import src.database.criar_tabelas as schema
    from src.database.connection import DatabaseConnection

    db = DatabaseConnection(connection_string)
    for tabela in TABELAS:
        db.execute(f"DELETE FROM dbo.{tabela}")
        # Reinicia o IDENTITY: o pipeline analisa cidade_id=1, fixo em run_pipeline().
        db.execute(f"DBCC CHECKIDENT ('dbo.{tabela}', RESEED, 0) WITH NO_INFOMSGS")
    schema.database = db
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
