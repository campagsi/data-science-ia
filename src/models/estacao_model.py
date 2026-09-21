from pydantic import BaseModel


class EstacaoModel(BaseModel):
    codigo: str
    nome: str
    cidade_id: int
    operador_id: int
    latitude: float
    longitude: float
    ativa: bool
    tipo: str
