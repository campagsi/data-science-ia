from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

FONTE_DADOS_PADRAO = "API_MOCK"


@dataclass(frozen=True)
class Settings:
    mock_api: str
    azure_sql_connectionstring: str
    chave_criptografia: str = ""
    pepper_hash: str = ""
    fonte_dados: str = FONTE_DADOS_PADRAO


def load_config() -> Settings:
    """Carrega a configuração do pipeline sem expor valores sensíveis."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    connection_string = os.getenv("AZURE_SQL_CONNECTIONSTRING", "").strip()
    if not connection_string:
        raise ValueError("A variável AZURE_SQL_CONNECTIONSTRING deve estar configurada.")

    mock_api = os.getenv("MOCK_API", "").strip()
    if not mock_api:
        raise ValueError("A variável MOCK_API deve estar configurada.")

    chave_criptografia = os.getenv("CHAVE_CRIPTOGRAFIA", "").strip()
    if not chave_criptografia:
        raise ValueError("A variável CHAVE_CRIPTOGRAFIA deve estar configurada.")

    return Settings(
        mock_api=mock_api,
        azure_sql_connectionstring=connection_string,
        chave_criptografia=chave_criptografia,
        # Opcional: sem pepper, o hash é SHA-256 puro (decisão D8).
        pepper_hash=os.getenv("PEPPER_HASH", "").strip(),
        fonte_dados=os.getenv("FONTE_DADOS", "").strip() or FONTE_DADOS_PADRAO,
    )
