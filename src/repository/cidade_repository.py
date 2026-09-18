from src.database.connection import DatabaseConnection


class CidadeRepository:
    @staticmethod
    def get_cidade_by_id(cidade_id: int):
        query = f"SELECT * FROM cidades WHERE id = {cidade_id}"
        result = DatabaseConnection.execute(query)
        return result

    @staticmethod
    def create_cidade(nome: str, estado: str):
        query = f"INSERT INTO cidades (nome, estado) VALUES ('{nome}', '{estado}')"
        DatabaseConnection.execute(query)

    @staticmethod
    def create_many_cidades(cidades: list):
        query = "INSERT INTO cidades (nome, estado) VALUES (?, ?)"
        DatabaseConnection.execute_many(query, cidades)

    