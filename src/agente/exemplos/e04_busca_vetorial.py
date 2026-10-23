"""
Exemplo 04 — Busca vetorial na documentação do projeto.

Demonstra: o índice criado por python main.py --indexar respondendo perguntas.
Cada consulta vira um vetor, e o banco devolve os trechos de maior similaridade
de cosseno acima do limiar (0,35), no máximo um por seção.

Como rodar:  python main.py --indexar   (uma vez)
             python -m src.agente.exemplos.e04_busca_vetorial "sua pergunta"
Observe:     (1) a pergunta sobre chuva e IQR acha analise-estatistica.md;
             (2) a receita de bolo não acha nada acima do limiar, e é melhor
             assim que um trecho irrelevante; (3) "como rodar a ingestão" acha o
             manual: paráfrase era o ponto fraco com trechos de 1.000 caracteres (e08, Fase 8).

Documentação: docs/agente/rag.md § 7
"""
import sys

from src.agente.rag.embeddings import EmbedderFastembed
from src.agente.rag.recuperador import Recuperador
from src.agente.rag.vector_store import abrir_indice
from src.config import load_config_indice

PERGUNTAS = [
    "por que a chuva gera tantos alertas IQR?",
    "o que significa o alerta IQR+ZSCORE?",
    "como o CPF do operador é protegido?",
    "como rodar a ingestão",
    "receita de bolo de chocolate",
]


def main(argv: list[str]) -> None:
    """Busca cada pergunta (as da linha de comando ou as de exemplo) e imprime os trechos."""
    cfg = load_config_indice()
    store = abrir_indice(cfg.vetores, cfg.dir_indice)
    if store is None:
        print("Índice não encontrado. Rode antes: python main.py --indexar")
        return
    recuperador = Recuperador(EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos"), store)
    print(f"Índice ({cfg.vetores}): {len(store)} trechos, modelo {store.modelo}, limiar {recuperador.limiar}")
    for pergunta in [" ".join(argv)] if argv else PERGUNTAS:
        print(f"\n{pergunta}")
        trechos = recuperador.buscar(pergunta, 3)
        for trecho in trechos:
            print(f"   {trecho.similaridade:.2f}  {trecho.arquivo} > {trecho.secao[-55:]}")
        if not trechos:
            print("   (nenhum trecho acima do limiar)")


if __name__ == "__main__":
    main(sys.argv[1:])
