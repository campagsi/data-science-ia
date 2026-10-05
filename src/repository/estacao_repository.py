from src.database.connection import DatabaseConnection
from src.models.estacao_model import EstacaoModel


class EstacaoRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__database = database or DatabaseConnection()

    def get_all(self) -> list[EstacaoModel]:
        """Retorna todas as estações cadastradas."""
        query = """
            SELECT id_estacao, codigo_estacao, nome, municipio_id, latitude, longitude
            FROM dbo.Estacoes
        """
        return [
            EstacaoModel(
                id_estacao=linha[0],
                codigo_estacao=linha[1],
                nome=linha[2],
                municipio_id=linha[3],
                latitude=float(linha[4]),
                longitude=float(linha[5]),
            )
            for linha in self.__database.fetch_all(query)
        ]

    # Legado da Parte 1: consulta o modelo antigo e só é usada pela análise
    # (src/services/analytics_service.py), que será adaptada ao modelo 3FN.
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

    def merge_many(self, estacoes: list[EstacaoModel]) -> int:
        """
        Insere ou atualiza estações pela chave natural codigo_estacao.

        Idempotente: reexecutar não duplica; nome, município e coordenadas são
        atualizados para os valores do lote.
        """
        if not estacoes:
            return 0

        query = """
            MERGE dbo.Estacoes AS destino
            USING (SELECT ? AS codigo_estacao, ? AS nome, ? AS municipio_id,
                          ? AS latitude, ? AS longitude) AS origem
            ON destino.codigo_estacao = origem.codigo_estacao
            WHEN MATCHED THEN
                UPDATE SET
                    nome = origem.nome,
                    municipio_id = origem.municipio_id,
                    latitude = origem.latitude,
                    longitude = origem.longitude
            WHEN NOT MATCHED BY TARGET THEN
                INSERT (codigo_estacao, nome, municipio_id, latitude, longitude)
                VALUES (origem.codigo_estacao, origem.nome, origem.municipio_id,
                        origem.latitude, origem.longitude);
        """
        params = [
            (
                estacao.codigo_estacao,
                estacao.nome,
                estacao.municipio_id,
                estacao.latitude,
                estacao.longitude,
            )
            for estacao in estacoes
        ]
        return self.__database.execute_many(query, params)

    def insert_estacao(self, estacoes: list[EstacaoModel]):
        """Método-ponte para a operação de gravação de estações."""
        return self.merge_many(estacoes)
