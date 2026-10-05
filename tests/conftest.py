import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Definido antes de qualquer import de src: o .env não sobrescreve variáveis já
# existentes, então nenhum teste acessa o banco real por acidente.
os.environ["AZURE_SQL_CONNECTIONSTRING"] = "Server=nao-usar-em-testes;Database=x"
os.environ["MOCK_API"] = "http://api-de-teste"
# Chave Fernet válida usada só nos testes.
os.environ["CHAVE_CRIPTOGRAFIA"] = "4N8bS6kA2fT0yX1qV3mR9pL7cD5hJ2wE8uZ0tY4iO6g="
os.environ["PEPPER_HASH"] = "pepper-de-teste"


@pytest.fixture
def registro_bruto() -> dict:
    """Registro no formato do contrato de dados, com valores em texto."""
    return {
        "cidade_nome": " Rio de Janeiro ",
        "cidade_estado": "rj",
        "operador_codigo": "OP-RJ-01",
        "operador_nome": "Instituto Guanabara Ambiental",
        "operador_tipo": "instituto",
        "operador_ativo": "true",
        "estacao_codigo": "EST-RJ-001",
        "estacao_nome": "Estação Integrada Guanabara Norte",
        "estacao_latitude": "-22.8768",
        "estacao_longitude": "-43.1929",
        "estacao_ativa": "true",
        "estacao_tipo": "integrada",
        "data_hora": "2026-06-01T00:00:00",
        "temperatura": "20.5",
        "umidade": "84.5",
        "pressao": "1014.3",
        "precipitacao": "0.0",
        "velocidade_vento": "17.6",
        "direcao_vento": "90.0",
        "radiacao_solar": "0.0",
        "temperatura_agua": "20.8",
        "ph": "7.49",
        "oxigenio_dissolvido": "6.93",
        "condutividade": "431.3",
        "turbidez": "8.5",
        "fonte": "SIMULADO",
    }


@pytest.fixture
def registro_normalizado(registro_bruto) -> dict:
    from src.services.normalization_service import NormalizationService

    return NormalizationService().normalize([registro_bruto])[0]
