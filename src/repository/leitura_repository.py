from datetime import date

from src.database.connection import DatabaseConnection
from src.models.leitura_item_model import LeituraItemModel
from src.models.leitura_model import LeituraModel
from src.models.parametro_model import ParametroModel


class LeituraRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__database = database or DatabaseConnection()

    # Consultas legadas da Parte 1 (modelo antigo, uma coluna por medição).
    # Só a análise (src/services/analytics_service.py) as usa; serão adaptadas
    # ao modelo Leituras + Leitura_Itens + Parametros na fase de analytics.
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

    def substituir_leituras(
        self,
        leituras: list[LeituraModel],
        itens: list[LeituraItemModel],
    ) -> dict[str, int]:
        """
        Grava as leituras e os itens substituindo as partições afetadas.

        Partição = estação + dia da leitura. Toda leitura já gravada numa
        partição do lote, ou com o mesmo codigo_registro, é apagada (itens
        primeiro) e o lote é inserido de novo. Assim, reexecutar o mesmo
        período (backfill) não duplica nada e reflete exatamente o lote atual.

        Usa tabelas temporárias da sessão (#lote, #itens): deve rodar dentro de
        DatabaseConnection.transaction(), que mantém uma única conexão.
        """
        if not leituras:
            return {"leituras_removidas": 0, "leituras_gravadas": 0, "itens_gravados": 0}

        db = self.__database
        db.execute("""
            DROP TABLE IF EXISTS #lote;
            DROP TABLE IF EXISTS #itens;
            DROP TABLE IF EXISTS #remover;
            CREATE TABLE #lote (
                codigo_registro VARCHAR(50) NOT NULL PRIMARY KEY,
                operador_id INT NOT NULL,
                estacao_id INT NOT NULL,
                data_hora DATETIME2 NOT NULL,
                fonte VARCHAR(100) NOT NULL
            );
            CREATE TABLE #itens (
                codigo_registro VARCHAR(50) NOT NULL,
                parametro_id INT NOT NULL,
                valor FLOAT NOT NULL,
                PRIMARY KEY (codigo_registro, parametro_id)
            );
        """)

        db.insert_em_lotes(
            "#lote",
            ("codigo_registro", "operador_id", "estacao_id", "data_hora", "fonte"),
            [
                (l.codigo_registro, l.operador_id, l.estacao_id, l.data_hora, l.fonte)
                for l in leituras
            ],
        )
        db.insert_em_lotes(
            "#itens",
            ("codigo_registro", "parametro_id", "valor"),
            [(i.codigo_registro, i.parametro_id, i.valor) for i in itens],
        )

        db.execute("""
            SELECT L.id_leitura
            INTO #remover
            FROM dbo.Leituras AS L
            WHERE EXISTS (
                    SELECT 1 FROM #lote AS T
                    WHERE T.estacao_id = L.estacao_id
                      AND CAST(T.data_hora AS DATE) = CAST(L.data_hora AS DATE))
               OR EXISTS (
                    SELECT 1 FROM #lote AS T
                    WHERE T.codigo_registro = L.codigo_registro);
        """)
        db.execute("""
            DELETE I FROM dbo.Leitura_Itens AS I
            INNER JOIN #remover AS R ON R.id_leitura = I.leitura_id;
        """)
        removidas = db.execute("""
            DELETE L FROM dbo.Leituras AS L
            INNER JOIN #remover AS R ON R.id_leitura = L.id_leitura;
        """)

        gravadas = db.execute("""
            INSERT INTO dbo.Leituras (codigo_registro, operador_id, estacao_id, data_hora, fonte)
            SELECT codigo_registro, operador_id, estacao_id, data_hora, fonte
            FROM #lote;
        """)
        itens_gravados = db.execute("""
            INSERT INTO dbo.Leitura_Itens (leitura_id, parametro_id, valor)
            SELECT L.id_leitura, I.parametro_id, I.valor
            FROM #itens AS I
            INNER JOIN dbo.Leituras AS L ON L.codigo_registro = I.codigo_registro;
        """)

        db.execute("DROP TABLE #lote; DROP TABLE #itens; DROP TABLE #remover;")
        return {
            "leituras_removidas": removidas,
            "leituras_gravadas": gravadas,
            "itens_gravados": itens_gravados,
        }

    def insert_leituras(self, leituras: list[LeituraModel], itens: list[LeituraItemModel]):
        """Método-ponte para a operação de gravação de leituras e itens."""
        return self.substituir_leituras(leituras, itens)

    def save_readings(
        self,
        registros_ok: list[dict],
        parametros: dict[str, ParametroModel],
        fonte: str,
    ) -> dict[str, int]:
        """
        Coordena a persistência das entidades na ordem de dependência:
        Estados (leitura) → Municípios → Operadores → Estações → Leituras + itens.

        registros_ok: só os registros válidos (ValidationService.registros_validos).
        parametros: retorno de ParametroService.sincronizar() (código → id).

        Todas as etapas usam a mesma transação: se qualquer uma falhar, nada
        do lote permanece gravado.
        """
        from src.ingestion.importar_dados import (
            importar_estacoes,
            importar_leituras,
            importar_municipios,
            importar_operadores,
        )
        from src.repository.estado_repository import EstadoRepository

        with self.__database.transaction() as database:
            estados = {e.sigla: e.id_estado for e in EstadoRepository(database).get_all()}
            municipios = importar_municipios(registros_ok, estados, database)
            operadores = importar_operadores(registros_ok, municipios, database)
            estacoes = importar_estacoes(registros_ok, municipios, database)
            contagens = importar_leituras(
                registros_ok, operadores, estacoes, parametros, fonte, database
            )

        return {
            "municipios": len(set(municipios.values())),
            "operadores": len(operadores),
            "estacoes": len(estacoes),
            **contagens,
        }
