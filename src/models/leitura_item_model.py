from pydantic import BaseModel


class LeituraItemModel(BaseModel):
    """
    Modelo responsável por representar uma medição de uma leitura (tabela Leitura_Itens).

    Antes da gravação, a leitura é identificada por codigo_registro; o
    leitura_id só existe depois que o cabeçalho é inserido.
    """

    leitura_id: int | None = None

    codigo_registro: str

    parametro_id: int

    valor: float
