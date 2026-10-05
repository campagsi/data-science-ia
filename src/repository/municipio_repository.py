from src.database.connection import DatabaseConnection
from src.models.municipio_model import MunicipioModel


class MunicipioRepository:

    def __init__(
        self,
        database: DatabaseConnection | None = None
    ) -> None:
        self.__database = database or DatabaseConnection()

    def get_all(
        self
    ) -> list[MunicipioModel]:
        """
        Retorna todos os municípios cadastrados.
        """

        query = """
            SELECT id_municipio, nome, estado_id
            FROM dbo.Municipios
        """

        return [
            MunicipioModel(id_municipio=linha[0], nome=linha[1], estado_id=linha[2])
            for linha in self.__database.fetch_all(query)
        ]

    def merge_many(
        self,
        municipios: list[MunicipioModel]
    ) -> int:
        """
        Insere os municípios que ainda não existem (chave: nome + estado).

        Idempotente: reexecutar não duplica nem gera erro.
        """

        if not municipios:
            return 0

        query = """
            MERGE dbo.Municipios AS destino
            USING (SELECT ? AS nome, ? AS estado_id) AS origem
            ON destino.nome = origem.nome AND destino.estado_id = origem.estado_id
            WHEN NOT MATCHED BY TARGET THEN
                INSERT (nome, estado_id) VALUES (origem.nome, origem.estado_id);
        """

        return self.__database.execute_many(
            query,
            [(municipio.nome, municipio.estado_id) for municipio in municipios]
        )
