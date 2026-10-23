"""
Indexação idempotente da documentação (python main.py --indexar).

Conceito
--------
Idempotência: rodar duas vezes seguidas tem o mesmo efeito de rodar uma. É a
mesma ideia da carga idempotente das leituras na ingestão, agora no índice.

O truque é a IDENTIDADE de cada trecho: id = sha256(modelo + arquivo + seção + texto).

- trecho igual → mesmo id → é mantido, e o embedding (a parte cara) não é recalculado;
- texto alterado → id novo: o antigo sai e o novo entra;
- modelo de embeddings trocado → todos os ids mudam → reindexação completa,
  sem misturar vetores de modelos diferentes.

    desejados = ids dos trechos dos arquivos de hoje
    novos     = desejados - existentes    → vetorizar e inserir
    obsoletos = existentes - desejados    → remover

Segunda execução sem mudança nos docs: inseridos=0 removidos=0.

O corpus é uma lista FECHADA de pastas (allowlist): README, docs/, diagramas e
docs/agente/, sem os TODOs. Logs, sql/, .env e o dataset nunca entram (dados pessoais e
segredos, rag.md § 2). Mesmo assim, o texto passa pela máscara de CPF, e-mail e
telefone antes de ser guardado (POL-02): exemplos nos documentos não vão para o LLM.

Documentação: docs/agente/rag.md § 2 e § 6
"""
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.agente.rag.chunker import SOBREPOSICAO, TAMANHO_MAXIMO, Chunk, dividir_markdown
from src.agente.rag.embeddings import Embedder
from src.agente.rag.vector_store import RegistroIndice, abrir_indice, novo_indice
from src.logger import logger
from src.security import mascarar_texto_livre

RAIZ_PROJETO = Path(__file__).resolve().parents[3]
# Allowlist do corpus (rag.md § 2): só documentação.
PADROES_CORPUS = ("README.md", "docs/*.md", "docs/diagramas/*.md", "docs/agente/*.md")
# Por quê: os TODOs são listas de tarefas que repetem as perguntas de exemplo ao pé da
# letra ("por que a chuva gera tantos alertas IQR?") e passavam à frente do documento
# que de fato explica a regra (medido em 21/10/2026). Não são conhecimento.
PADROES_EXCLUIDOS = ("docs/todo-*.md", "docs/agente/todo.md")


@dataclass(frozen=True)
class ResumoIndexacao:
    """
    O que uma indexação fez, também registrado no log.

    Example:
        >>> ResumoIndexacao(arquivos=2, chunks=10, inseridos=0, removidos=0, mantidos=10, ms=5).mantidos
        10
    """

    arquivos: int
    chunks: int
    inseridos: int
    removidos: int
    mantidos: int
    ms: int


def arquivos_do_corpus(raiz: Path = RAIZ_PROJETO) -> list[Path]:
    """
    Arquivos Markdown que entram no índice, em ordem de caminho.

    Example:
        >>> any(p.name == "analise-estatistica.md" for p in arquivos_do_corpus())
        True
    """
    excluidos = {caminho for padrao in PADROES_EXCLUIDOS for caminho in raiz.glob(padrao)}
    return sorted({caminho for padrao in PADROES_CORPUS for caminho in raiz.glob(padrao) if caminho.is_file()} - excluidos)


def id_do_trecho(modelo: str, chunk: Chunk) -> str:
    """
    Identidade do trecho: muda se o modelo, o arquivo, a seção ou o texto mudar.

    Example:
        >>> a = id_do_trecho("m1", Chunk("x.md", "S", "texto"))
        >>> a == id_do_trecho("m1", Chunk("x.md", "S", "texto")), a == id_do_trecho("m2", Chunk("x.md", "S", "texto"))
        (True, False)
    """
    # Por quê: o separador \0 evita que ("ab", "c") e ("a", "bc") gerem o mesmo hash.
    conteudo = "\0".join((modelo, chunk.arquivo, chunk.secao, chunk.texto))
    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()


def trechos_do_corpus(
    arquivos: list[Path],
    raiz: Path = RAIZ_PROJETO,
    tamanho_maximo: int = TAMANHO_MAXIMO,
    sobreposicao: int = SOBREPOSICAO,
) -> list[Chunk]:
    """
    Trechos de todos os arquivos, com o texto já mascarado (POL-02).

    O tamanho e a sobreposição só mudam no experimento de chunking (e08): o
    índice do agente usa sempre os padrões do chunker.

    Example:
        >>> len(trechos_do_corpus(arquivos_do_corpus())) > 100
        True
    """
    trechos = []
    for arquivo in arquivos:
        relativo = arquivo.relative_to(raiz).as_posix()
        for chunk in dividir_markdown(arquivo.read_text(encoding="utf-8"), relativo, tamanho_maximo, sobreposicao):
            trechos.append(Chunk(chunk.arquivo, chunk.secao, mascarar_texto_livre(chunk.texto)))
    return trechos


