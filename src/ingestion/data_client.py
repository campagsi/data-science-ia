from typing import Any

import requests

from src.config import Settings


class DataClient:
    def __init__(self, settings: Settings):
        self.__settings = settings

    def fetch_data(self) -> list[dict[str, Any]]:
        """Obtém o dataset exclusivamente pela API configurada."""
        response = requests.get(
            f"{self.__settings.fonte_dados.rstrip('/')}/api/v1/data-set",
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            raise ValueError("A fonte de dados deve devolver uma lista de registros.")

        if not all(isinstance(record, dict) for record in data):
            raise ValueError("Todos os registros da fonte devem ser objetos JSON.")

        return data

