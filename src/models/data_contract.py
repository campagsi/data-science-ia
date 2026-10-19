from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class DataContract(BaseModel):
    # ======= Rejeitar Registro ========
    registro_codigo: str
    cidade_codigo: str
    estacao_codigo: str
    operador_codigo: str
    estacao_latitude: float
    estacao_longitude: float
    data_hora_ciclo: datetime
    cidade_estado: str

    # =================================
    temperatura_agua: float | None
    data_hora_leitura_temperatura_agua: datetime | None

    ph: float | None
    data_hora_leitura_ph: datetime | None

    oxigenio_dissolvido: float | None
    data_hora_leitura_oxigenio_dissolvido: datetime | None

    condutividade: float | None
    data_hora_leitura_condutividade: datetime | None

    turbidez: float | None
    data_hora_leitura_turbidez: datetime | None

    temperatura: float | None
    data_hora_leitura_temperatura: datetime | None

    umidade: float | None
    data_hora_leitura_umidade: datetime | None

    pressao: float | None
    data_hora_leitura_pressao: datetime | None

    precipitacao: float | None
    data_hora_leitura_precipitacao: datetime | None

    velocidade_vento: float | None
    data_hora_leitura_velocidade_vento: datetime | None

    radiacao_solar: float | None
    data_hora_leitura_radiacao_solar: datetime | None

    municipio: str | None
    estacao_nome: str | None
    estacao_ativa: bool | None
    estacao_tipo: str | None
    operador_nome_completo: str | None
    operador_cpf: str | None
    operador_email: str | None
    operador_ativo: bool | None

    temperatura_agua_unidade_medida: str | None
    temperatura_agua_codigo: str | None
    temperatura_agua_tipo_codigo: str | None
    ph_unidade_medida: str | None
    ph_codigo: str | None
    ph_tipo_codigo: str | None
    temperatura_unidade_medida: str | None
    temperatura_codigo: str | None
    temperatura_tipo_codigo: str | None
    umidade_unidade_medida: str | None
    umidade_codigo: str | None
    umidade_tipo_codigo: str | None
    pressao_unidade_medida: str | None
    pressao_codigo: str | None
    pressao_tipo_codigo: str | None
    precipitacao_unidade_medida: str | None
    precipitacao_codigo: str | None
    precipitacao_tipo_codigo: str | None
    velocidade_unidade_medida: str | None
    velocidade_codigo: str | None
    velocidade_vento_tipo_codigo: str | None
    radiacao_solar_unidade_medida: str | None
    radiacao_solar_codigo: str | None
    radiacao_solar_tipo_codigo: str | None
    oxigenio_dissolvido_medida: str | None
    oxigenio_dissolvido_tipo_codigo: str | None
    condutividade_unidade_medida: str | None
    condutividade_codigo: str | None
    turbidez_unidade_medida: str | None
    turbidez_codigo: str | None
    turbidez_tipo_codigo: str | None
    oxigenio_dissolvido_codigo: str | None
    condutividade_tipo_codigo: str | None
