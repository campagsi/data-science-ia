from src.database import DatabaseConnection
from src.models.cidade_model import CidadeModel


class CidadeRepository:
    def __init__(self) -> None:
        self.__database = DatabaseConnection()

    def get_by_id(self, cidadeID: int) -> dict:
        query = "SELECT * FROM cidades WHERE id = ?"
        result = self.__database.fetch_one(query, (cidadeID,))

        if not result:
            return None

        return {"id": result[0], "nome": result[1], "estado": result[2]}

    def get_by_name(self, nome: str) -> dict | None:
        query = "SELECT id, nome, estado FROM cidades WHERE nome = ?"
        result = self.__database.fetch_one(
            query,
            (nome,),
        )

        if not result:
            return None

        return {"id": result[0], "nome": result[1], "estado": result[2]}

    def get_all(self) -> list:
        query = "SELECT id, nome, estado FROM cidades"
        result = self.__database.fetch_all(query)

        return [
            {
                "id": linha[0],
                "nome": linha[1],
                "estado": linha[2],
            }
            for linha in result
        ]

    def create(self, cidade: CidadeModel):
        query = "INSERT INTO cidades (nome, estado) VALUES (?, ?)"

        param = (cidade.nome, cidade.estado)

        return self.__database.execute(query, param)

    def create_many(self, cidades: list[CidadeModel]):
        query = "INSERT INTO cidades (nome, estado) VALUES (?, ?)"

        params = [
            (
                cidade.nome,
                cidade.estado,
            )
            for cidade in cidades
        ]

        return self.__database.execute_many(query, params)
