import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Definido antes de qualquer import de src: o .env não sobrescreve variáveis já
# existentes, então nenhum teste acessa o banco real por acidente.
os.environ["AZURE_SQL_CONNECTIONSTRING"] = "Server=nao-usar-em-testes;Database=x"
os.environ["FONTE_DADOS"] = "http://api-de-teste"
# Chave Fernet válida usada só nos testes.
os.environ["CHAVE_CRIPTOGRAFIA"] = "4N8bS6kA2fT0yX1qV3mR9pL7cD5hJ2wE8uZ0tY4iO6g="
os.environ["CHAVE_HASH"] = "chave-hash-de-teste"
# Logs de testes (inclusive dos subprocessos de main.py) fora de logs/, que
# guarda só os das cargas reais conferidas na fase 9.
os.environ["PASTA_LOGS"] = tempfile.mkdtemp(prefix="dsia_logs_")


_DATASET: list[dict] | None = None


def carregar_dataset() -> list[dict]:
    """Dataset servido pela API (src/api/data_set.json), lido uma vez por sessão."""
    global _DATASET
    if _DATASET is None:
        _DATASET = json.loads((RAIZ / "src" / "api" / "data_set.json").read_text(encoding="utf-8"))
    return _DATASET


@pytest.fixture(scope="session")
def dataset() -> list[dict]:
    """Dataset completo da API. Não alterar: é compartilhado na sessão."""
    return carregar_dataset()


@pytest.fixture
def registro_bruto() -> dict:
    """Primeiro registro do dataset da API, no formato do payload (cópia independente)."""
    return copy.deepcopy(carregar_dataset()[0])


@pytest.fixture
def seguranca():
    """Configura src/security.py com as chaves de teste."""
    from src.security import configurar_seguranca

    configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], os.environ["CHAVE_HASH"])


@pytest.fixture
def logs_temporarios(tmp_path):
    """
    Configura os logs numa pasta temporária e devolve uma função que lê as
    linhas de um dos arquivos ("pipeline" ou "rejeitados"), sem o cabeçalho.
    """
    import src.logger as log

    arquivos = log.configurar_logs("ingestao", tmp_path)

    def ler(nome: str) -> list[str]:
        for handler in logging.getLogger().handlers + log.logger_rejeitados.handlers:
            handler.flush()
        linhas = arquivos[nome].read_text(encoding="utf-8").splitlines()
        return [linha for linha in linhas if log.MARCADOR_CABECALHO not in linha]

    yield ler

    for alvo in (log.logger_rejeitados, logging.getLogger()):
        for handler in list(alvo.handlers):
            handler.close()
            alvo.removeHandler(handler)
