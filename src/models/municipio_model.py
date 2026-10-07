from pydantic import BaseModel, Field


class MunicipioModel(BaseModel):
    """
    Modelo responsável por representar um Município (tabela Municipios).
    """

    id_municipio: int | None = None

    nome: str = Field(min_length=1, max_length=150)

    estado_id: int
