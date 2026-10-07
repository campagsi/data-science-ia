from src.database.connection import DatabaseConnection
from src.models.operador_model import OperadorModel


class OperadorRepository:

    def __init__(
        self,
        database: DatabaseConnection | None = None
    ) -> None:
        self.__database = database or DatabaseConnection()

    def get_all(
        self
    ) -> list[OperadorModel]:
        """
        Retorna todos os operadores cadastrados (somente dados já anonimizados).
        """

        query = """
            SELECT id_operador, codigo_operador, nome_hash, cpf_hash,
                   municipio_id, email_criptografado
            FROM dbo.Operadores
        """

        return [
            OperadorModel(
                id_operador=linha[0],
                codigo_operador=linha[1],
                nome_hash=linha[2],
                cpf_hash=linha[3],
                municipio_id=linha[4],
                email_criptografado=linha[5],
            )
            for linha in self.__database.fetch_all(query)
        ]

    def merge_many(
        self,
        operadores: list[OperadorModel]
    ) -> int:
        """
        Insere ou atualiza operadores pela chave natural codigo_operador.

        Idempotente: reexecutar não duplica. O e-mail criptografado é sempre
        regravado, porque o token Fernet muda a cada criptografia.
        """

        if not operadores:
            return 0

        query = """
            MERGE dbo.Operadores AS destino
            USING (SELECT ? AS codigo_operador, ? AS nome_hash, ? AS cpf_hash,
                          ? AS municipio_id, ? AS email_criptografado) AS origem
            ON destino.codigo_operador = origem.codigo_operador
            WHEN MATCHED THEN
                UPDATE SET
                    nome_hash = origem.nome_hash,
                    cpf_hash = origem.cpf_hash,
                    municipio_id = origem.municipio_id,
                    email_criptografado = origem.email_criptografado
            WHEN NOT MATCHED BY TARGET THEN
                INSERT (codigo_operador, nome_hash, cpf_hash, municipio_id, email_criptografado)
                VALUES (origem.codigo_operador, origem.nome_hash, origem.cpf_hash,
                        origem.municipio_id, origem.email_criptografado);
        """

        return self.__database.execute_many(
            query,
            [
                (
                    operador.codigo_operador,
                    operador.nome_hash,
                    operador.cpf_hash,
                    operador.municipio_id,
                    operador.email_criptografado,
                )
                for operador in operadores
            ]
        )
