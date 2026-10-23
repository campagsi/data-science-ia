"""
Índice dos resumos diários (python main.py --indexar-dias) e a busca de dias vizinhos.

Conceito
--------
Mesmo mecanismo do índice da documentação (indexacao idempotente por hash,
rag/indexador.py), mas numa PASTA SEPARADA (data/agente/dias): uma busca na
documentação nunca devolve um dia, e uma busca de dias nunca devolve um documento.

    resumo do dia → Chunk(arquivo="dias/EST-RJ-001", secao="2026-06-15", texto=resumo)
    id = sha256(modelo + arquivo + seção + texto)

Uma nova ingestão muda os tercis e as anomalias: só os dias cujo resumo mudou
são vetorizados de novo.

A busca usa o resumo do dia pedido como CONSULTA e devolve os vizinhos mais
próximos da mesma estação, sem o próprio dia.

Documentação: docs/agente/rag.md § 8
"""
import time
from pathlib import Path

from src.agente.dias.resumos import ResumoDia, conteudo_do_texto, resumos_diarios
from src.agente.rag.chunker import Chunk
from src.agente.rag.embeddings import Embedder
from src.agente.rag.indexador import ResumoIndexacao, id_do_trecho, sincronizar
from src.agente.rag.vector_store import TrechoEncontrado, VectorStore, abrir_indice
from src.logger import logger

PASTA_DIAS = "dias"
PREFIXO_ARQUIVO = "dias/"


def trechos_dos_dias(resumos: list[ResumoDia]) -> list[Chunk]:
    """
    Um Chunk por dia: o "arquivo" é a estação, e a "seção", a data ISO.

    Example:
        >>> from datetime import date
        >>> trecho = trechos_dos_dias([ResumoDia("EST-1", date(2026, 6, 1), "01/06/2026, estação EST-1\\nSem chuva.")])[0]
        >>> trecho.arquivo, trecho.secao
        ('dias/EST-1', '2026-06-01')
    """
    return [Chunk(f"{PREFIXO_ARQUIVO}{r.estacao}", r.dia.isoformat(), r.texto) for r in resumos]


def indexar_dias(medicoes: list[dict], embedder: Embedder, pasta_indice: Path, vetores: str = "memoria") -> ResumoIndexacao:
    """
    Atualiza o índice dos dias em pasta_indice/dias para refletir as medições.

    Args:
        medicoes: todas as medições (ConsultaDados.medicoes(FiltroMedicoes())).
        embedder: o mesmo modelo de embeddings da documentação.
        pasta_indice: AGENTE_DIR_INDICE (o índice fica na subpasta "dias").
        vetores: "memoria" ou "chroma".

    Returns:
        Contagens (arquivos = estações, chunks = dias), também registradas no log.

    Example:
        >>> import tempfile
        >>> from datetime import datetime
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> medicoes = [{"estacao_codigo": "EST-1", "estacao": "Estação 1", "codigo_registro": f"R{d}",
        ...              "data_hora": datetime(2026, 6, d), "codigo_parametro": "TIP-CHU", "parametro": "Precipitação",
        ...              "unidade_medida": "mm", "valor": float(d)} for d in (1, 2, 3)]
        >>> pasta = Path(tempfile.mkdtemp())
        >>> primeira, segunda = indexar_dias(medicoes, EmbedderSimulado(), pasta), indexar_dias(medicoes, EmbedderSimulado(), pasta)
        >>> (primeira.arquivos, primeira.chunks, primeira.inseridos), (segunda.inseridos, segunda.removidos)
        ((1, 3, 3), (0, 0))
    """
    inicio = time.monotonic()
    resumos = resumos_diarios(medicoes)
    trechos = trechos_dos_dias(resumos)
    # Por quê: o embedding usa o conteúdo sem a linha de data e estação (resumos.py).
    inseridos, removidos = sincronizar(embedder, pasta_indice / PASTA_DIAS, vetores, trechos, lambda chunk: conteudo_do_texto(chunk.texto))
    total = len({id_do_trecho(embedder.modelo, trecho) for trecho in trechos})
    resumo = ResumoIndexacao(
        arquivos=len({r.estacao for r in resumos}),
        chunks=total,
        inseridos=inseridos,
        removidos=removidos,
        mantidos=total - inseridos,
        ms=int((time.monotonic() - inicio) * 1000),
    )
    logger.info(
        f"Indexação dos dias: vetores={vetores} modelo={embedder.modelo} estacoes={resumo.arquivos} dias={resumo.chunks} "
        f"inseridos={resumo.inseridos} removidos={resumo.removidos} mantidos={resumo.mantidos} ms={resumo.ms}"
    )
    return resumo


class BuscaDeDias:
    """
    Busca os dias mais parecidos com um resumo, na mesma estação.

    Args:
        embedder: o modelo usado na indexação.
        store: o índice dos dias (abrir_busca_de_dias).

    Example:
        >>> import tempfile
        >>> from datetime import datetime
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> medicoes = [{"estacao_codigo": "EST-1", "estacao": "Estação 1", "codigo_registro": f"R{d}",
        ...              "data_hora": datetime(2026, 6, d), "codigo_parametro": "TIP-CHU", "parametro": "Precipitação",
        ...              "unidade_medida": "mm", "valor": v} for d, v in ((1, 0.0), (2, 30.0), (3, 0.0))]
        >>> pasta = Path(tempfile.mkdtemp())
        >>> _ = indexar_dias(medicoes, EmbedderSimulado(), pasta)
        >>> busca = abrir_busca_de_dias(EmbedderSimulado(), pasta)
        >>> [t.secao for t in busca.vizinhos("Sem chuva: 0 mm no dia. Sem anomalias.", "EST-1", "2026-06-01", 1)]
        ['2026-06-03']
    """

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        """Guarda o embedder e o índice."""
        self.__embedder = embedder
        self.__store = store

    def __len__(self) -> int:
        """Dias indexados (todas as estações)."""
        return len(self.__store)

    def vizinhos(self, conteudo: str, estacao: str, dia: str, top_k: int) -> list[TrechoEncontrado]:
        """
        Os top_k dias da estação mais parecidos com o conteúdo, sem o próprio dia.

        Args:
            conteudo: resumo do dia de referência, sem a linha de data e estação.
            estacao: código da estação.
            dia: data ISO do dia de referência (fica fora do resultado).
            top_k: quantidade de dias.
        """
        # Por quê: o índice tem todas as estações; pedir todos e filtrar é simples e
        # barato (um dia por estação por dia de dados, poucas centenas no total).
        candidatos = self.__store.buscar(self.__embedder.vetorizar_consulta(conteudo), len(self.__store))
        arquivo = f"{PREFIXO_ARQUIVO}{estacao}"
        return [t for t in candidatos if t.arquivo == arquivo and t.secao != dia][:top_k]


def abrir_busca_de_dias(embedder: Embedder, pasta_indice: Path, vetores: str = "memoria") -> BuscaDeDias | None:
    """
    BuscaDeDias sobre o índice salvo, ou None se ele não existe ou é de outro modelo.

    Example:
        >>> import tempfile
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> abrir_busca_de_dias(EmbedderSimulado(), Path(tempfile.mkdtemp())) is None
        True
    """
    store = abrir_indice(vetores, pasta_indice / PASTA_DIAS)
    if store is None or store.modelo != embedder.modelo:
        return None
    return BuscaDeDias(embedder, store)
