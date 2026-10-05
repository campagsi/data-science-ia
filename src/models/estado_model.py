from pydantic import BaseModel, Field


class EstadoModel(BaseModel):
    """
    Modelo responsável por representar um Estado.
    """

    id_estado: int | None = None

    sigla: str = Field(
        min_length=2,
        max_length=2
    )

    nome: str = Field(
        min_length=2,
        max_length=100
    )
