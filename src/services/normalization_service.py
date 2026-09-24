from datetime import datetime
from typing import Any


class NormalizationService:
    _TEXT_FIELDS = (
        "cidade_nome",
        "cidade_estado",
        "operador_codigo",
        "operador_nome",
        "operador_tipo",
        "estacao_codigo",
        "estacao_nome",
        "estacao_tipo",
        "fonte",
    )
    _FLOAT_FIELDS = (
        "estacao_latitude",
        "estacao_longitude",
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
    )

    def normalize(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Padroniza os campos sem alterar o payload recebido."""
        normalized_data = []
        for index, record in enumerate(raw_data):
            normalized = dict(record)

            for field in self._TEXT_FIELDS:
                if field in normalized and normalized[field] is not None:
                    normalized[field] = str(normalized[field]).strip()

            for field in self._FLOAT_FIELDS:
                if field in normalized and normalized[field] not in (None, ""):
                    try:
                        normalized[field] = float(normalized[field])
                    except (TypeError, ValueError) as error:
                        raise ValueError(
                            f"Registro {index}: campo {field} deve ser numérico."
                        ) from error

            for field in ("operador_ativo", "estacao_ativa"):
                if field in normalized:
                    normalized[field] = self.__normalize_bool(normalized[field], index, field)

            if "data_hora" in normalized:
                try:
                    normalized["data_hora"] = datetime.fromisoformat(
                        str(normalized["data_hora"]).strip()
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Registro {index}: campo data_hora deve ser uma data ISO válida."
                    ) from error

            if "cidade_estado" in normalized:
                normalized["cidade_estado"] = normalized["cidade_estado"].upper()

            normalized_data.append(normalized)

        return normalized_data

    @staticmethod
    def __normalize_bool(value: Any, index: int, field: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "1", "sim"}:
            return True
        if isinstance(value, str) and value.strip().lower() in {"false", "0", "nao", "não"}:
            return False
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise ValueError(f"Registro {index}: campo {field} deve ser booleano.")
