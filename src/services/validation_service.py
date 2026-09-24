import math
from typing import Any

from pydantic import ValidationError

from src.models import CidadeModel, EstacaoModel, LeituraModel, OperadorModel


class ValidationService:
    _REQUIRED_FIELDS = (
        "cidade_nome",
        "cidade_estado",
        "operador_codigo",
        "operador_nome",
        "operador_tipo",
        "operador_ativo",
        "estacao_codigo",
        "estacao_nome",
        "estacao_latitude",
        "estacao_longitude",
        "estacao_ativa",
        "estacao_tipo",
        "data_hora",
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
        "fonte",
    )

    def validate_data(self, normalized_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Valida o lote inteiro antes de permitir qualquer persistência."""
        validated_data = []
        errors = []
        operator_codes = {}
        station_codes = {}

        for index, record in enumerate(normalized_data):
            try:
                self.__validate_required_fields(record, index)
                self.__validate_models(record)
                self.__validate_ranges(record)
                self.__validate_batch_uniqueness(
                    record, operator_codes, station_codes
                )
                validated_data.append(dict(record))
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                errors.append(f"Registro {index}: {error}")

        if errors:
            raise ValueError("Lote inválido: " + "; ".join(errors))

        return validated_data

    def validar_estacao(self, registro: dict[str, Any]) -> EstacaoModel:
        """Cria e valida uma estação com os identificadores resolvidos depois."""
        return EstacaoModel(
            codigo=registro["estacao_codigo"],
            nome=registro["estacao_nome"],
            cidade_id=registro.get("cidade_id", 0),
            operador_id=registro.get("operador_id", 0),
            latitude=registro["estacao_latitude"],
            longitude=registro["estacao_longitude"],
            ativa=registro["estacao_ativa"],
            tipo=registro["estacao_tipo"],
        )

    def validar_leitura(
        self, registro: dict[str, Any], estacao_id: int = 0
    ) -> LeituraModel:
        """Cria e valida uma leitura associada à estação informada."""
        fields = {
            field: registro.get(field)
            for field in LeituraModel.model_fields
            if field in registro
        }
        fields["estacao_id"] = estacao_id
        return LeituraModel(**fields)

    def __validate_required_fields(self, record: dict[str, Any], index: int) -> None:
        missing = [
            field
            for field in self._REQUIRED_FIELDS
            if field not in record
            or record[field] is None
            or (isinstance(record[field], str) and not record[field].strip())
        ]
        if missing:
            raise ValueError(f"campos obrigatórios ausentes: {', '.join(missing)}")

        if not isinstance(record["cidade_estado"], str):
            raise ValueError("cidade_estado deve ser uma sigla de duas letras.")
        if len(record["cidade_estado"]) != 2 or not record["cidade_estado"].isalpha():
            raise ValueError("cidade_estado deve ser uma sigla de duas letras.")

    def __validate_ranges(self, record: dict[str, Any]) -> None:
        ranges = {
            "estacao_latitude": (-90, 90),
            "estacao_longitude": (-180, 180),
            "umidade": (0, 100),
            "direcao_vento": (0, 360),
            "ph": (0, 14),
        }
        non_negative_fields = (
            "precipitacao",
            "radiacao_solar",
            "oxigenio_dissolvido",
            "condutividade",
            "turbidez",
        )

        for field, (minimum, maximum) in ranges.items():
            value = record[field]
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{field} deve ser numérico e finito.")
            if not minimum <= value <= maximum:
                raise ValueError(f"{field} deve estar entre {minimum} e {maximum}.")

        for field in non_negative_fields:
            value = record[field]
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{field} deve ser numérico e finito.")
            if value < 0:
                raise ValueError(f"{field} não pode ser negativo.")

    @staticmethod
    def __validate_batch_uniqueness(
        record: dict[str, Any], operator_codes: dict, station_codes: dict
    ) -> None:
        operator_code = record["operador_codigo"]
        station_code = record["estacao_codigo"]
        operator_identity = (
            record["operador_nome"],
            record["operador_tipo"],
            record["cidade_nome"],
        )
        station_identity = (
            record["estacao_nome"],
            record["estacao_latitude"],
            record["estacao_longitude"],
            record["cidade_nome"],
            record["operador_codigo"],
        )

        if operator_code in operator_codes and operator_codes[operator_code] != operator_identity:
            raise ValueError(f"operador_codigo duplicado no lote: {operator_code}.")
        if station_code in station_codes and station_codes[station_code] != station_identity:
            raise ValueError(f"estacao_codigo duplicado no lote: {station_code}.")

        operator_codes[operator_code] = operator_identity
        station_codes[station_code] = station_identity

    def __validate_models(self, record: dict[str, Any]) -> None:
        CidadeModel(nome=record["cidade_nome"], estado=record["cidade_estado"])
        OperadorModel(
            codigo=record["operador_codigo"],
            nome=record["operador_nome"],
            tipo=record["operador_tipo"],
            cidade_id=0,
        )
        self.validar_estacao(record)
        self.validar_leitura(record)
