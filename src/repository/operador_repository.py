from src.database.connection import DatabaseConnection
from src.models.operador_model import OperadorModel


class OperadorRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__database = database or DatabaseConnection()

    def get_by_id(self, operadorID: int) -> dict:
        query = "SELECT * FROM operadores WHERE id = ?"
        result = self.__database.execute(query, (operadorID,))

        if not result:
            return None

        return {"id": result[0], "nome": result[1], "estado": result[2]}

    def get_by_name(self, nome: str) -> dict | None:
        query = "SELECT * FROM operadores WHERE nome = ?"
        result = self.__database.fetch_one(
            query,
            (nome,),
        )

        if not result:
            return None

        return {"id": result[0], "nome": result[1], "estado": result[2]}

    def create(self, nome: str, estado: str):
        query = f"INSERT INTO cidades (codigo, nome, tipo, cidade_id) VALUES ('{nome}', '{estado}')"
        return self.__database.execute(query)

    def create_many(self, operadores: list[OperadorModel]):
        query = (
            "INSERT INTO operadores (codigo, nome, tipo, cidade_id) VALUES (?, ?, ?, ?)"
        )
        params = [
            (operador.codigo, operador.nome, operador.tipo, operador.cidade_id)
            for operador in operadores
        ]

        return self.__database.execute_many(query, params)
