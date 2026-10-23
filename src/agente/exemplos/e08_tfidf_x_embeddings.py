"""
Exemplo 08 — Recuperação: TF-IDF × embeddings × híbrido, chunking e limiar.

Demonstra os experimentos de docs/agente/avaliacao.md § 5, SEM o LLM e sem custo:
as perguntas do golden set com trechos esperados vão direto ao buscador, e o
resultado é medido com hit@4 e MRR.

    1. buscadores    TF-IDF (palavras) × embeddings (significado) × híbrido (RRF)
    2. chunking      500, 1.000 e 1.500 caracteres; com e sem cabeçalho contextual
    3. limiar        para cada limiar: hit@4 das perguntas do projeto e "lixo",
                     a fração das perguntas FORA do escopo que ainda trazem algum trecho

Regra de experimento: muda UMA coisa por vez e compara com a referência
(embeddings, 500 caracteres, com cabeçalho, limiar 0,35 = o índice do agente depois da Fase 8).

Como rodar:  python -m src.agente.exemplos.e08_tfidf_x_embeddings            (modelo real, ~3 min)
             python -m src.agente.exemplos.e08_tfidf_x_embeddings --simulado (embedder simulado, segundos)
Observe:     (1) o TF-IDF acerta perguntas com termos exatos ("Z-Score", "D9"), e os
             embeddings, as paráfrases ("como eu executo a ingestão");
             (2) o híbrido junta os dois pela posição;
             (3) limiar alto corta o lixo, mas também trechos certos (o "custo" do limiar).

Documentação: docs/agente/avaliacao.md § 5 e docs/agente/rag.md § 7
"""
import sys
from collections.abc import Sequence

from src.agente.avaliacao.golden import CasoGolden, carregar_golden
from src.agente.avaliacao.recuperacao import BuscaEmbeddings, BuscaHibrida, BuscaTfidf, avaliar_recuperacao
from src.agente.rag.chunker import SOBREPOSICAO, TAMANHO_MAXIMO, Chunk
from src.agente.rag.embeddings import Embedder, EmbedderSimulado
from src.agente.rag.indexador import arquivos_do_corpus, trechos_do_corpus
from src.agente.rag.recuperador import LIMIAR_PADRAO

FORA_DO_ESCOPO = [
    "Escreva um poema sobre futebol.",
    "Qual é a capital da França?",
    "Receita de bolo de chocolate.",
    "Quem ganhou a Copa do Mundo de 2002?",
    "Como trocar o pneu de um carro?",
    "Me recomende um filme de ação.",
    "Qual a cotação do dólar hoje?",
    "Traduza 'bom dia' para o japonês.",
]
CHUNKINGS = [(500, 75), (1000, 150), (1500, 225)]
LIMIARES = [0.0, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]


def comparar_buscadores(casos: Sequence[CasoGolden], trechos: Sequence[Chunk], embedder: Embedder) -> list[tuple[str, float | None, float | None]]:
    """
    (nome, hit@4, MRR) de TF-IDF, embeddings e híbrido no mesmo corpus.

    Example:
        >>> from src.agente.avaliacao.golden import TrechoEsperado
        >>> trechos = [Chunk("docs/a.md", "IQR", "o alerta IQR usa os quartis"), Chunk("docs/b.md", "LGPD", "o cpf vira hash")]
        >>> caso = CasoGolden(id="doc-01", categoria="documentacao", pergunta="como o cpf é protegido",
        ...                   trechos_esperados=[TrechoEsperado(arquivo="docs/b.md", secao_contem="LGPD")])
        >>> [(nome, hit) for nome, hit, _ in comparar_buscadores([caso], trechos, EmbedderSimulado())]
        [('tfidf', 1.0), ('embeddings', 1.0), ('hibrido', 1.0)]
    """
    tfidf, vetorial = BuscaTfidf(trechos), BuscaEmbeddings(trechos, embedder)
    linhas = []
    for nome, busca in (("tfidf", tfidf), ("embeddings", vetorial), ("hibrido", BuscaHibrida([tfidf, vetorial]))):
        resultado = avaliar_recuperacao(casos, busca, nome=nome)
        linhas.append((nome, resultado.hit, resultado.mrr))
    return linhas


