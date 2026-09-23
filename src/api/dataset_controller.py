from typing import Any

from fastapi import APIRouter, HTTPException

from .dataset_service import DatasetService


class DatasetController:
    """Expõe as rotas HTTP do dataset."""

    def __init__(self, service: DatasetService | None = None) -> None:
        """Inicializa o controlador e registra a rota de consulta do dataset.

        Args:
            service: Serviço usado para buscar os dados. Quando não informado,
                uma instância padrão de ``DatasetService`` é criada.
        """
        self.__service = service or DatasetService()
        self.router = APIRouter(prefix="/api/v1", tags=["Dataset"])
        self.router.add_api_route(
            "/data-set",
            self.listar_dados,
            methods=["GET"],
            response_model=list[dict[str, Any]],
            summary="Retorna o dataset bruto de monitoramento",
        )

    def listar_dados(self) -> list[dict[str, Any]]:
        """Retorna o dataset bruto ou converte falhas internas em HTTP 500."""
        try:
            return self.__service.listar_dados()
        except RuntimeError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error