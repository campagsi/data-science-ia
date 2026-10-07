from contextlib import contextmanager
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from mssql_python import connect

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class DatabaseConnection:
    def __init__(self, connection_string: str | None = None):
        self.__connection_string = connection_string or getenv(
            "AZURE_SQL_CONNECTIONSTRING"
        )
        if not self.__connection_string:
            raise ValueError("A string de conexão não foi preenchida corretamente.")

        self.__transaction_connection = None

    def connect(self):
        """Abre uma conexão para a unidade de persistência."""
        return connect(self.__connection_string)

    @contextmanager
    def transaction(self):
        """
        Mantém uma única conexão aberta para todas as operações do bloco.

        Ao final do bloco é feito commit; se qualquer operação falhar, é feito
        rollback e nenhuma alteração do lote permanece no banco.
        """
        if self.__transaction_connection is not None:
            raise RuntimeError("Já existe uma transação ativa nesta conexão.")

        try:
            with self.connect() as connection:
                self.__transaction_connection = connection
                yield self
        finally:
            self.__transaction_connection = None

    @contextmanager
    def __cursor(self):
        """Usa a conexão da transação ativa ou abre uma conexão própria."""
        if self.__transaction_connection is not None:
            with self.__transaction_connection.cursor() as cursor:
                yield cursor
            return

        # Fora de uma transação, a conexão faz commit ao sair sem erro.
        with self.connect() as connection, connection.cursor() as cursor:
            yield cursor

    def execute(self, sql: str, params: tuple = ()) -> int:
        """
        Executa INSERT, UPDATE ou DELETE.

        Retorna a quantidade de registros afetados.
        """
        try:
            with self.__cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.rowcount

        except Exception as error:
            raise RuntimeError(
                f"Erro ao executar operação no banco de dados: {error}"
            ) from error

    def execute_many(self, sql: str, params: list[tuple]) -> int:
        """
        Executa uma mesma instrução "INSERT, UPDATE ou DELETE" para vários conjuntos de parâmetros.

        Exemplo:
            INSERT INTO Cidades (nome, estado) VALUES (?, ?)
        """
        if not params:
            return 0

        try:
            with self.__cursor() as cursor:
                cursor.executemany(sql, params)
                return cursor.rowcount

        except Exception as error:
            raise RuntimeError(f"Erro ao executar operação em lote: {error}") from error

    # O SQL Server aceita no máximo 2100 parâmetros por comando.
    __MAX_PARAMETROS = 2000

    def insert_em_lotes(self, tabela: str, colunas: tuple[str, ...], linhas: list[tuple]) -> int:
        """
        Insere muitas linhas com INSERT de várias linhas por comando.

        Evita uma ida ao banco por linha (executemany) em cargas grandes.
        `tabela` e `colunas` vêm do código, nunca do payload; os valores
        sempre vão como parâmetros.

        Exemplo:
            insert_em_lotes("#itens", ("codigo_registro", "parametro_id", "valor"), linhas)
        """
        if not linhas:
            return 0

        por_comando = max(1, self.__MAX_PARAMETROS // len(colunas))
        marcadores = "(" + ", ".join("?" * len(colunas)) + ")"
        inseridas = 0

        for inicio in range(0, len(linhas), por_comando):
            lote = linhas[inicio:inicio + por_comando]
            sql = (
                f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES "
                + ", ".join([marcadores] * len(lote))
            )
            parametros = tuple(valor for linha in lote for valor in linha)
            self.execute(sql, parametros)
            inseridas += len(lote)

        return inseridas

    def fetch_one(self, sql: str, params: tuple = ()):
        """Executa um SELECT e retorna somente um registro."""
        try:
            with self.__cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()

        except Exception as error:
            raise RuntimeError(f"Erro ao consultar um registro: {error}") from error

    def fetch_all(self, sql: str, params: list[tuple] | None = None) -> list:
        """Executa um SELECT e retorna todos os registros selecionados."""
        try:
            with self.__cursor() as cursor:
                cursor.execute(sql, params or ())
                return list(cursor.fetchall())

        except Exception as error:
            raise RuntimeError(f"Erro ao consultar registros: {error}") from error
