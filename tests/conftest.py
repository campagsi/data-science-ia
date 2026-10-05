import copy
import json
import logging
import os
import sys
from datetime import datetime
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
os.environ["PEPPER_HASH"] = "pepper-de-teste"


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

    configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], os.environ["PEPPER_HASH"])


@pytest.fixture
def logs_temporarios(tmp_path):
    """
    Configura os logs numa pasta temporária e devolve uma função que lê as
    linhas de um dos arquivos ("pipeline" ou "rejeitados").
    """
    import src.logger as log

    arquivos = log.configurar_logs(tmp_path)

    def ler(nome: str) -> list[str]:
        for handler in logging.getLogger().handlers + log.logger_rejeitados.handlers:
            handler.flush()
        return arquivos[nome].read_text(encoding="utf-8").splitlines()

    yield ler

    for alvo in (log.logger_rejeitados, logging.getLogger()):
        for handler in list(alvo.handlers):
            handler.close()
            alvo.removeHandler(handler)


@pytest.fixture
def registro_legado() -> dict:
    """
    Registro no formato normalizado da Parte 1 (modelo antigo, com uma chave
    por medição). Usado só por tests/integration/test_persistencia.py, que está
    pulado até a reescrita nas fases 8 e 10 de docs/todo-idempotencia.md.
    """
    return {
        "cidade_nome": "Rio de Janeiro",
        "cidade_estado": "RJ",
        "operador_codigo": "OP-RJ-01",
        "operador_nome": "Instituto Guanabara Ambiental",
        "operador_tipo": "instituto",
        "operador_ativo": True,
        "estacao_codigo": "EST-RJ-001",
        "estacao_nome": "Estação Integrada Guanabara Norte",
        "estacao_latitude": -22.8768,
        "estacao_longitude": -43.1929,
        "estacao_ativa": True,
        "estacao_tipo": "integrada",
        "data_hora": datetime(2026, 6, 1, 0, 0),
        "temperatura": 20.5,
        "umidade": 84.5,
        "pressao": 1014.3,
        "precipitacao": 0.0,
        "velocidade_vento": 17.6,
        "direcao_vento": 90.0,
        "radiacao_solar": 0.0,
        "temperatura_agua": 20.8,
        "ph": 7.49,
        "oxigenio_dissolvido": 6.93,
        "condutividade": 431.3,
        "turbidez": 8.5,
        "fonte": "SIMULADO",
    }
