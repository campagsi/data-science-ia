from pydantic import BaseModel

class Operador_Model(BaseModel):
    id: int | None = None
    codigo: str
    nome: str   
    tipo: str
    cidade_id: int
