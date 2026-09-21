from datetime import datetime

from pydantic import BaseModel, field_validator


class LeituraModel(BaseModel):
    estacao_id: int
    data_hora: datetime

    # Dados meteorológicos
    temperatura: float | None = None
    umidade: float | None = None
    pressao: float | None = None
    precipitacao: float | None = None
    velocidade_vento: float | None = None
    direcao_vento: float | None = None
    radiacao_solar: float | None = None

    # Qualidade da água
    temperatura_agua: float | None = None
    ph: float | None = None
    oxigenio_dissolvido: float | None = None
    condutividade: float | None = None
    turbidez: float | None = None

    fonte: str

    @field_validator(
        "temperatura",
        "umidade",
        "pressao",
        "precipitacao",
        "velocidade_vento",
        "direcao_vento",
        "radiacao_solar",
        "temperatura_agua",
        "ph",
        "oxigenio_dissolvido",
        "condutividade",
        "turbidez",
        mode="before",
    )
    @classmethod
    def converter_vazio_para_none(cls, valor):
        if isinstance(valor, str) and not valor.strip():
            return None

        return valor
