from pydantic import BaseModel, Field


class OperadorModel(BaseModel):
    """
    Modelo responsável por representar um Operador (tabela Operadores).

    Só recebe dados já protegidos por src/security.py: nome e CPF como hash
    SHA-256 (64 caracteres) e e-mail criptografado.
    """

    id_operador: int | None = None

    codigo_operador: str = Field(min_length=1, max_length=50)

    nome_hash: str = Field(min_length=64, max_length=64)

    cpf_hash: str = Field(min_length=64, max_length=64)

    municipio_id: int

    email_criptografado: str | None = Field(default=None, max_length=255)
