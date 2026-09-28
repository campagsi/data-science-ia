from datetime import date

from src.database.connection import DatabaseConnection
from src.models.leitura_model import LeituraModel


class LeituraRepository:
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
                L.data_hora,
                E.nome
                FROM Leituras L
                INNER JOIN Estacoes E ON L.estacao_id = E.id
                WHERE E.cidade_id = ?               
            """

        params = [cidade_id]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            params.append(data_inicio)

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"
            params.extend([data_inicio, data_fim])

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

        params = [estacao_id]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            params.append(data_inicio)

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"
            params.extend([data_inicio, data_fim])

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

        params = [estacao_id]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            params.append(data_inicio)

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"
            params.extend([data_inicio, data_fim])

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

        params = [estacao_id]

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            params.append(data_inicio)

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"
            params.extend([data_inicio, data_fim])

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

    def create_many(self, leituras: list[LeituraModel]):
        query = """
            INSERT INTO Leituras (
                estacao_id,
                data_hora,
                temperatura,
                umidade,
                pressao,
                precipitacao,
                velocidade_vento,
                direcao_vento,
                radiacao_solar,
                temperatura_agua,
                ph,
                oxigenio_dissolvido,
                condutividade,
                turbidez,
                fonte
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [
            (
                leitura.estacao_id,
                leitura.data_hora,
                leitura.temperatura,
                leitura.umidade,
                leitura.pressao,
                leitura.precipitacao,
                leitura.velocidade_vento,
                leitura.direcao_vento,
                leitura.radiacao_solar,
                leitura.temperatura_agua,
                leitura.ph,
                leitura.oxigenio_dissolvido,
                leitura.condutividade,
                leitura.turbidez,
                leitura.fonte,
            )
            for leitura in leituras
        ]

        return self.__database.execute_many(query, params)

    def insert_leituras(self, leituras: list[LeituraModel]):
        """Método-ponte para a operação de inserção de leituras."""
        return self.create_many(leituras)

    def save_readings(self, registros_ok: list[dict]) -> dict[str, int]:
        """
        Coordena a persistência das entidades na ordem de dependência.

        Todas as etapas usam a mesma transação: se qualquer uma falhar, nada
        do lote permanece gravado.
        """
        from src.ingestion.importar_dados import (
            importar_cidades,
            importar_estacoes,
            importar_leituras,
            importar_operadores,
            __dict__ as ingestion_state,
        )

        for cache_name in ("__cidades", "__operadores", "__estacoes"):
            cache = ingestion_state.get(cache_name)
            if isinstance(cache, dict):
                cache.clear()

        with self.__database.transaction() as database:
            importar_cidades(registros_ok, database)
            importar_operadores(registros_ok, database)
            importar_estacoes(registros_ok, database)
            importar_leituras(registros_ok, database)

        return {"registros": len(registros_ok)}
