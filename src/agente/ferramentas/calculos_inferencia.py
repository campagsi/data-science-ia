"""
Cálculos de inferência estatística das ferramentas, em funções puras.

Conceito
--------
Estatística descritiva DESCREVE uma amostra (média, mediana). Inferência
pergunta se a diferença observada é real ou poderia ser acaso:

- Teste de hipótese (Mann-Whitney U): H0 = as duas amostras vêm da mesma
  distribuição. p-valor = probabilidade de ver uma diferença tão grande quanto
  a observada SE H0 fosse verdade. p < 0,05 (alfa) → rejeita H0 ("significativo").
  Usa-se Mann-Whitney, e não o t-test do aplicacao_estatistica.py, porque os
  dados do projeto não são normais (assimetria do pH 3,5, da turbidez 16,7).
- p-valor × tamanho de efeito: com 1.400 medições por mês, diferenças mínimas
  viram "significativas". O tamanho de efeito diz se a diferença IMPORTA.
  Aqui: correlação rank-bisserial r = 2·U/(n1·n2) − 1, entre −1 e 1
  (0 = nenhuma tendência; 1 = todo valor de A maior que todo valor de B).
- Correlação: Spearman (por postos, robusta a picos e a relações não lineares)
  ou Pearson (linear). Ela mede associação, e não causa.
- Probabilidade (Bernoulli): P(evento) = casos / leituras. Probabilidade
  condicional: P(E | C) = casos em que E e C ocorrem juntos / casos de C.

As medições são pareadas pela MESMA leitura (codigo_registro) para correlação e
probabilidade condicional: temperatura e umidade da mesma hora, e não de horas diferentes.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA/estatistica_IA/aplicacao_estatistica.py
Documentação: docs/agente/ferramentas.md § 4.8 a § 4.10
"""
import math
import operator
from collections.abc import Iterable
from datetime import datetime

import pandas as pd
from scipy import stats

from src.agente.ferramentas.base import ErroDeRegra

ALFA = 0.05
MINIMO_POR_GRUPO = 5
MINIMO_PARES = 3
# Turnos: "dia" = 6h às 17h59; "noite" = 18h às 5h59.
HORAS_DIA = range(6, 18)
OPERADORES = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


def formatar_p(p: float) -> float | str:
    """
    p-valor para o retorno: número com 3 casas, ou "<0.001" quando é menor.

    Por quê: o retorno das ferramentas arredonda para 3 casas, e 0.0003 viraria
    0.0, que o LLM poderia apresentar como "p = 0" (falso).

    Example:
        >>> formatar_p(0.0321), formatar_p(0.0003)
        (0.032, '<0.001')
    """
    return "<0.001" if p < 0.001 else round(float(p), 3)


def no_turno(instante: datetime, turno: str) -> bool:
    """
    True se o horário pertence ao turno ("todas", "dia" ou "noite").

    Example:
        >>> from datetime import datetime
        >>> no_turno(datetime(2026, 6, 1, 12), "dia"), no_turno(datetime(2026, 6, 1, 23), "dia"), no_turno(datetime(2026, 6, 1, 3), "noite")
        (True, False, True)
    """
    if turno == "todas":
        return True
    diurno = instante.hour in HORAS_DIA
    return diurno if turno == "dia" else not diurno


def interpretar_efeito(efeito: float) -> str:
    """
    Faixas usuais do tamanho de efeito rank-bisserial (|r|).

    Example:
        >>> [interpretar_efeito(v) for v in (0.05, -0.2, 0.4, 0.9)]
        ['desprezível', 'pequeno', 'médio', 'grande']
    """
    absoluto = abs(efeito)
    if absoluto < 0.1:
        return "desprezível"
    if absoluto < 0.3:
        return "pequeno"
    return "médio" if absoluto < 0.5 else "grande"


