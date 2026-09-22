from datetime import date

from src.database.connection import DatabaseConnection
from src.models.operador_model import OperadorModel


class LeituraRepository:
    def __init__(self) -> None:
        self.__database = DatabaseConnection()

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

    def get_leituras_meteorologicas_by_cidade(
        self,
        cidade_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ):

        query = """
                SELECT
                L.temperatura, 
                L.pressao,
                L.umidade,
                L.precipitacao,
                L.velocidade_vento,
                L.radiacao_solar,
                L.data_hora
                E.nome
                FROM Leituras L
                INNER JOIN Estacoes E ON L.estacao_id = E.id
                WHERE E.cidade_id = ?               
            """

        params = [cidade_id, data_inicio, data_fim]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            # params.insert((data_inicio,))

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"

        result = self.__database.fetch_all(query, params)

        if not result:
            return None

        return [
            {
                "temperatura": linha[0],
                "pressao": linha[1],
                "umidade": linha[2],
                "precipitacao": linha[3],
                "velocidade_vento": linha[4],
                "radiacao_solar": linha[5],
                "data_hora": linha[6],
                "estacao": linha[7],
            }
            for linha in result
        ]

    def get_leituras_qualidade_agua_by_cidade(
        self,
        estacao_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ):

        query = """
                            SELECT
                            L.temperatura_agua,
                            L.ph,
                            L.oxigenio_dissolvido,
                            L.condutividade,
                            L.turbidez,
                            L.data_hora,
                            E.nome
                            FROM Leituras L
                            INNER JOIN Estacoes E ON L.estacao_id = E.id
                            WHERE E.cidade_id = ?               
                        """

        params = [estacao_id, data_inicio, data_fim]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"

        result = self.__database.fetch_all(query, params)

        if not result:
            return None

        return [
            {
                "temperatura_agua": linha[0],
                "ph": linha[1],
                "oxigenio_dissolvido": linha[2],
                "condutividade": linha[3],
                "turbidez": linha[4],
                "data_hora": linha[5],
                "estacao": linha[6],
            }
            for linha in result
        ]

    def get_leituras_meteorologicas_by_estacao(
        self,
        estacao_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ):

        query = """
                    SELECT
                    L.temperatura, 
                    L.pressao,
                    L.umidade,
                    L.precipitacao,
                    L.velocidade_vento,
                    L.radiacao_solar,
                    L.data_hora
                    FROM Leituras L
                    WHERE L.estacao_id = ?               
                """

        params = [estacao_id, data_inicio, data_fim]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"

        result = self.__database.fetch_all(query, params)

        if not result:
            return None

        return [
            {
                "temperatura": linha[0],
                "pressao": linha[1],
                "umidade": linha[2],
                "precipitacao": linha[3],
                "velocidade_vento": linha[4],
                "radiacao_solar": linha[5],
                "data_hora": linha[6],
            }
            for linha in result
        ]

    def get_leituras_qualidade_agua_by_estacao(
        self,
        estacao_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ):

        query = """
                    SELECT
                    L.temperatura_agua,
                    L.ph,
                    L.oxigenio_dissolvido,
                    L.condutividade,
                    L.turbidez,
                    L.data_hora
                    FROM Leituras as L
                    WHERE estacao_id = ?               
                """

        params = [estacao_id, data_inicio, data_fim]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"

        result = self.__database.fetch_all(query, params)

        if not result:
            return None

        return [
            {
                "temperatura_agua": linha[0],
                "ph": linha[1],
                "oxigenio_dissolvido": linha[2],
                "condutividade": linha[3],
                "turbidez": linha[4],
                "data_hora": linha[5],
            }
            for linha in result
        ]

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
