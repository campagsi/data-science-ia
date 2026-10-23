"""
Exemplo 03 — Como um documento vira trechos (chunking).

Demonstra: o docs/analise-estatistica.md dividido pelos títulos e, dentro das
seções grandes, em pedaços de até 500 caracteres com 75 de sobreposição.

Como rodar:  python -m src.agente.exemplos.e03_chunking
Observe:     o caminho da seção de cada trecho, os tamanhos (80 a 500) e,
             nos trechos seguidos da mesma seção, o fim de um repetido no começo do outro.

Sem rede e sem modelo.
Documentação: docs/agente/rag.md § 3
"""
from src.agente.rag.chunker import dividir_markdown
from src.agente.rag.indexador import RAIZ_PROJETO

ARQUIVO = "docs/analise-estatistica.md"


def main() -> None:
    """Divide o documento e mostra cada trecho e as sobreposições."""
    trechos = dividir_markdown((RAIZ_PROJETO / ARQUIVO).read_text(encoding="utf-8"), ARQUIVO)
    print(f"{ARQUIVO}: {len(trechos)} trechos\n")
    for numero, trecho in enumerate(trechos, start=1):
        inicio = trecho.texto[:70].replace("\n", " ")
        print(f"{numero:2}. {len(trecho.texto):4} caracteres | {trecho.secao[:60]}\n    {inicio}...")
    for anterior, seguinte in zip(trechos, trechos[1:]):
        if anterior.secao == seguinte.secao:
            print(f"\nSobreposição em '{seguinte.secao[:50]}':")
            print(f"    fim do anterior : ...{anterior.texto[-60:]!r}")
            print(f"    início do seguinte: {seguinte.texto[:60]!r}...")
            break
    print("\nTexto que vira embedding (com o cabeçalho contextual):\n")
    print(trechos[1].texto_vetorizado()[:300])


if __name__ == "__main__":
    main()
