"""
Avaliação da recuperação (RAG) e os buscadores comparados no experimento e08.

Roda SEM o LLM: a pergunta do golden set vai direto para o buscador, e o
resultado é comparado com os trechos esperados (hit@k e MRR, ver metricas.py).

Conceitos
---------
- TF-IDF (baseline): cada trecho vira um vetor de PALAVRAS, com peso alto para
  palavras raras no corpus. Acha "IQR" se a pergunta disser "IQR", mas não liga
  "chuva" a "precipitação" (sinônimo não tem palavra em comum).
- Embeddings: vetor de SIGNIFICADO. Liga sinônimos, mas pode errar com códigos e
  siglas exatas ("D9", "TIP-CHU").
- Híbrido com RRF (Reciprocal Rank Fusion): junta as duas listas pela POSIÇÃO,
  sem misturar escalas de pontuação diferentes:

      pontuação(trecho) = soma, em cada lista, de 1 / (60 + posição)

  Um trecho em 1º no TF-IDF e 3º nos embeddings soma 1/61 + 1/63.

Documentação: docs/agente/avaliacao.md § 5 e docs/agente/rag.md § 7
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from src.agente.avaliacao.golden import CasoGolden
from src.agente.avaliacao.metricas import hit_e_mrr, posicao_do_primeiro_acerto
from src.agente.rag.chunker import Chunk
from src.agente.rag.embeddings import Embedder

K_RRF = 60

# Assinatura comum dos buscadores: (consulta, top_k) → [(arquivo, seção, pontuação)].
Busca = Callable[[str, int], list[tuple[str, str, float]]]


@dataclass(frozen=True)
class ResultadoRecuperacao:
    """
    hit@k e MRR de um buscador no golden set.

    Args:
        nome: rótulo do buscador no relatório (ex.: "embeddings").
        k: posições consideradas no hit@k.
        posicoes: por id do caso, a posição do primeiro trecho certo (None = não achou).

    Example:
        >>> r = ResultadoRecuperacao("tfidf", 4, {"doc-01": 1, "doc-02": None})
        >>> r.hit, r.mrr, r.falhas
        (0.5, 0.5, ['doc-02'])
    """

    nome: str
    k: int
    posicoes: dict[str, int | None] = field(default_factory=dict)

    @property
    def hit(self) -> float | None:
        """Fração das perguntas com o trecho certo entre os k primeiros."""
        return hit_e_mrr(list(self.posicoes.values()), self.k)[0]

    @property
    def mrr(self) -> float | None:
        """Média de 1/posição do primeiro trecho certo."""
        return hit_e_mrr(list(self.posicoes.values()), self.k)[1]

    @property
    def falhas(self) -> list[str]:
        """Ids das perguntas sem o trecho certo entre os k primeiros."""
        return [id_ for id_, p in self.posicoes.items() if p is None or p > self.k]


def avaliar_recuperacao(casos: Sequence[CasoGolden], buscar: Busca, k: int = 4, nome: str = "embeddings", profundidade: int = 10) -> ResultadoRecuperacao:
    """
    Executa a busca para cada caso com trechos_esperados e mede hit@k e MRR.

    Args:
        casos: golden set (os casos sem trechos esperados são ignorados).
        buscar: buscador, ex.: o Recuperador adaptado por busca_do_recuperador().
        k: posições do hit@k.
        nome: rótulo do relatório.
        profundidade: quantos resultados pedir. O MRR olha além de k (posição 7 vale 1/7).

    Example:
        >>> from src.agente.avaliacao.golden import TrechoEsperado
        >>> caso = CasoGolden(id="doc-01", categoria="documentacao", pergunta="o que é IQR?",
        ...                   trechos_esperados=[TrechoEsperado(arquivo="docs/a.md", secao_contem="IQR")])
        >>> busca = lambda consulta, top_k: [("docs/b.md", "Outro", 0.9), ("docs/a.md", "Regras > IQR", 0.8)]
        >>> avaliar_recuperacao([caso], busca).posicoes
        {'doc-01': 2}
    """
    posicoes = {}
    for caso in casos:
        if caso.trechos_esperados:
            consulta = caso.consulta_busca or caso.pergunta
            encontrados = [(arquivo, secao) for arquivo, secao, _ in buscar(consulta, profundidade)]
            posicoes[caso.id] = posicao_do_primeiro_acerto(encontrados, caso.trechos_esperados)
    return ResultadoRecuperacao(nome, k, posicoes)


def busca_do_recuperador(recuperador) -> Busca:
    """
    Adapta o Recuperador do agente (com o limiar dele) à assinatura Busca.

    Example:
        >>> class Falso:
        ...     def buscar(self, consulta, top_k):
        ...         from src.agente.rag.vector_store import TrechoEncontrado
        ...         return [TrechoEncontrado("id", "docs/a.md", "Seção", "texto", 0.7)]
        >>> busca_do_recuperador(Falso())("pergunta", 4)
        [('docs/a.md', 'Seção', 0.7)]
    """
    return lambda consulta, top_k: [(t.arquivo, t.secao, t.similaridade) for t in recuperador.buscar(consulta, top_k)]


class BuscaTfidf:
    """
    Baseline de busca por palavras (TF-IDF do scikit-learn, como no workload.py do curso).

    Args:
        trechos: corpus já dividido em chunks.
        com_cabecalho: vetoriza o cabeçalho contextual (documento e seção) junto.

    Example:
        >>> trechos = [Chunk("docs/a.md", "IQR", "O IQR é a distância entre Q1 e Q3."),
        ...            Chunk("docs/b.md", "LGPD", "O CPF é pseudonimizado com hash.")]
        >>> BuscaTfidf(trechos)("como o CPF é protegido?", 1)[0][:2]
        ('docs/b.md', 'LGPD')
    """

    def __init__(self, trechos: Sequence[Chunk], com_cabecalho: bool = True) -> None:
        """Ajusta o vocabulário e o IDF no corpus (fit) e guarda a matriz dos trechos."""
        # Por quê: import aqui para quem só usa as métricas não carregar o scikit-learn.
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.__trechos = list(trechos)
        # Conceito: sublinear_tf usa 1 + log(tf), para uma palavra repetida 10
        # vezes não valer 10 vezes mais; strip_accents casa "análise" e "analise".
        self.__vetorizador = TfidfVectorizer(strip_accents="unicode", sublinear_tf=True)
        textos = [t.texto_vetorizado() if com_cabecalho else t.texto for t in self.__trechos]
        self.__matriz = self.__vetorizador.fit_transform(textos)

    def __call__(self, consulta: str, top_k: int) -> list[tuple[str, str, float]]:
        """Os top_k trechos com maior similaridade de cosseno entre vetores TF-IDF."""
        # Conceito: o TfidfVectorizer já normaliza cada linha (norma L2), então o
        # produto escalar é a similaridade de cosseno.
        pontuacoes = (self.__matriz @ self.__vetorizador.transform([consulta]).T).toarray().ravel()
        return _melhores(self.__trechos, pontuacoes, top_k)


class BuscaEmbeddings:
    """
    Busca vetorial em memória sobre um corpus qualquer (para comparar chunkings sem reindexar).

    Args:
        trechos: corpus já dividido em chunks.
        embedder: EmbedderFastembed (real) ou EmbedderSimulado (testes).
        com_cabecalho: vetoriza o cabeçalho contextual junto.

    Example:
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> trechos = [Chunk("docs/a.md", "IQR", "intervalo interquartil IQR"), Chunk("docs/b.md", "LGPD", "cpf hash lgpd")]
        >>> BuscaEmbeddings(trechos, EmbedderSimulado())("cpf lgpd", 1)[0][0]
        'docs/b.md'
    """

    def __init__(self, trechos: Sequence[Chunk], embedder: Embedder, com_cabecalho: bool = True) -> None:
        """Vetoriza todos os trechos uma vez."""
        self.__trechos = list(trechos)
        self.__embedder = embedder
        self.__matriz = embedder.vetorizar_documentos([t.texto_vetorizado() if com_cabecalho else t.texto for t in self.__trechos])

    def __call__(self, consulta: str, top_k: int) -> list[tuple[str, str, float]]:
        """Os top_k trechos com maior similaridade de cosseno (vetores já normalizados)."""
        return _melhores(self.__trechos, self.__matriz @ self.__embedder.vetorizar_consulta(consulta), top_k)


class BuscaHibrida:
    """
    Fusão de vários buscadores por RRF (Reciprocal Rank Fusion).

    Example:
        >>> a = lambda c, k: [("x.md", "A", 0.9), ("y.md", "B", 0.5)]
        >>> b = lambda c, k: [("y.md", "B", 0.8), ("z.md", "C", 0.7)]
        >>> [item[:2] for item in BuscaHibrida([a, b])("pergunta", 3)]
        [('y.md', 'B'), ('x.md', 'A'), ('z.md', 'C')]
    """

    def __init__(self, buscas: Sequence[Busca], profundidade: int = 20) -> None:
        """Guarda os buscadores e quantos resultados pedir a cada um antes da fusão."""
        self.__buscas = list(buscas)
        self.__profundidade = profundidade

    def __call__(self, consulta: str, top_k: int) -> list[tuple[str, str, float]]:
        """Os top_k trechos com maior soma de 1 / (60 + posição) nas listas."""
        listas = [[(arquivo, secao) for arquivo, secao, _ in busca(consulta, max(top_k, self.__profundidade))] for busca in self.__buscas]
        return [(arquivo, secao, pontuacao) for (arquivo, secao), pontuacao in fusao_rrf(listas)[:top_k]]


def fusao_rrf(listas: Sequence[Sequence[tuple[str, str]]], k: int = K_RRF) -> list[tuple[tuple[str, str], float]]:
    """
    Junta listas ordenadas pela posição: cada item soma 1 / (k + posição) por lista.

    Example:
        >>> [(item, round(p, 4)) for item, p in fusao_rrf([[("a", "1"), ("b", "2")], [("b", "2")]])]
        [(('b', '2'), 0.0325), (('a', '1'), 0.0164)]
    """
    pontuacoes: dict[tuple[str, str], float] = {}
    for lista in listas:
        for posicao, item in enumerate(lista, start=1):
            pontuacoes[item] = pontuacoes.get(item, 0.0) + 1 / (k + posicao)
    return sorted(pontuacoes.items(), key=lambda par: -par[1])


def _melhores(trechos: Sequence[Chunk], pontuacoes: np.ndarray, top_k: int) -> list[tuple[str, str, float]]:
    """Os top_k trechos de maior pontuação, sem repetir a mesma (arquivo, seção)."""
    resultado, vistos = [], set()
    for indice in np.argsort(-pontuacoes, kind="stable"):
        chave = (trechos[indice].arquivo, trechos[indice].secao)
        if chave not in vistos:
            vistos.add(chave)
            resultado.append((*chave, round(float(pontuacoes[indice]), 4)))
        if len(resultado) == top_k:
            break
    return resultado
