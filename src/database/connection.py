from os import getenv

from dotenv import load_dotenv
from mssql_python import connect

load_dotenv()


class DatabaseConnection:
    def __init__(self):
        self.__connection_string = getenv("AZURE_SQL_CONNECTIONSTRING")
        if not self.__connection_string:
            raise ValueError("A string de conexão não foi preenchida corretamente.")

    def execute(self, sql: str, params: tuple = ()) -> int:
        """
        Executa INSERT, UPDATE ou DELETE.

        Retorna a quantidade de registros afetados.
        """
        try:
            with connect(self.__connection_string) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    affected_rows = cursor.rowcount

                connection.commit()

                return affected_rows

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
            with connect(self.__connection_string) as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(sql, params)
                    affected_rows = cursor.rowcount

                connection.commit()

                return affected_rows

        except Exception as error:
            raise RuntimeError(f"Erro ao executar operação em lote: {error}") from error

    def fetch_one(self, sql: str, params: tuple = ()):
        """Executa um SELECT e retorna somente um registro."""
        try:
            with (
                connect(self.__connection_string) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, params)
                return cursor.fetchone()

        except Exception as error:
            raise RuntimeError(f"Erro ao consultar um registro: {error}") from error

    def fetch_all(self, sql: str, params: list[tuple] | None = None) -> list:
        """Executa um SELECT e retorna todos os registros selecionados."""
        try:
            with (
                connect(self.__connection_string) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, params or ())
                return list(cursor.fetchall())

        except Exception as error:
            raise RuntimeError(f"Erro ao consultar registros: {error}") from error
