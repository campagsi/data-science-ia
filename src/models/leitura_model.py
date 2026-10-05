from datetime import datetime

from pydantic import BaseModel, Field


class LeituraModel(BaseModel):
    """
    Modelo responsável por representar o cabeçalho de uma leitura (tabela Leituras).

    As medições ficam em LeituraItemModel (tabela Leitura_Itens).
    """

    id_leitura: int | None = None

    codigo_registro: str = Field(min_length=1, max_length=50)

    operador_id: int

    estacao_id: int

    data_hora: datetime

    fonte: str = Field(min_length=1, max_length=100)