def indexar(embedder: Embedder, pasta_indice: Path, raiz: Path = RAIZ_PROJETO, vetores: str = "memoria") -> ResumoIndexacao:
    """
    Atualiza o índice salvo na pasta para refletir os documentos de hoje.

    Args:
        embedder: modelo de embeddings (o mesmo que o recuperador vai usar).
        pasta_indice: onde o índice fica (AGENTE_DIR_INDICE, padrão data/agente).
        raiz: raiz do projeto, de onde vem o corpus.
        vetores: banco vetorial, "memoria" ou "chroma" (AGENTE_VETORES).

    Returns:
        Contagens da indexação (também registradas em INFO no log).

    Example:
        >>> import tempfile
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> pasta = Path(tempfile.mkdtemp())
        >>> primeira = indexar(EmbedderSimulado(), pasta)
        >>> segunda = indexar(EmbedderSimulado(), pasta)
        >>> primeira.inseridos > 0, (segunda.inseridos, segunda.removidos)
        (True, (0, 0))
    """
    inicio = time.monotonic()
    arquivos = arquivos_do_corpus(raiz)
    trechos = trechos_do_corpus(arquivos, raiz)
    inseridos, removidos = sincronizar(embedder, pasta_indice, vetores, trechos)
    total = len({id_do_trecho(embedder.modelo, trecho) for trecho in trechos})
    resumo = ResumoIndexacao(
        arquivos=len(arquivos),
        chunks=total,
        inseridos=inseridos,
        removidos=removidos,
        mantidos=total - inseridos,
        ms=int((time.monotonic() - inicio) * 1000),
    )
    logger.info(
        f"Indexação: vetores={vetores} modelo={embedder.modelo} arquivos={resumo.arquivos} chunks={resumo.chunks} "
        f"inseridos={resumo.inseridos} removidos={resumo.removidos} mantidos={resumo.mantidos} ms={resumo.ms}"
    )
    return resumo


def sincronizar(
    embedder: Embedder,
    pasta_indice: Path,
    vetores: str,
    trechos: list[Chunk],
    texto_do_vetor: Callable[[Chunk], str] = Chunk.texto_vetorizado,
) -> tuple[int, int]:
    """
    Deixa o índice da pasta com exatamente estes trechos, vetorizando só os novos.

    É o núcleo idempotente, usado pela documentação (indexar) e pelos resumos
    diários (dias/indice.py, Fase 9), cada um na sua pasta.

    Args:
        embedder: modelo de embeddings.
        pasta_indice: pasta do índice.
        vetores: "memoria" ou "chroma".
        trechos: o conteúdo desejado do índice.
        texto_do_vetor: o texto que vira embedding (padrão: cabeçalho contextual + texto).

    Returns:
        (inseridos, removidos).

    Example:
        >>> import tempfile
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> pasta, trechos = Path(tempfile.mkdtemp()), [Chunk("docs/a.md", "A", "texto do trecho a")]
        >>> sincronizar(EmbedderSimulado(), pasta, "memoria", trechos), sincronizar(EmbedderSimulado(), pasta, "memoria", trechos)
        ((1, 0), (0, 0))
    """
    desejados = {id_do_trecho(embedder.modelo, chunk): chunk for chunk in trechos}
    store = abrir_indice(vetores, pasta_indice)
    if store is None or store.modelo != embedder.modelo or store.dimensoes != embedder.dimensoes:
        # Modelo diferente: os ids não batem mesmo, então começa um índice novo.
        store = novo_indice(vetores, pasta_indice, embedder.modelo, embedder.dimensoes)
    existentes = store.ids()

    novos = [identificador for identificador in desejados if identificador not in existentes]
    obsoletos = existentes - set(desejados)
    if novos:
        # Conceito: só o que é novo é vetorizado; o embedding é a parte cara da indexação.
        # Cuidado: "matriz", e não "vetores", que é o parâmetro com o tipo do banco (bug achado no log).
        matriz = embedder.vetorizar_documentos([texto_do_vetor(desejados[i]) for i in novos])
        store.inserir([RegistroIndice(i, desejados[i].arquivo, desejados[i].secao, desejados[i].texto) for i in novos], matriz)
    store.remover(obsoletos)
    store.persistir()
    return len(novos), len(obsoletos)
