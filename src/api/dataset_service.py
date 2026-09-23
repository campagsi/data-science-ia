from typing import Any

from .dataset_repository import DatasetRepository


class DatasetService:
    """Coordena o acesso ao dataset disponibilizado pela API."""

    def __init__(self, repository: DatasetRepository | None = None) -> None:
        """Inicializa o serviço com o repositório responsável pelos dados.

        Args:
            repository: Repositório usado na leitura. Se omitido, o repositório
                padrão do dataset da API é criado.
        """
        self.__repository = repository or DatasetRepository()

    def listar_dados(self) -> list[dict[str, Any]]:
        """Solicita ao repositório todos os registros do dataset."""
        return self.__repository.get_all()