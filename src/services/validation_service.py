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
        "estacao_codigo",
        "estacao_nome",
        "estacao_tipo",
        "data_hora",
        "fonte",
    )

    def validate_data(self, normalized_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Valida o lote inteiro antes de permitir qualquer persistência."""
        validated_data = []
        errors = []

        for index, record in enumerate(normalized_data):
            try:
                self.__validate_required_fields(record, index)
                self.__validate_models(record)
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
            if field not in record or record[field] in (None, "")
        ]
        if missing:
            raise ValueError(f"campos obrigatórios ausentes: {', '.join(missing)}")

        for field in ("estacao_latitude", "estacao_longitude"):
            if field not in record:
                raise ValueError(f"campo obrigatório ausente: {field}")

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
