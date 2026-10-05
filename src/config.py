from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

# Leituras.fonte é VARCHAR(100) no sql/ddl_banco_relacional.sql.
TAMANHO_MAXIMO_FONTE = 100


@dataclass(frozen=True)
class Settings:
    # URL da API de ingestão; também é o valor gravado em Leituras.fonte.
    fonte_dados: str
    azure_sql_connectionstring: str
    chave_criptografia: str = ""
    pepper_hash: str = ""


def load_config() -> Settings:
    """Carrega a configuração do pipeline sem expor valores sensíveis."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    connection_string = os.getenv("AZURE_SQL_CONNECTIONSTRING", "").strip()
    if not connection_string:
        raise ValueError("A variável AZURE_SQL_CONNECTIONSTRING deve estar configurada.")

    fonte_dados = os.getenv("FONTE_DADOS", "").strip()
    if not fonte_dados:
        raise ValueError("A variável FONTE_DADOS deve estar configurada.")
    if len(fonte_dados) > TAMANHO_MAXIMO_FONTE:
        raise ValueError(
            f"A variável FONTE_DADOS deve ter no máximo {TAMANHO_MAXIMO_FONTE} caracteres."
        )

    chave_criptografia = os.getenv("CHAVE_CRIPTOGRAFIA", "").strip()
    if not chave_criptografia:
        raise ValueError("A variável CHAVE_CRIPTOGRAFIA deve estar configurada.")

    return Settings(
        fonte_dados=fonte_dados,
        azure_sql_connectionstring=connection_string,
        chave_criptografia=chave_criptografia,
        # Opcional: sem pepper, o hash é SHA-256 puro (decisão D8).
        pepper_hash=os.getenv("PEPPER_HASH", "").strip(),
    )
