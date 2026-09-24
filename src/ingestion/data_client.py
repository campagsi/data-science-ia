import json
from pathlib import Path
from typing import Any

import requests

from src.config import Settings


class DataClient:
    def __init__(self, settings: Settings):
        self.__settings = settings

    def fetch_data(self) -> list[dict[str, Any]]:
        """Obtém o dataset da API configurada ou do arquivo local."""
        if self.__settings.mock_api:
            response = requests.get(
                f"{self.__settings.mock_api.rstrip('/')}/api/v1/data-set",
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        else:
            data = self.__read_local_dataset(self.__settings.dataset_path)

        if not isinstance(data, list):
            raise ValueError("A fonte de dados deve devolver uma lista de registros.")

        if not all(isinstance(record, dict) for record in data):
            raise ValueError("Todos os registros da fonte devem ser objetos JSON.")

        return data

    @staticmethod
    def __read_local_dataset(dataset_path: Path) -> Any:
        try:
            with dataset_path.open(encoding="utf-8") as dataset_file:
                return json.load(dataset_file)
        except OSError as error:
            raise RuntimeError("Não foi possível ler o dataset local.") from error
        except json.JSONDecodeError as error:
            raise ValueError("O dataset local não contém JSON válido.") from error
