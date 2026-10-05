from src.database.connection import DatabaseConnection
from src.models.parametro_model import ParametroModel


class ParametroRepository:

    __COLUNAS = "id_parametro, codigo_parametro, nome, unidade_medida, valor_minimo, valor_maximo"

    def __init__(
        self,
        database: DatabaseConnection | None = None
    ) -> None:
        self.__database = database or DatabaseConnection()

    def get_all(
        self
    ) -> list[ParametroModel]:
        """
        Retorna todos os parâmetros cadastrados.
        """

        query = f"""
            SELECT {self.__COLUNAS}
            FROM dbo.Parametros
            ORDER BY codigo_parametro
        """

        result = self.__database.fetch_all(query)

        return [self.__para_modelo(linha) for linha in result]

    def get_by_codigo(
        self,
        codigo_parametro: str
    ) -> ParametroModel | None:
        """
        Busca um parâmetro pelo código (valor de <param>_tipo_codigo no payload).
        """

        query = f"""
            SELECT {self.__COLUNAS}
            FROM dbo.Parametros
            WHERE codigo_parametro = ?
        """

        result = self.__database.fetch_one(
            query,
            (codigo_parametro,)
        )

        if not result:
            return None

        return self.__para_modelo(result)

    def create_many(
        self,
        parametros: list[ParametroModel]
    ) -> int:
        """
        Insere vários parâmetros de uma vez, sem duplicar.

        Um código que já exista é ignorado, então reexecutar não gera erro
        nem linha repetida (idempotente).
        """

        if not parametros:
            return 0

        query = """
            INSERT INTO dbo.Parametros
            (
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            )
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS
            (
                SELECT 1 FROM dbo.Parametros WHERE codigo_parametro = ?
            )
        """

        params = [
            (
                parametro.codigo_parametro,
                parametro.nome,
                parametro.unidade_medida,
                parametro.valor_minimo,
                parametro.valor_maximo,
                parametro.codigo_parametro
            )
            for parametro in parametros
        ]

        return self.__database.execute_many(
            query,
            params
        )

    @staticmethod
    def __para_modelo(linha) -> ParametroModel:
        return ParametroModel(
            id_parametro=linha[0],
            codigo_parametro=linha[1],
            nome=linha[2],
            unidade_medida=linha[3],
            valor_minimo=linha[4],
            valor_maximo=linha[5]
        )
