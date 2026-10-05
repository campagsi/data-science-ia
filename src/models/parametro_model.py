from pydantic import BaseModel, Field


class ParametroModel(BaseModel):
    """
    Modelo responsável por representar um parâmetro medido (tabela Parametros).

    Os tamanhos seguem o sql/ddl_banco_relacional.sql.
    """

    id_parametro: int | None = None

    codigo_parametro: str = Field(min_length=1, max_length=50)

    nome: str = Field(min_length=1, max_length=100)

    unidade_medida: str = Field(min_length=1, max_length=30)

    # None = sem limite (parâmetro novo ainda sem faixa definida).
    valor_minimo: float | None = None
    valor_maximo: float | None = None
