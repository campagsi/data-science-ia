import gzip
import json
from pathlib import Path
from typing import Any


class DatasetRepository:
    """Le o dataset bruto armazenado pela camada de API."""

    def __init__(self, dataset_path: Path | None = None) -> None:
        """Define o caminho do arquivo JSON que contém o dataset.

        Args:
            dataset_path: Caminho opcional para um arquivo JSON específico,
                compactado em gzip quando terminar em ``.gz``.
                Por padrão, usa ``data_set.json.gz`` no mesmo diretório deste módulo
                (compactado para caber no limite de 100 MB por arquivo do GitHub).
        """
        self.__dataset_path = dataset_path or Path(__file__).with_name("data_set.json.gz")

    def get_all(self) -> list[dict[str, Any]]:
        """Lê e valida o dataset, retornando uma lista de registros.

        Raises:
            RuntimeError: Se o arquivo não existir, contiver JSON inválido,
                for um gzip corrompido ou não representar uma lista de registros.
        """
        try:
            if self.__dataset_path.suffix == ".gz":
                dataset_file = gzip.open(self.__dataset_path, "rt", encoding="utf-8")
            else:
                dataset_file = self.__dataset_path.open(encoding="utf-8")
            with dataset_file:
                data = json.load(dataset_file)
        except FileNotFoundError as error:
            raise RuntimeError("Dataset da API nao foi encontrado.") from error
        except gzip.BadGzipFile as error:
            raise RuntimeError("Dataset da API possui gzip invalido.") from error
        except json.JSONDecodeError as error:
            raise RuntimeError("Dataset da API possui JSON invalido.") from error

        if not isinstance(data, list):
            raise RuntimeError("Dataset da API deve conter uma lista de registros.")

        return data
