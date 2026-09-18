from pydantic import BaseModel

class Cidade_Model(BaseModel):
    id: int | None = None
    nome: str
    estado: str