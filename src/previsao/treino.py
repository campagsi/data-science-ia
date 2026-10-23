"""
Treino e avaliação do modelo de previsão, com validação temporal (Fase 10, DA10).

Conceito
--------
Validação TEMPORAL: o modelo é sempre avaliado em dados POSTERIORES aos do
treino, como vai ser usado de verdade. O train_test_split aleatório mistura
passado e futuro: o modelo treina com 10:00 e 11:00 e é testado em 10:30, e o
erro sai otimista demais (o e12 mede a diferença).

    TimeSeriesSplit(n_splits=5), com o teste final nas últimas 2 semanas:

    dobra 1  [treino]            [val]
    dobra 2  [treino      ]            [val]
    ...
    dobra 5  [treino                       ]  [val]  │ [teste final]

O gap entre o treino e a validação tem o tamanho do horizonte: o alvo das
últimas linhas do treino (t + h) já cairia dentro da validação.

Para cada parâmetro e horizonte:

1. Pipeline = padronização + regressor, para o mesmo pré-processamento valer
   no treino e na previsão. Compara Ridge (linear, com regularização) e
   HistGradientBoostingRegressor (árvores);
2. o melhor na validação (menor MAE médio) é comparado com os dois baselines;
3. REGRA DE ACEITE: o horizonte só é publicado se o modelo vencer os DOIS
   baselines na validação. Os outros ficam registrados como "não supera o baseline";
4. o teste final, nunca usado nas escolhas, mostra o erro esperado em dados novos;
5. o modelo publicado é retreinado com todos os dados.

Documentação: docs/agente/todo.md (Fase 10) e docs/agente/ferramentas.md § 4.12
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.previsao.atributos import linhas_completas, montar_atributos
from src.previsao.baselines import BASELINES, mae_e_rmse, previsoes_dos_baselines
from src.previsao.dados import PARAMETROS_ALVO, PASSOS_POR_HORA, series_alvo

HORIZONTES = (1, 3, 6, 12, 24)
DOBRAS = 5
DIAS_DE_TESTE = 14
MINIMO_LINHAS = 500


def candidatos() -> dict[str, Callable[[], object]]:
    """
    Os modelos comparados, como fábricas de Pipeline (cada dobra recebe um novo).

    Example:
        >>> sorted(candidatos())
        ['HistGradientBoosting', 'Ridge']
    """
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "Ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "HistGradientBoosting": lambda: make_pipeline(StandardScaler(), HistGradientBoostingRegressor(max_iter=200, random_state=0)),
    }


@dataclass
class AvaliacaoHorizonte:
    """
    Resultado de um parâmetro em um horizonte.

    Args:
        estacao, parametro, horas: o que foi avaliado.
        modelo: nome do melhor candidato na validação.
        aprovado: True se o modelo venceu os dois baselines na validação.
        validacao: {"modelo"|"ingenuo"|"ingenuo_sazonal": {"mae", "rmse"}} médio nas dobras.
        teste: o mesmo, no teste final.
        n_treino, n_teste: linhas usadas.
        periodo: (primeiro, último) instante de referência usado.
        pipeline: o modelo retreinado com todos os dados (só se aprovado).

    Example:
        >>> AvaliacaoHorizonte("EST-1", "TIP-TMP", 6, "Ridge", False, {}, {}, 0, 0, ("", "")).chave
        'EST-1|TIP-TMP|6'
    """

    estacao: str
    parametro: str
    horas: int
    modelo: str
    aprovado: bool
    validacao: dict[str, dict[str, float]]
    teste: dict[str, dict[str, float]]
    n_treino: int
    n_teste: int
    periodo: tuple[str, str]
    pipeline: object = field(default=None, repr=False)

    @property
    def chave(self) -> str:
        """Identificador "estação|parâmetro|horas", usado no metadados.json."""
        return f"{self.estacao}|{self.parametro}|{self.horas}"


def avaliar_horizonte(serie: pd.Series, estacao: str, parametro: str, horas: int, dobras: int = DOBRAS, dias_de_teste: int = DIAS_DE_TESTE) -> AvaliacaoHorizonte | None:
    """
    Valida os candidatos e os baselines num horizonte e, se aprovado, retreina com tudo.

    Returns:
        A avaliação, ou None se não houver linhas suficientes.

    Example:
        >>> indice = pd.date_range("2026-06-01", periods=48 * 40, freq="30min")
        >>> ciclo = 25 + 5 * np.sin(2 * np.pi * (indice.hour + indice.minute / 60) / 24)
        >>> serie = pd.Series(ciclo + np.random.default_rng(0).normal(0, 0.3, len(indice)), index=indice)
        >>> avaliacao = avaliar_horizonte(serie, "EST-1", "TIP-TMP", 6, dobras=3, dias_de_teste=7)
        >>> avaliacao.aprovado, avaliacao.validacao["modelo"]["mae"] < avaliacao.validacao["ingenuo"]["mae"]
        (True, True)
    """
    from sklearn.model_selection import TimeSeriesSplit

    X, y = linhas_completas(*montar_atributos(serie, horas))
    if len(X) < MINIMO_LINHAS:
        return None
    corte = X.index.max() - pd.Timedelta(days=dias_de_teste)
    X_treino, y_treino, X_teste, y_teste = X[X.index <= corte], y[y.index <= corte], X[X.index > corte], y[y.index > corte]
    divisor = TimeSeriesSplit(n_splits=dobras, gap=horas * PASSOS_POR_HORA)

    erros: dict[str, list[dict[str, float]]] = {nome: [] for nome in (*candidatos(), *BASELINES)}
    for indices_treino, indices_validacao in divisor.split(X_treino):
        Xt, yt = X_treino.iloc[indices_treino], y_treino.iloc[indices_treino]
        Xv, yv = X_treino.iloc[indices_validacao], y_treino.iloc[indices_validacao]
        for nome, fabrica in candidatos().items():
            erros[nome].append(mae_e_rmse(yv, fabrica().fit(Xt, yt).predict(Xv)))
        for nome, previsao in previsoes_dos_baselines(Xv).items():
            erros[nome].append(mae_e_rmse(yv, previsao))
    media = {nome: _media(lista) for nome, lista in erros.items()}
    melhor = min(candidatos(), key=lambda nome: media[nome]["mae"])
    aprovado = all(media[melhor]["mae"] < media[baseline]["mae"] for baseline in BASELINES)

    teste = {}
    if len(X_teste):
        final = candidatos()[melhor]().fit(X_treino, y_treino)
        teste = {"modelo": mae_e_rmse(y_teste, final.predict(X_teste))}
        teste |= {nome: mae_e_rmse(y_teste, previsao) for nome, previsao in previsoes_dos_baselines(X_teste).items()}
    return AvaliacaoHorizonte(
        estacao=estacao,
        parametro=parametro,
        horas=horas,
        modelo=melhor,
        aprovado=aprovado,
        validacao={"modelo": media[melhor], **{nome: media[nome] for nome in BASELINES}},
        teste=teste,
        n_treino=len(X_treino),
        n_teste=len(X_teste),
        periodo=(X.index.min().isoformat(), X.index.max().isoformat()),
        # Por quê: o modelo publicado aprende também as últimas semanas (as mais
        # parecidas com o que vem a seguir), depois de avaliado sem elas.
        pipeline=candidatos()[melhor]().fit(X, y) if aprovado else None,
    )


def treinar(medicoes: list[dict], parametros: Sequence[str] = PARAMETROS_ALVO, horizontes: Sequence[int] = HORIZONTES, **opcoes) -> list[AvaliacaoHorizonte]:
    """
    Avalia (e, se aprovado, treina) cada estação × parâmetro × horizonte.

    Args:
        medicoes: linhas de get_medicoes() com os parâmetros alvo.
        parametros: códigos a prever.
        horizontes: horas à frente.
        **opcoes: dobras e dias_de_teste de avaliar_horizonte().

    Returns:
        Uma avaliação por combinação com dados suficientes.

    Example:
        >>> treinar([])
        []
    """
    avaliacoes = []
    for (estacao, parametro), serie in series_alvo(medicoes, tuple(parametros)).items():
        for horas in horizontes:
            avaliacao = avaliar_horizonte(serie, estacao, parametro, horas, **opcoes)
            if avaliacao is not None:
                avaliacoes.append(avaliacao)
    return avaliacoes


def _media(metricas: list[dict[str, float]]) -> dict[str, float]:
    """Média das métricas das dobras."""
    return {chave: round(float(np.mean([m[chave] for m in metricas])), 4) for chave in ("mae", "rmse")}