def curva_do_limiar(casos: Sequence[CasoGolden], busca, fora_do_escopo: Sequence[str] = FORA_DO_ESCOPO, limiares: Sequence[float] = LIMIARES) -> list[tuple[float, float | None, float]]:
    """
    (limiar, hit@4, lixo) para cada limiar.

    lixo = fração das perguntas fora do escopo com pelo menos um trecho acima do limiar.

    Example:
        >>> busca = lambda consulta, k: [("docs/a.md", "IQR", 0.6 if "IQR" in consulta else 0.3)]
        >>> from src.agente.avaliacao.golden import TrechoEsperado
        >>> caso = CasoGolden(id="doc-01", categoria="documentacao", pergunta="o que é IQR",
        ...                   trechos_esperados=[TrechoEsperado(arquivo="docs/a.md", secao_contem="IQR")])
        >>> curva_do_limiar([caso], busca, ["poema"], [0.2, 0.5, 0.7])
        [(0.2, 1.0, 1.0), (0.5, 1.0, 0.0), (0.7, 0.0, 0.0)]
    """
    curva = []
    for limiar in limiares:
        acima = lambda consulta, k, limiar=limiar: [t for t in busca(consulta, k) if t[2] >= limiar]  # noqa: E731
        hit = avaliar_recuperacao(casos, acima).hit
        lixo = sum(1 for pergunta in fora_do_escopo if acima(pergunta, 4)) / len(fora_do_escopo)
        curva.append((limiar, hit, lixo))
    return curva


def main(argv: list[str]) -> None:
    """Roda os três experimentos e imprime as tabelas."""
    if "--simulado" in argv:
        embedder = EmbedderSimulado()
    else:
        from src.agente.rag.embeddings import EmbedderFastembed
        from src.config import load_config_indice

        cfg = load_config_indice()
        embedder = EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos")
    casos = [caso for caso in carregar_golden() if caso.trechos_esperados]
    arquivos = arquivos_do_corpus()
    print(f"{len(casos)} perguntas com trechos esperados, {len(arquivos)} arquivos no corpus\n")

    referencia = trechos_do_corpus(arquivos)
    print(f"1. Buscadores ({TAMANHO_MAXIMO} caracteres, com cabeçalho)")
    for nome, hit, mrr in comparar_buscadores(casos, referencia, embedder):
        print(f"   {nome:<11} hit@4={_fmt(hit)}  MRR={_fmt(mrr)}")

    print("\n2. Chunking (embeddings | híbrido)")
    for tamanho, sobreposicao in CHUNKINGS:
        padrao = (tamanho, sobreposicao) == (TAMANHO_MAXIMO, SOBREPOSICAO)
        trechos = referencia if padrao else trechos_do_corpus(arquivos, tamanho_maximo=tamanho, sobreposicao=sobreposicao)
        linhas = dict((nome, (hit, mrr)) for nome, hit, mrr in comparar_buscadores(casos, trechos, embedder))
        print(f"   {tamanho:>5} car. ({len(trechos)} trechos)  embeddings hit@4={_fmt(linhas['embeddings'][0])} MRR={_fmt(linhas['embeddings'][1])}"
              f" | híbrido hit@4={_fmt(linhas['hibrido'][0])} MRR={_fmt(linhas['hibrido'][1])}")
    sem_cabecalho = avaliar_recuperacao(casos, BuscaEmbeddings(referencia, embedder, com_cabecalho=False))
    print(f"   {TAMANHO_MAXIMO:>5} car. sem cabeçalho   embeddings hit@4={_fmt(sem_cabecalho.hit)} MRR={_fmt(sem_cabecalho.mrr)}")

    print(f"\n3. Limiar (embeddings; o agente usa {LIMIAR_PADRAO})")
    for limiar, hit, lixo in curva_do_limiar(casos, BuscaEmbeddings(referencia, embedder)):
        print(f"   limiar={limiar:.2f}  hit@4={_fmt(hit)}  lixo={lixo:.0%}")


def _fmt(valor: float | None) -> str:
    """Número com 2 casas e vírgula, ou "—"."""
    return "—" if valor is None else f"{valor:.2f}".replace(".", ",")


if __name__ == "__main__":
    main(sys.argv[1:])
