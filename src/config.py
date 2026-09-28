from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mock_api: str
    azure_sql_connectionstring: str


def load_config() -> Settings:
    """Carrega a configuração do pipeline sem expor valores sensíveis."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    connection_string = os.getenv("AZURE_SQL_CONNECTIONSTRING", "").strip()
    if not connection_string:
        raise ValueError("A variável AZURE_SQL_CONNECTIONSTRING deve estar configurada.")

    mock_api = os.getenv("MOCK_API", "").strip()
    if not mock_api:
        raise ValueError("A variável MOCK_API deve estar configurada.")

    return Settings(
        mock_api=mock_api,
        azure_sql_connectionstring=connection_string,
    )