def interpretar_correlacao(r: float | None) -> str:
    """
    Força e sentido da correlação (|r| < 0,1 desprezível; até 0,3 fraca; até 0,5 moderada; acima, forte).

    Example:
        >>> [interpretar_correlacao(v) for v in (0.02, 0.25, -0.45, 0.9, None)]
        ['desprezível', 'fraca positiva', 'moderada negativa', 'forte positiva', 'indefinida (valores constantes)']
    """
    if r is None:
        return "indefinida (valores constantes)"
    absoluto = abs(r)
    if absoluto < 0.1:
        return "desprezível"
    forca = "fraca" if absoluto < 0.3 else "moderada" if absoluto < 0.5 else "forte"
    return f"{forca} {'positiva' if r > 0 else 'negativa'}"


def descrever(valores: list[float]) -> dict:
    """
    Resumo de uma amostra: n, média, mediana e desvio padrão amostral.

    Example:
        >>> descrever([1.0, 2.0, 3.0, 4.0])
        {'n': 4, 'media': 2.5, 'mediana': 2.5, 'desvio_padrao': 1.2909944487358056}
    """
    serie = pd.Series(valores, dtype=float)
    desvio = serie.std()
    return {
        "n": int(serie.count()),
        "media": float(serie.mean()),
        "mediana": float(serie.median()),
        "desvio_padrao": None if math.isnan(desvio) else float(desvio),
    }


def comparar_amostras(a: list[float], b: list[float]) -> dict:
    """
    Mann-Whitney U (bilateral) e tamanho de efeito rank-bisserial entre duas amostras.

    Args:
        a: valores do período A.
        b: valores do período B.

    Returns:
        {"a", "b" (descritivas), "teste", "p_valor", "significativo", "alfa",
        "efeito", "efeito_interpretacao", "sentido"}. efeito > 0 = A tende a ter valores maiores.

    Raises:
        ErroDeRegra: algum grupo com menos de 5 valores.

    Example:
        >>> iguais = comparar_amostras([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6])
        >>> iguais["significativo"], iguais["efeito_interpretacao"]
        (False, 'desprezível')
        >>> deslocadas = comparar_amostras([10, 11, 12, 13, 14, 15], [1, 2, 3, 4, 5, 6])
        >>> deslocadas["significativo"], deslocadas["efeito"], deslocadas["sentido"]
        (True, 1.0, 'A maior que B')
    """
    if min(len(a), len(b)) < MINIMO_POR_GRUPO:
        raise ErroDeRegra(f"amostra pequena demais (A tem {len(a)} valores e B tem {len(b)}; mínimo {MINIMO_POR_GRUPO} em cada)")
    teste = stats.mannwhitneyu(a, b, alternative="two-sided")
    # Conceito: rank-bisserial. U conta quantos pares (a, b) têm a > b (empate = meio).
    efeito = 2 * float(teste.statistic) / (len(a) * len(b)) - 1
    sentido = "sem diferença de posição" if abs(efeito) < 0.1 else ("A maior que B" if efeito > 0 else "A menor que B")
    return {
        "a": descrever(a),
        "b": descrever(b),
        "teste": "Mann-Whitney U (bilateral)",
        "p_valor": formatar_p(float(teste.pvalue)),
        "significativo": bool(teste.pvalue < ALFA),
        "alfa": ALFA,
        "efeito": round(efeito, 3),
        "efeito_interpretacao": interpretar_efeito(efeito),
        "sentido": sentido,
    }


def parear_por_leitura(medicoes: Iterable[dict]) -> pd.DataFrame:
    """
    Tabela com uma linha por leitura (codigo_registro) e uma coluna por parâmetro.

    Example:
        >>> linhas = [{"codigo_registro": "R1", "codigo_parametro": "TIP-TMP", "valor": 20.0},
        ...           {"codigo_registro": "R1", "codigo_parametro": "TIP-UMI", "valor": 80.0}]
        >>> parear_por_leitura(linhas).to_dict("records")
        [{'TIP-TMP': 20.0, 'TIP-UMI': 80.0}]
    """
    tabela = pd.DataFrame(list(medicoes), columns=["codigo_registro", "codigo_parametro", "valor"])
    return tabela.pivot_table(index="codigo_registro", columns="codigo_parametro", values="valor", aggfunc="first").rename_axis(None, axis=1)


