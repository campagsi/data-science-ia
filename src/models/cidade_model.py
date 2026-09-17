from pydantic import BaseModel

class Cidade_Model(BaseModel):
    id: int
    nome: str
    estado: str