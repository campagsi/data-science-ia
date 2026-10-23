"""
Exemplo 09 — Teste de hipótese: t-test × Mann-Whitney × tamanho de efeito.

Demonstra, com dados sintéticos de turbidez (assimétricos, com picos, como os
do projeto), duas lições de inferência:

1. Com muitas medições, uma diferença MINÚSCULA vira "significativa": o p-valor
   é pequeno, mas o tamanho de efeito é desprezível. "Significativo" não quer
   dizer "importante".
2. Em dados assimétricos, poucos picos de sensor puxam a MÉDIA, mas quase não
   mexem na MEDIANA nem no tamanho de efeito por postos. Por isso o agente cita
   a mediana junto com a média e usa o Mann-Whitney (por postos), e não o t-test
   (que compara médias e supõe normalidade).

Como rodar:  python -m src.agente.exemplos.e09_teste_hipotese
Observe:     no cenário 1, o p-valor < 0,05 com efeito "desprezível"; no
             cenário 2, 3 picos dobram a média de B, enquanto a mediana e o
             tamanho de efeito quase não mudam. (Os p-valores do cenário 2 ficam
             perto de 0,05 nos dois testes: com 200 valores, o acaso pesa.)

Sem rede e sem banco (dados gerados com semente fixa, então o resultado se repete).
Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA/estatistica_IA/aplicacao_estatistica.py
Documentação: docs/agente/ferramentas.md § 4.8
"""
import numpy as np
from scipy import stats

from src.agente.ferramentas.calculos_inferencia import comparar_amostras


def turbidez(rng: np.random.Generator, n: int, deslocamento: float = 0.0) -> list[float]:
    """Valores lognormais (assimétricos, cauda longa à direita), em NTU."""
    return list(rng.lognormal(mean=1.6 + deslocamento, sigma=0.6, size=n))


def mostrar(titulo: str, a: list[float], b: list[float]) -> None:
    """Imprime o t-test, o Mann-Whitney e o tamanho de efeito para duas amostras."""
    teste_t = stats.ttest_ind(a, b, equal_var=False)
    resultado = comparar_amostras(a, b)
    print(f"\n{titulo}")
    print(f"  médias: {np.mean(a):.2f} × {np.mean(b):.2f} NTU   medianas: {np.median(a):.2f} × {np.median(b):.2f} NTU")
    print(f"  t-test (Welch):  p = {teste_t.pvalue:.2g}")
    print(f"  Mann-Whitney:    p = {resultado['p_valor']}   significativo: {resultado['significativo']}")
    print(f"  tamanho de efeito (rank-bisserial): {resultado['efeito']} → {resultado['efeito_interpretacao']}")


def main() -> None:
    """Roda os dois cenários."""
    rng = np.random.default_rng(42)

    junho, julho = turbidez(rng, 20000), turbidez(rng, 20000, deslocamento=0.03)
    mostrar("Cenário 1: 20 mil medições por mês, diferença de 3% na escala", junho, julho)

    a, b = turbidez(rng, 200), turbidez(rng, 200)
    picos = b + [400.0, 450.0, 500.0]
    mostrar("Cenário 2a: duas amostras da mesma distribuição", a, b)
    mostrar("Cenário 2b: as mesmas, com 3 picos de sensor em B", a, picos)


if __name__ == "__main__":
    main()
