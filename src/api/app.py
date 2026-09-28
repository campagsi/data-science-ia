from fastapi import FastAPI

from .dataset_controller import DatasetController


def create_app() -> FastAPI:
    """Cria e configura a instância principal da aplicação FastAPI."""
    application = FastAPI(
        title="API de Ingestao de Dados Ambientais",
        version="1.0.0",
        description="Disponibiliza o dataset bruto para o pipeline de ingestao.",
    )
    application.include_router(DatasetController().router)

    @application.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        """Informa se a API está disponível para receber requisições."""
        return {"status": "ok"}

    return application


app = create_app()