def correlacionar(tabela: pd.DataFrame, parametros: list[str], metodo: str) -> list[dict]:
    """
    Correlação de cada par de parâmetros, só com as leituras que têm os dois valores.

    Args:
        tabela: saída de parear_por_leitura().
        parametros: códigos, na ordem pedida.
        metodo: "spearman" ou "pearson".

    Returns:
        Um item por par: {"a", "b", "r", "p_valor", "n", "interpretacao"}.

    Example:
        >>> import pandas as pd
        >>> tabela = pd.DataFrame({"X": [1, 2, 3, 4], "Y": [2, 4, 6, 8], "Z": [8, 6, 4, 2]})
        >>> [(p["b"], p["r"], p["interpretacao"]) for p in correlacionar(tabela, ["X", "Y", "Z"], "pearson")[:2]]
        [('Y', 1.0, 'forte positiva'), ('Z', -1.0, 'forte negativa')]
    """
    funcao = stats.spearmanr if metodo == "spearman" else stats.pearsonr
    pares = []
    for indice, a in enumerate(parametros):
        for b in parametros[indice + 1 :]:
            colunas = [c for c in (a, b) if c in tabela.columns]
            dados = tabela[colunas].dropna() if len(colunas) == 2 else pd.DataFrame()
            n = len(dados)
            if n < MINIMO_PARES:
                pares.append({"a": a, "b": b, "r": None, "p_valor": None, "n": n, "interpretacao": f"poucas leituras com os dois valores (n={n})"})
                continue
            if dados[a].nunique() < 2 or dados[b].nunique() < 2:
                pares.append({"a": a, "b": b, "r": None, "p_valor": None, "n": n, "interpretacao": interpretar_correlacao(None)})
                continue
            resultado = funcao(dados[a], dados[b])
            r = float(resultado.statistic)
            pares.append({"a": a, "b": b, "r": round(r, 3), "p_valor": formatar_p(float(resultado.pvalue)), "n": n, "interpretacao": interpretar_correlacao(r)})
    return pares


def probabilidade(tabela: pd.DataFrame, evento: tuple[str, str, float], condicao: tuple[str, str, float] | None) -> dict:
    """
    P(evento) e, se houver condição, P(evento | condição), por contagem de leituras.

    Args:
        tabela: saída de parear_por_leitura().
        evento: (parâmetro, operador, valor), ex.: ("TIP-CHU", ">", 0).
        condicao: idem, ou None.

    Returns:
        {"p_evento", "n_evento", "casos_evento"} e, com condição,
        {"p_evento_dado_condicao", "n_condicao", "casos_evento_e_condicao"}.

    Example:
        >>> import pandas as pd
        >>> tabela = pd.DataFrame({"CHU": [0, 0, 2, 5], "UMI": [60, 95, 92, 97]})
        >>> resultado = probabilidade(tabela, ("CHU", ">", 0), ("UMI", ">", 90))
        >>> resultado["p_evento"], round(resultado["p_evento_dado_condicao"], 3), resultado["n_condicao"]
        (0.5, 0.667, 3)
    """
    parametro, simbolo, valor = evento
    if parametro not in tabela.columns:
        return {"p_evento": None, "n_evento": 0, "casos_evento": 0}
    medidos = tabela[parametro].dropna()
    casos = int(OPERADORES[simbolo](medidos, valor).sum())
    resultado = {"p_evento": casos / len(medidos) if len(medidos) else None, "n_evento": int(len(medidos)), "casos_evento": casos}
    if condicao is None:
        return resultado
    parametro_c, simbolo_c, valor_c = condicao
    if parametro_c not in tabela.columns:
        return {**resultado, "p_evento_dado_condicao": None, "n_condicao": 0, "casos_evento_e_condicao": 0}
    juntos = tabela[[parametro, parametro_c]].dropna()
    com_condicao = juntos[OPERADORES[simbolo_c](juntos[parametro_c], valor_c)]
    casos_juntos = int(OPERADORES[simbolo](com_condicao[parametro], valor).sum())
    return {
        **resultado,
        "p_evento_dado_condicao": casos_juntos / len(com_condicao) if len(com_condicao) else None,
        "n_condicao": int(len(com_condicao)),
        "casos_evento_e_condicao": casos_juntos,
    }
