"""
Engenharia de atributos para a previsão: o que o modelo sabe no instante t (Fase 10).

Conceito
--------
Um modelo de regressão não "vê" a série: ele recebe uma TABELA. Cada linha é
um instante de referência t, as colunas são os atributos (o que se sabe em t)
e o alvo é o valor h horas depois:

    t                lag_0  lag_2  ...  media_48  hora_sin  sazonal │ alvo (t + 6 h)
    2026-06-10 06:00 21,2   20,1   ...  24,0      1,0       27,5    │ 27,9

- lag_k (defasagem): o valor de k passos atrás (lag_0 = o próprio t, lag_48 = 24 h atrás);
- media_j: média móvel das últimas j leituras, terminando em t;
- hora_sin e hora_cos: a hora do INSTANTE PREVISTO num círculo (23h fica perto
  de 0h, o que um número de 0 a 23 não diz);
- sazonal: o valor na mesma hora do instante previsto, um dia antes.

VAZAMENTO TEMPORAL (data leakage) é usar, sem querer, informação do futuro.
Exemplo: preencher uma lacuna em t pela média de t-1 e t+1 coloca o valor de
t+1 nos atributos de t. Aqui as lacunas são preenchidas só para a frente
(forward fill, com o último valor conhecido, no máximo 2 passos) e todo
atributo usa valores até t. Um teste prova isso trocando o futuro e
conferindo que os atributos não mudam.

Estratégia direta: um modelo por horizonte (1, 3, 6, 12 e 24 h), em vez de
prever 1 h e reaplicar o modelo sobre a própria previsão (o erro se acumularia).

Documentação: docs/agente/todo.md (Fase 10)
"""
import numpy as np
import pandas as pd

from src.previsao.dados import PASSOS_POR_DIA, PASSOS_POR_HORA

DEFASAGENS = (0, 1, 2, 3, 4, 6, 12, 24, 47)
JANELAS = (4, 12, 48)
PREENCHIMENTO_MAXIMO = 2


def montar_atributos(serie: pd.Series, horas: int) -> tuple[pd.DataFrame, pd.Series]:
    """
    Atributos de cada instante t e o alvo (o valor em t + horas).

    Args:
        serie: série regular de 30 em 30 minutos (dados.series_alvo).
        horas: horizonte, de 1 a 24.

    Returns:
        (X, y) com o mesmo índice (o instante t). Linhas com lacunas ficam com
        NaN: remova com linhas_completas().

    Raises:
        ValueError: horizonte fora de 1 a 24 h (o atributo sazonal exige h ≤ 24).

    Example:
        >>> serie = pd.Series(np.arange(100.0), index=pd.date_range("2026-06-01", periods=100, freq="30min"))
        >>> X, y = montar_atributos(serie, horas=1)
        >>> X.loc["2026-06-02 02:00", ["lag_0", "lag_2", "sazonal"]].tolist(), float(y["2026-06-02 02:00"])
        ([52.0, 50.0, 6.0], 54.0)
    """
    if not 1 <= horas <= 24:
        raise ValueError(f"horizonte de {horas} h fora de 1 a 24 h")
    passos = horas * PASSOS_POR_HORA
    # Cuidado: preencher só para a frente (ffill). Interpolar usaria t + 1 nos atributos de t.
    base = serie.ffill(limit=PREENCHIMENTO_MAXIMO)
    atributos = {f"lag_{k}": base.shift(k) for k in DEFASAGENS}
    # Mesma hora do instante previsto, um dia antes: t + passos - 48 (≤ t quando h ≤ 24 h).
    atributos["sazonal"] = base.shift(PASSOS_POR_DIA - passos)
    for janela in JANELAS:
        atributos[f"media_{janela}"] = base.rolling(janela, min_periods=janela // 2).mean()
    previsto = serie.index + pd.Timedelta(minutes=30 * passos)
    hora = previsto.hour + previsto.minute / 60
    atributos["hora_sin"] = pd.Series(np.sin(2 * np.pi * hora / 24), index=serie.index)
    atributos["hora_cos"] = pd.Series(np.cos(2 * np.pi * hora / 24), index=serie.index)
    atributos["dia_semana"] = pd.Series(previsto.dayofweek, index=serie.index, dtype=float)
    # Por quê: o alvo é o valor MEDIDO (sem preenchimento): um alvo preenchido seria
    # "igual ao anterior" e favoreceria o baseline ingênuo de mentira.
    return pd.DataFrame(atributos), serie.shift(-passos).rename("alvo")


def linhas_completas(X: pd.DataFrame, y: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """
    Só as linhas com todos os atributos e o alvo.

    Example:
        >>> X = pd.DataFrame({"a": [1.0, np.nan, 3.0]}); y = pd.Series([1.0, 2.0, np.nan])
        >>> [len(parte) for parte in linhas_completas(X, y)]
        [1, 1]
    """
    validas = X.notna().all(axis=1) & y.notna()
    return X[validas], y[validas]
