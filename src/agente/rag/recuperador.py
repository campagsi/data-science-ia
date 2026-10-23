"""
Recuperação: a etapa "R" do RAG (Retrieval-Augmented Generation).

Conceito
--------
RAG = buscar trechos relevantes da documentação e entregá-los ao LLM, para ele
explicar com base NELES (grounding), e não no que "acha" que sabe.

    consulta do LLM → embedding da consulta → busca top_k × 2 candidatos
    → descarta abaixo do limiar → 1 trecho por seção → top_k finais

- top_k: quantos trechos voltam (padrão 6; o LLM pode pedir de 1 a 8). Era 4 com trechos de
  1.000 caracteres; com 500 (Fase 8), 6 trechos levam o mesmo volume de texto ao LLM.
- Limiar de similaridade: abaixo dele, o trecho é "lixo" e não vai ao LLM.
  Melhor nenhum trecho ("a documentação não cobre isso") do que um trecho
  irrelevante tratado como fonte. Calibrado no golden set (Fase 8, e08): 0,35
  é o menor limiar em que nenhuma das 8 perguntas fora do escopo ("capital da
  França", "cotação do dólar") traz trecho, sem perder nenhum acerto do hit@4.
  Com 0,25 (o valor inicial), 38% delas ainda traziam algum trecho.
- Deduplicação: chunks vizinhos da mesma seção se sobrepõem. Devolver os dois
  gastaria contexto com texto repetido.

O índice precisa ter sido criado com o MESMO modelo do embedder. Vetores de
modelos diferentes vivem em "espaços" diferentes, e a similaridade entre eles não significa nada.

Documentação: docs/agente/rag.md § 7
"""
from src.agente.rag.embeddings import Embedder
from src.agente.rag.vector_store import TrechoEncontrado, VectorStore

LIMIAR_PADRAO = 0.35
TOP_K_PADRAO = 6


class Recuperador:
    """
    Busca os trechos da documentação mais parecidos com uma consulta.

    Args:
        embedder: o mesmo modelo usado na indexação.
        store: o banco vetorial com o índice.
        limiar: similaridade mínima (0,35 para o modelo da DA2, calibrado na Fase 8).

    Raises:
        ValueError: índice criado com outro modelo de embeddings.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.agente.rag.indexador import indexar
        >>> from src.agente.rag.vector_store import VectorStoreMemoria
        >>> pasta = Path(tempfile.mkdtemp())
        >>> _ = indexar(EmbedderSimulado(), pasta)
        >>> recuperador = Recuperador(EmbedderSimulado(), VectorStoreMemoria.carregar(pasta), limiar=0.1)
        >>> recuperador.buscar("limitação da regra IQR na precipitação", 1)[0].arquivo
        'docs/analise-estatistica.md'
    """

    def __init__(self, embedder: Embedder, store: VectorStore, limiar: float = LIMIAR_PADRAO) -> None:
        """Confere se o índice e o embedder usam o mesmo modelo."""
        if store.modelo != embedder.modelo:
            raise ValueError(
                f"o índice foi criado com o modelo {store.modelo}, e o embedder é {embedder.modelo}; rode python main.py --indexar"
            )
        self.__embedder = embedder
        self.__store = store
        self.limiar = limiar

    def buscar(self, consulta: str, top_k: int = TOP_K_PADRAO) -> list[TrechoEncontrado]:
        """
        Os trechos mais relevantes acima do limiar, no máximo um por seção.

        Args:
            consulta: texto de busca (o LLM pode reformular a pergunta do usuário).
            top_k: máximo de trechos devolvidos.

        Returns:
            Trechos do mais para o menos parecido. Vazio = nada relevante.
        """
        vetor = self.__embedder.vetorizar_consulta(consulta)
        # Por quê: pede o dobro, porque a deduplicação por seção pode descartar vários candidatos.
        candidatos = self.__store.buscar(vetor, top_k * 2)
        escolhidos: list[TrechoEncontrado] = []
        secoes_vistas: set[tuple[str, str]] = set()
        for trecho in candidatos:
            chave = (trecho.arquivo, trecho.secao)
            if trecho.similaridade < self.limiar or chave in secoes_vistas:
                continue
            secoes_vistas.add(chave)
            escolhidos.append(trecho)
        return escolhidos[:top_k]
