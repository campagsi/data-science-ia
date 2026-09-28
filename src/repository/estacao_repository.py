from src.database.connection import DatabaseConnection
from src.models.estacao_model import EstacaoModel


class EstacaoRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__database = database or DatabaseConnection()

    def get_all(self) -> list:
        query = "SELECT id, codigo, nome, cidade_id, operador_id, latitude, longitude, ativa, tipo FROM estacoes"
        result = self.__database.fetch_all(query)

        if not result:
            return None

        return {
            "id": result[0],
            "codigo": result[1],
            "nome": result[2],
            "cidade_id": result[3],
            "operador_id": result[4],
            "latitude": result[5],
            "longitude": result[6],
            "ativa": result[7],
            "tipo": result[8],
        }

    def get_by_codigo(self, codigo: str) -> dict | None:
        query = "SELECT id, codigo, nome, cidade_id, operador_id, latitude, longitude, ativa, tipo FROM dbo.Estacoes WHERE codigo = ?"
        result = self.__database.fetch_one(
            query,
            (codigo,),
        )

        if not result:
            return None

        return {
            "id": result[0],
            "codigo": result[1],
            "nome": result[2],
            "cidade_id": result[3],
            "operador_id": result[4],
            "latitude": result[5],
            "longitude": result[6],
            "ativa": result[7],
            "tipo": result[8],
        }

    def get_estacao_cidade(self, cidadeId: int):
        query = "SELECT id, codigo, nome, cidade_id, operador_id, latitude, longitude, ativa, tipo FROM estacoes WHERE cidade_id = ?"

        result = self.__database.fetch_all(
            query,
            (cidadeId,),
        )

        if not result:
            return None

        return [
            {
                "id": linha[0],
                "codigo": linha[1],
                "nome": linha[2],
                "cidade_id": linha[3],
                "operador_id": linha[4],
                "latitude": linha[5],
                "longitude": linha[6],
                "ativa": linha[7],
                "tipo": linha[8],
            }
            for linha in result
        ]

    def create_many(self, estacoes: list[EstacaoModel]):
        query = """
                    INSERT INTO 
                    estacoes (
                        codigo, 
                        nome, 
                        cidade_id, 
                        operador_id, 
                        latitude, 
                        longitude,  
                        ativa, 
                        tipo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
        params = [
            (
                estacao.codigo,
                estacao.nome,
                estacao.cidade_id,
                estacao.operador_id,
                estacao.latitude,
                estacao.longitude,
                estacao.ativa,
                estacao.tipo,
            )
            for estacao in estacoes
        ]

        return self.__database.execute_many(query, params)

    def insert_estacao(self, estacoes: list[EstacaoModel]):
        """Método-ponte para a operação de inserção de estações."""
        return self.create_many(estacoes)
