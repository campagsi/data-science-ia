from src.database.connection import DatabaseConnection
from src.models.parametro_model import ParametroModel


class ParametroRepository:

    @staticmethod
    def _to_model(
        row: tuple
    ) -> ParametroModel:
        """
        Converte uma linha do banco em ParametroModel.
        """

        return ParametroModel(
            id_parametro=row[0],
            codigo_parametro=row[1],
            nome=row[2],
            unidade_medida=row[3],
            valor_minimo=row[4],
            valor_maximo=row[5]
        )

    @staticmethod
    def _to_model_list(
        rows: list[tuple]
    ) -> list[ParametroModel]:
        """
        Converte uma lista de linhas do banco
        em uma lista de ParametroModel.
        """

        return [
            ParametroRepository._to_model(row)
            for row in rows
        ]

    def __init__(
        self,
        database: DatabaseConnection | None = None
    ) -> None:
        """
        Inicializa o repository com uma conexão recebida
        ou cria uma nova conexão com o banco.
        """

        self.__database = database or DatabaseConnection()

    def create(
        self,
        parametro: ParametroModel
    ) -> int:
        """
        Insere um parâmetro no banco de dados.
        """

        query = """
            INSERT INTO Parametros
            (
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """

        params = (
            parametro.codigo_parametro,
            parametro.nome,
            parametro.unidade_medida,
            parametro.valor_minimo,
            parametro.valor_maximo
        )

        return self.__database.execute(
            query,
            params
        )

    def create_many(
        self,
        parametros: list[ParametroModel]
    ) -> int:
        """
        Insere vários parâmetros no banco de dados.
        """

        if not parametros:
            return 0

        query = """
            INSERT INTO Parametros
            (
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """

        params = [
            (
                parametro.codigo_parametro,
                parametro.nome,
                parametro.unidade_medida,
                parametro.valor_minimo,
                parametro.valor_maximo
            )
            for parametro in parametros
        ]

        return self.__database.execute_many(
            query,
            params
        )

    def get_by_id(
        self,
        parametro_id: int
    ) -> ParametroModel | None:
        """
        Busca um parâmetro pelo ID.
        """

        query = """
            SELECT
                id_parametro,
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            FROM Parametros
            WHERE id_parametro = ?
        """

        result = self.__database.fetch_one(
            query,
            (parametro_id,)
        )

        if not result:
            return None

        return self._to_model(result)

    def get_by_codigo(
        self,
        codigo_parametro: str
    ) -> ParametroModel | None:
        """
        Busca um parâmetro pelo código.
        """

        query = """
            SELECT
                id_parametro,
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            FROM Parametros
            WHERE codigo_parametro = ?
        """

        result = self.__database.fetch_one(
            query,
            (codigo_parametro,)
        )

        if not result:
            return None

        return self._to_model(result)

    def get_all(
        self
    ) -> list[ParametroModel]:
        """
        Retorna todos os parâmetros cadastrados,
        ordenados pelo nome.
        """

        query = """
            SELECT
                id_parametro,
                codigo_parametro,
                nome,
                unidade_medida,
                valor_minimo,
                valor_maximo
            FROM Parametros
            ORDER BY nome
        """

        result = self.__database.fetch_all(query)

        return self._to_model_list(result)