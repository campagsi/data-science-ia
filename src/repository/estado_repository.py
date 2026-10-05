from src.database.connection import DatabaseConnection
from src.models.estado_model import EstadoModel


class EstadoRepository:

    def __init__(
        self,
        database: DatabaseConnection | None = None
    ) -> None:
        self.__database = database or DatabaseConnection()

    def create(
        self,
        estado: EstadoModel
    ) -> int:
        """
        Insere um estado.
        """

        query = """
            INSERT INTO Estados
            (
                sigla,
                nome
            )
            VALUES
            (
                ?,
                ?
            )
        """

        params = (
            estado.sigla,
            estado.nome
        )

        return self.__database.execute(
            query,
            params
        )

    def create_many(
        self,
        estados: list[EstadoModel]
    ) -> int:
        """
        Insere vários estados de uma única vez.
        """

        if not estados:
            return 0

        query = """
            INSERT INTO Estados
            (
                sigla,
                nome
            )
            VALUES
            (
                ?,
                ?
            )
        """

        params = [
            (
                estado.sigla,
                estado.nome
            )
            for estado in estados
        ]

        return self.__database.execute_many(
            query,
            params
        )

    def get_by_id(
        self,
        estado_id: int
    ) -> EstadoModel | None:
        """
        Busca um estado pelo ID.
        """

        query = """
            SELECT
                id_estado,
                sigla,
                nome
            FROM Estados
            WHERE id_estado = ?
        """

        result = self.__database.fetch_one(
            query,
            (estado_id,)
        )

        if not result:
            return None

        return EstadoModel(
            id_estado=result[0],
            sigla=result[1],
            nome=result[2]
        )

    def get_by_sigla(
        self,
        sigla: str
    ) -> EstadoModel | None:
        """
        Busca um estado pela sigla.
        """

        query = """
            SELECT
                id_estado,
                sigla,
                nome
            FROM Estados
            WHERE sigla = ?
        """

        result = self.__database.fetch_one(
            query,
            (sigla,)
        )

        if not result:
            return None

        return EstadoModel(
            id_estado=result[0],
            sigla=result[1],
            nome=result[2]
        )

    def get_all(
        self
    ) -> list[EstadoModel]:
        """
        Retorna todos os estados cadastrados.
        """

        query = """
            SELECT
                id_estado,
                sigla,
                nome
            FROM Estados
            ORDER BY nome
        """

        result = self.__database.fetch_all(query)

        return [
            EstadoModel(
                id_estado=linha[0],
                sigla=linha[1],
                nome=linha[2]
            )
            for linha in result
        ]