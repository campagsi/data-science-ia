"""
Exemplo 02 — Similaridade de cosseno com embeddings reais.

Demonstra: textos de significado parecido ficam com vetores próximos, mesmo
sem palavras em comum ("acidez da água" × "pH"). Compara o modelo real (DA2)
com o EmbedderSimulado (hashing de palavras), que só enxerga palavras iguais.

Como rodar:  python -m src.agente.exemplos.e02_similaridade
Observe:     (1) no modelo real, "acidez da água" fica mais perto de "pH da
             água" do que de "velocidade do vento"; (2) no simulado, o que
             pesa é ter palavras iguais ("água"), não o significado.

Na primeira execução, o modelo (~0,22 GB) é baixado para data/agente/modelos.
Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA/matematica_IA/mat_IA.py
Documentação: docs/agente/rag.md § 4
"""
from src.agente.rag.embeddings import EmbedderFastembed, EmbedderSimulado

TEXTOS = ["pH da água", "acidez da água", "turbidez da água após a chuva", "velocidade do vento"]


def tabela(nome: str, embedder) -> None:
    """Imprime a matriz de similaridade de cosseno entre os textos."""
    vetores = embedder.vetorizar_documentos(TEXTOS)
    # Conceito: com vetores normalizados, cosseno = produto escalar. A matriz inteira é V @ Vᵀ.
    similaridades = vetores @ vetores.T
    print(f"\n{nome} ({embedder.dimensoes} dimensões)")
    print(" " * 32 + "".join(f"{t[:14]:>16}" for t in TEXTOS))
    for texto, linha in zip(TEXTOS, similaridades):
        print(f"{texto:32}" + "".join(f"{valor:16.2f}" for valor in linha))


def main() -> None:
    """Compara o modelo real com o simulado."""
    tabela("Modelo real (paraphrase-multilingual-MiniLM-L12-v2)", EmbedderFastembed())
    tabela("Simulado (hashing de palavras)", EmbedderSimulado())


if __name__ == "__main__":
    main()
