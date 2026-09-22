from pydantic import BaseModel


class CidadeModel(BaseModel):
    nome: str
    estado: str
