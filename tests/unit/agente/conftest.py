"""Fixtures das ferramentas do agente, sobre os dados falsos de dados_falsos_agente.py."""
from datetime import date

import pytest

from dados_falsos_agente import montar_consulta
from src.agente.dias.indice import abrir_busca_de_dias, indexar_dias
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.ferramentas.consulta_dados import FiltroMedicoes
from src.agente.rag.embeddings import EmbedderSimulado
from src.agente.rag.indexador import indexar
from src.agente.rag.recuperador import Recuperador
from src.agente.rag.vector_store import VectorStoreMemoria
from src.previsao.persistencia import ModeloPrevisao


@pytest.fixture
def consulta():
    """ConsultaDados de uma estação com os dados falsos."""
    return montar_consulta()[0]


@pytest.fixture
def registro(consulta):
    """Catálogo completo de ferramentas sobre os dados falsos."""
    return criar_registro(consulta, max_linhas=50)


@pytest.fixture
def junho():
    """Período com dados (01 a 03/06/2026)."""
    return {"data_inicio": date(2026, 6, 1).isoformat(), "data_fim": date(2026, 6, 3).isoformat()}


@pytest.fixture(scope="session")
def pasta_indice(tmp_path_factory):
    """Índice da documentação real do projeto, criado uma vez com o embedder simulado (sem download)."""
    pasta = tmp_path_factory.mktemp("indice_docs")
    indexar(EmbedderSimulado(), pasta)
    return pasta


@pytest.fixture
def recuperador(pasta_indice):
    """Recuperador sobre o índice simulado (limiar baixo: o hashing tem outra escala de similaridade)."""
    return Recuperador(EmbedderSimulado(), VectorStoreMemoria.carregar(pasta_indice), limiar=0.1)


@pytest.fixture
def busca_dias(consulta, tmp_path):
    """Índice dos dias dos dados falsos (01 a 03/06), com o embedder simulado."""
    indexar_dias(consulta.medicoes(FiltroMedicoes()), EmbedderSimulado(), tmp_path)
    return abrir_busca_de_dias(EmbedderSimulado(), tmp_path)


class PrevisorFixo:
    """Pipeline falso: sempre prevê 25,0 (os testes da ferramenta não dependem do treino)."""

    def predict(self, X):
        """Uma previsão por linha."""
        return [25.0] * len(X)


@pytest.fixture
def modelo_previsao():
    """Modelo de previsão falso: TIP-TMP da EST-1 aprovado em 6 h e reprovado em 1 h."""
    metricas = {"modelo": {"mae": 0.62, "rmse": 0.81}, "ingenuo": {"mae": 2.1, "rmse": 2.6}, "ingenuo_sazonal": {"mae": 0.95, "rmse": 1.22}}
    reprovado = {"modelo": {"mae": 0.31, "rmse": 0.4}, "ingenuo": {"mae": 0.29, "rmse": 0.38}, "ingenuo_sazonal": {"mae": 0.95, "rmse": 1.22}}
    base = {"estacao": "EST-1", "parametro": "TIP-TMP", "modelo": "Ridge", "periodo": ["2026-06-01T00:00:00", "2026-06-03T23:30:00"]}
    return ModeloPrevisao(
        {"EST-1|TIP-TMP|6": PrevisorFixo()},
        {"criado_em": "2026-10-21T10:00:00", "avaliacoes": {
            "EST-1|TIP-TMP|6": {**base, "horas": 6, "aprovado": True, "validacao": metricas, "teste": metricas},
            "EST-1|TIP-TMP|1": {**base, "horas": 1, "aprovado": False, "validacao": reprovado, "teste": reprovado},
        }},
    )


@pytest.fixture
def registro_completo(consulta, recuperador, busca_dias, modelo_previsao):
    """Catálogo com todas as ferramentas: as de dados, buscar_documentacao, dias_semelhantes e prever."""
    return criar_registro(consulta, max_linhas=50, recuperador=recuperador, dias=busca_dias, modelo_previsao=modelo_previsao)
