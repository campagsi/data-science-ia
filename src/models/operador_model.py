from pydantic import BaseModel


class OperadorModel(BaseModel):
    codigo: str
    nome: str
    tipo: str
    cidade_id: int
