"""
Contrato do banco vetorial: os MESMOS testes rodam contra a memória (numpy) e o ChromaDB.

Teste de contrato = a interface promete um comportamento, e toda implementação
precisa cumpri-lo. Se um teste passar na memória e falhar no Chroma, o Chroma
não pode substituir a memória sem mudar o resto do agente.

Aceite da Fase 5: com o índice da documentação real, os dois bancos devolvem os
mesmos ids no top-4, embora o Chroma use um índice APROXIMADO (HNSW) e a memória
faça a busca exata.
"""
import os
from pathlib import Path

import numpy as np
import pytest

from src.agente.fabrica import recuperador_da_documentacao
from src.agente.rag.embeddings import EmbedderSimulado, normalizar
from src.agente.rag.indexador import indexar
from src.agente.rag.recuperador import Recuperador
from src.agente.rag.vector_store import TIPOS, RegistroIndice, abrir_indice, novo_indice
from src.config import ConfigAgente

RAIZ = Path(__file__).resolve().parents[3]
PERGUNTAS = [
    "por que a chuva gera tantos alertas IQR?",
    "o que significa o alerta IQR+ZSCORE?",
    "como o CPF do operador é protegido?",
    "como rodar a ingestão no banco",
    "qual a faixa válida do oxigênio dissolvido?",
    "o agente pode gravar no banco?",
    "idempotência da carga de leituras",
    "limiar de similaridade do RAG",
]


@pytest.fixture(params=TIPOS)
def tipo(request):
    """Cada teste do contrato roda uma vez por banco vetorial."""
    return request.param


def tres(tipo: str, pasta: Path):
    """Banco do tipo com três trechos em direções conhecidas."""
    store = novo_indice(tipo, pasta, "m", 3)
    store.inserir([RegistroIndice(i, f"{i}.md", "S", f"texto {i}") for i in ("a", "b", "c")], np.eye(3))
    return store


def test_contrato_busca_em_ordem_com_similaridade_de_cosseno(tipo, tmp_path):
    resultado = tres(tipo, tmp_path).buscar(normalizar(np.array([0.1, 0.9, 0.3]))[0], 2)

    assert [t.id for t in resultado] == ["b", "c"]
    assert resultado[0].similaridade == pytest.approx(0.9 / np.linalg.norm([0.1, 0.9, 0.3]), abs=1e-4)
    assert (resultado[0].arquivo, resultado[0].secao, resultado[0].texto) == ("b.md", "S", "texto b")


def test_contrato_ids_remover_e_tamanho(tipo, tmp_path):
    store = tres(tipo, tmp_path)

    store.remover({"b", "inexistente"})

    assert (store.ids(), len(store)) == ({"a", "c"}, 2)


def test_contrato_persistencia(tipo, tmp_path):
    tres(tipo, tmp_path).persistir()

    reaberto = abrir_indice(tipo, tmp_path)

    assert (reaberto.ids(), reaberto.modelo, reaberto.dimensoes) == ({"a", "b", "c"}, "m", 3)


def test_contrato_vazio_e_dimensao_errada(tipo, tmp_path):
    store = novo_indice(tipo, tmp_path, "m", 3)

    assert store.buscar(np.array([1.0, 0.0, 0.0]), 4) == []
    with pytest.raises(ValueError, match="esperava vetores"):
        store.inserir([RegistroIndice("a", "x", "S", "t")], np.ones((1, 4)))


def test_contrato_top_k_maior_que_o_indice(tipo, tmp_path):
    assert len(tres(tipo, tmp_path).buscar(np.array([1.0, 0.0, 0.0]), 10)) == 3


def test_contrato_indice_ausente(tipo, tmp_path):
    assert abrir_indice(tipo, tmp_path) is None


def test_tipo_desconhecido(tmp_path):
    with pytest.raises(ValueError, match="pinecone"):
        abrir_indice("pinecone", tmp_path)


# --- Indexação nos dois bancos ---------------------------------------------------------


def test_indexacao_idempotente_e_troca_de_modelo(tipo, tmp_path_factory):
    pasta = tmp_path_factory.mktemp(f"indice_{tipo}")

    primeira = indexar(EmbedderSimulado(), pasta, RAIZ, vetores=tipo)
    segunda = indexar(EmbedderSimulado(), pasta, RAIZ, vetores=tipo)
    outro_modelo = indexar(EmbedderSimulado(128), pasta, RAIZ, vetores=tipo)

    assert primeira.inseridos == primeira.chunks > 100
    assert (segunda.inseridos, segunda.removidos) == (0, 0)
    assert (outro_modelo.inseridos, outro_modelo.mantidos) == (outro_modelo.chunks, 0)
    assert abrir_indice(tipo, pasta).modelo == "simulado-hashing-128"


@pytest.fixture(scope="module")
def indices_da_documentacao(tmp_path_factory):
    """A documentação real indexada nos dois bancos, com o mesmo embedder."""
    pasta = {tipo: tmp_path_factory.mktemp(f"docs_{tipo}") for tipo in TIPOS}
    for tipo, destino in pasta.items():
        indexar(EmbedderSimulado(), destino, RAIZ, vetores=tipo)
    return {tipo: abrir_indice(tipo, destino) for tipo, destino in pasta.items()}


@pytest.mark.parametrize("pergunta", PERGUNTAS)
def test_aceite_memoria_e_chroma_devolvem_o_mesmo_top4(indices_da_documentacao, pergunta):
    vetor = EmbedderSimulado().vetorizar_consulta(pergunta)

    memoria = indices_da_documentacao["memoria"].buscar(vetor, 4)
    chroma = indices_da_documentacao["chroma"].buscar(vetor, 4)

    assert [t.id for t in chroma] == [t.id for t in memoria]
    assert [t.similaridade for t in chroma] == pytest.approx([t.similaridade for t in memoria], abs=1e-4)


def test_recuperador_e_fabrica_com_o_chroma(indices_da_documentacao, tmp_path):
    chroma = indices_da_documentacao["chroma"]
    trechos = Recuperador(EmbedderSimulado(), chroma, limiar=0.1).buscar("limitação da regra IQR na precipitação", 1)
    indexar(EmbedderSimulado(), tmp_path, RAIZ, vetores="chroma")

    cfg = ConfigAgente("anthropic", dir_indice=tmp_path, vetores="chroma", embeddings_modelo="simulado-hashing-256")

    assert trechos[0].arquivo == "docs/analise-estatistica.md"
    assert recuperador_da_documentacao(cfg) is not None


@pytest.mark.skipif(os.getenv("AGENTE_TESTAR_EMBEDDINGS_REAIS") != "1", reason="usa o modelo real; AGENTE_TESTAR_EMBEDDINGS_REAIS=1")
def test_aceite_com_o_modelo_real(tmp_path_factory):
    from src.agente.rag.embeddings import EmbedderFastembed

    embedder = EmbedderFastembed(pasta_cache=RAIZ / "data" / "agente" / "modelos")
    indices = {}
    for tipo in TIPOS:
        pasta = tmp_path_factory.mktemp(f"real_{tipo}")
        indexar(embedder, pasta, RAIZ, vetores=tipo)
        indices[tipo] = abrir_indice(tipo, pasta)

    for pergunta in PERGUNTAS:
        vetor = embedder.vetorizar_consulta(pergunta)
        assert [t.id for t in indices["chroma"].buscar(vetor, 4)] == [t.id for t in indices["memoria"].buscar(vetor, 4)], pergunta
