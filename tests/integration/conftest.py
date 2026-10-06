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


def limpar_banco(connection_string: str):
    """
    Esvazia todas as tabelas e reaplica o DML de domínio, para começar só com
    os 27 estados e os 11 parâmetros conhecidos. Devolve a conexão.
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


def preparar_lote(database, normalizados: list[dict]) -> dict:
    """
    Prepara o lote como a run_pipeline(): sincroniza os parâmetros com o banco
    e valida com as faixas e siglas lidas dele.

    Devolve {"validos", "parametros", "resultados"}; "validos" é o que vai para
    LeituraRepository.save_readings().
    """
    from src.repository.estado_repository import EstadoRepository
    from src.repository.parametro_repository import ParametroRepository
    from src.services.normalization_service import NormalizationService
    from src.services.parametro_service import ParametroService
    from src.services.validation_service import ValidationService

    parametros = ParametroService(ParametroRepository(database)).sincronizar(
        NormalizationService.descobrir_parametros(normalizados)
    )
    resultados = ValidationService(
        faixas=ParametroService.faixas(parametros),
        siglas_estados={e.sigla for e in EstadoRepository(database).get_all()},
        parametros_validos=set(parametros),
    ).validate_data(normalizados)
    return {
        "validos": ValidationService.registros_validos(resultados),
        "parametros": parametros,
        "resultados": resultados,
    }


@pytest.fixture
def database(connection_string):
    """Conexão com o banco de teste, limpo a cada teste (limpar_banco)."""
    return limpar_banco(connection_string)


@pytest.fixture(scope="session")
def normalizados():
    """Dataset da API normalizado e anonimizado com as chaves de teste (fase 4)."""
    from src.api.dataset_repository import DatasetRepository
    from src.security import configurar_seguranca
    from src.services.normalization_service import NormalizationService

    configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], os.environ["PEPPER_HASH"])
    return NormalizationService().normalize(DatasetRepository().get_all())


@pytest.fixture
def lote(database, normalizados):
    """Lote do dataset completo pronto para gravar (preparar_lote)."""
    return preparar_lote(database, normalizados)


@pytest.fixture
def contagens(database):
    """Quantidade de registros por tabela no banco de teste."""
    return lambda: {
        t: database.fetch_one(f"SELECT COUNT(*) FROM dbo.{t}")[0] for t in reversed(TABELAS)
    }


@pytest.fixture(scope="module")
def banco_carregado(connection_string, normalizados):
    """
    Banco de teste com o dataset completo gravado uma vez por módulo, para
    testes só de leitura (consultas e análise). Os testes que usam a fixture
    database limpam o banco de novo.
    """
    from src.repository.leitura_repository import LeituraRepository

    db = limpar_banco(connection_string)
    lote = preparar_lote(db, normalizados)
    LeituraRepository(db).save_readings(lote["validos"], lote["parametros"], "http://api-de-teste")
    return db


@pytest.fixture(scope="session")
def consultas_analiticas() -> list[str]:
    """Lotes de sql/queries_analiticas.sql, na ordem do arquivo."""
    return _lotes(RAIZ / "sql" / "queries_analiticas.sql")
