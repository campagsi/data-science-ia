from datetime import date

from src.database.connection import DatabaseConnection
from src.models.leitura_item_model import LeituraItemModel
from src.models.leitura_model import LeituraModel
from src.models.parametro_model import ParametroModel


class LeituraRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__database = database or DatabaseConnection()

    def get_medicoes(
        self,
        estacao_id: int | None = None,
        municipio_id: int | None = None,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        codigos_parametro: list[str] | None = None,
    ) -> list[dict]:
        """
        Medições gravadas, uma linha por item (Leituras + Leitura_Itens + Parametros).

        Filtros opcionais: estação, município, parâmetros e período. Só
        data_inicio = aquele dia; data_inicio e data_fim = intervalo fechado.
        Ordenadas por estação, parâmetro e data/hora.
        """
        query = """
            SELECT
                E.id_estacao, E.codigo_estacao, E.nome,
                L.codigo_registro, L.data_hora,
                P.codigo_parametro, P.nome, P.unidade_medida,
                I.valor
            FROM dbo.Leitura_Itens AS I
            INNER JOIN dbo.Leituras AS L ON L.id_leitura = I.leitura_id
            INNER JOIN dbo.Parametros AS P ON P.id_parametro = I.parametro_id
            INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
            WHERE 1 = 1
        """
        params: list = []

        if estacao_id is not None:
            query += " AND L.estacao_id = ?"
            params.append(estacao_id)

        if municipio_id is not None:
            query += " AND E.municipio_id = ?"
            params.append(municipio_id)

        if data_inicio is not None and data_fim is None:
            query += " AND CAST(L.data_hora AS DATE) = ?"
            params.append(data_inicio)

        if data_inicio is not None and data_fim is not None:
            query += " AND CAST(L.data_hora AS DATE) BETWEEN ? AND ?"
            params.extend([data_inicio, data_fim])

        if codigos_parametro:
            query += f" AND P.codigo_parametro IN ({', '.join('?' * len(codigos_parametro))})"
            params.extend(codigos_parametro)

        query += " ORDER BY E.codigo_estacao, P.codigo_parametro, L.data_hora"

        return [
            {
                "estacao_id": linha[0],
                "estacao_codigo": linha[1],
                "estacao": linha[2],
                "codigo_registro": linha[3],
                "data_hora": linha[4],
                "codigo_parametro": linha[5],
                "parametro": linha[6],
                "unidade_medida": linha[7],
                "valor": float(linha[8]),
            }
            for linha in self.__database.fetch_all(query, params)
        ]

    def get_cobertura(self) -> list[dict]:
        """
        Período coberto e volume de leituras por estação (só leitura).

        Agrega no banco (MIN, MAX e COUNT) para o agente saber o período com
        dados sem carregar todas as medições. Uma linha por estação com
        leituras: [{"estacao_codigo", "primeira_leitura", "ultima_leitura", "leituras"}].
        """
        query = """
            SELECT E.codigo_estacao, MIN(L.data_hora), MAX(L.data_hora), COUNT(*)
            FROM dbo.Leituras AS L
            INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
            GROUP BY E.codigo_estacao
            ORDER BY E.codigo_estacao
        """
        return [
            {
                "estacao_codigo": linha[0],
                "primeira_leitura": linha[1],
                "ultima_leitura": linha[2],
                "leituras": int(linha[3]),
            }
            for linha in self.__database.fetch_all(query)
        ]

    def get_operadores(self) -> list[dict]:
        """
        Códigos dos operadores que registraram leituras em cada estação (só leitura).

        Só o codigo_operador, que identifica o posto de trabalho e não é dado
        pessoal. Nome e CPF (hash) e e-mail (criptografado) nunca são lidos: o
        usuário do agente nem tem permissão nessas colunas (POL-02,
        sql/seguranca/agente_usuario_leitura.sql). COUNT(L.id_leitura), e não
        COUNT(*), porque o SQL Server recusa COUNT(*) numa tabela com coluna negada.
        [{"estacao_codigo", "operador_codigo", "primeira_leitura", "ultima_leitura", "leituras"}].
        """
        query = """
            SELECT E.codigo_estacao, O.codigo_operador, MIN(L.data_hora), MAX(L.data_hora), COUNT(L.id_leitura)
            FROM dbo.Leituras AS L
            INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
            INNER JOIN dbo.Operadores AS O ON O.id_operador = L.operador_id
            GROUP BY E.codigo_estacao, O.codigo_operador
            ORDER BY E.codigo_estacao, O.codigo_operador
        """
        return [
            {
                "estacao_codigo": linha[0],
                "operador_codigo": linha[1],
                "primeira_leitura": linha[2],
                "ultima_leitura": linha[3],
                "leituras": int(linha[4]),
            }
            for linha in self.__database.fetch_all(query)
        ]

    def get_assinatura(self) -> dict:
        """
        Assinatura do conteúdo das medições gravadas (só leitura).

        Muda quando alguma medição entra, sai ou muda de valor, mas não quando a
        ingestão regrava os mesmos dados: o checksum usa codigo_registro, parâmetro
        e valor, e não id_leitura nem data_ingestao. Serve para o agente saber se o
        índice dos dias e o modelo de previsão estão em dia com o banco.
        {"medicoes", "primeira", "ultima", "checksum"}, com as datas em ISO.
        """
        query = """
            SELECT COUNT_BIG(*), MIN(L.data_hora), MAX(L.data_hora),
                   CHECKSUM_AGG(BINARY_CHECKSUM(L.codigo_registro, LI.parametro_id, LI.valor))
            FROM dbo.Leituras AS L
            INNER JOIN dbo.Leitura_Itens AS LI ON LI.leitura_id = L.id_leitura
        """
        medicoes, primeira, ultima, checksum = self.__database.fetch_all(query)[0]
        return {
            "medicoes": int(medicoes),
            "primeira": primeira.isoformat() if primeira else None,
            "ultima": ultima.isoformat() if ultima else None,
            "checksum": int(checksum) if checksum is not None else None,
        }

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
