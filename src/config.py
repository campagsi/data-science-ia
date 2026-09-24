from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mock_api: str | None
    azure_sql_connectionstring: str
    dataset_path: Path


def load_config() -> Settings:
    """Carrega a configuração do pipeline sem expor valores sensíveis."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    connection_string = os.getenv("AZURE_SQL_CONNECTIONSTRING", "").strip()
    if not connection_string:
        raise ValueError("A variável AZURE_SQL_CONNECTIONSTRING deve estar configurada.")

    mock_api = os.getenv("MOCK_API", "").strip() or None
    dataset_path = Path(__file__).resolve().parent / "api" / "data_set.json"

    return Settings(
        mock_api=mock_api,
        azure_sql_connectionstring=connection_string,
        dataset_path=dataset_path,
    )
