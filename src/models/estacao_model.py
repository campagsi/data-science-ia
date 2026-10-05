from pydantic import BaseModel, Field


class EstacaoModel(BaseModel):
    """
    Modelo responsável por representar uma Estação (tabela Estacoes).
    """

    id_estacao: int | None = None

    codigo_estacao: str = Field(min_length=1, max_length=50)

    nome: str = Field(min_length=1, max_length=150)

    municipio_id: int

    latitude: float = Field(ge=-90, le=90)

    longitude: float = Field(ge=-180, le=180)
