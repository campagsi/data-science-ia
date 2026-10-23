"""
Séries temporais dos parâmetros alvo, a partir das medições (Fase 10).

Conceito
--------
Série temporal = valores em ordem de tempo, a intervalos regulares. As leituras
do projeto vêm a cada 30 minutos, então cada série tem 48 pontos por dia:

    2026-06-01 00:00   20,1 °C
    2026-06-01 00:30   19,8 °C
    2026-06-01 01:00   (falta)   ← lacuna: ~2,5% de nulos no dataset

A grade é REGULAR: um instante sem leitura vira NaN, em vez de sumir. Assim
"o valor de 24 h atrás" é sempre 48 posições para trás, sem precisar procurar.

Só os parâmetros com estrutura temporal são alvo de previsão: temperatura do
ar, umidade, temperatura da água e radiação solar. pH, oxigênio, condutividade
e turbidez têm autocorrelação ≈ 0 no dataset (docs/agente/analise.md § 3):
nenhum modelo vence a média.

Documentação: docs/agente/ferramentas.md § 4.12 e docs/agente/todo.md (Fase 10)
"""
import pandas as pd

PARAMETROS_ALVO = ("TIP-TMP", "TIP-UMI", "TIP-TAG", "TIP-RAD")
FREQUENCIA = "30min"
PASSOS_POR_HORA = 2
PASSOS_POR_DIA = 48


def series_alvo(medicoes: list[dict], parametros: tuple[str, ...] = PARAMETROS_ALVO) -> dict[tuple[str, str], pd.Series]:
    """
    (estação, parâmetro) → série regular de 30 em 30 minutos, com NaN nas lacunas.

    Args:
        medicoes: linhas de LeituraRepository.get_medicoes().
        parametros: códigos dos parâmetros alvo.

    Example:
        >>> from datetime import datetime
        >>> medicoes = [{"estacao_codigo": "EST-1", "codigo_parametro": "TIP-TMP", "data_hora": datetime(2026, 6, 1, h, m), "valor": v}
        ...             for h, m, v in ((0, 0, 20.0), (0, 30, 20.5), (1, 30, 21.5))]
        >>> serie = series_alvo(medicoes)[("EST-1", "TIP-TMP")]
        >>> serie.tolist()
        [20.0, 20.5, nan, 21.5]
        >>> str(serie.index[2])
        '2026-06-01 01:00:00'
    """
    tabela = pd.DataFrame([m for m in medicoes if m["codigo_parametro"] in parametros])
    if tabela.empty:
        return {}
    # Conceito: arredondar para a grade de 30 min alinha uma leitura das 00:29:58 com a das 00:30.
    tabela["instante"] = pd.to_datetime(tabela["data_hora"]).dt.round(FREQUENCIA)
    series = {}
    for (estacao, parametro), linhas in tabela.groupby(["estacao_codigo", "codigo_parametro"], sort=True):
        valores = linhas.groupby("instante")["valor"].mean().astype(float)
        grade = pd.date_range(valores.index.min(), valores.index.max(), freq=FREQUENCIA)
        series[(estacao, parametro)] = valores.reindex(grade).rename(parametro)
    return series
