"""
Perfis diários numéricos: o "dia como vetor" sem texto e sem embeddings (Fase 9).

Conceito
--------
A alternativa ao resumo textual é montar o vetor do dia direto com números:
os 48 valores de temperatura do ar (um a cada 30 minutos, das 00:00 às 23:30).

    01/06  [20,0  20,0  21,0  21,0 ... 32,0 ... 21,0]   → 48 números

1. Lacunas (~2,5% de nulos no dataset) são preenchidas por interpolação linear
   entre os vizinhos. Um dia com menos da metade dos pontos fica de fora.
2. Centralização por dia (subtrai a média do dia): o vetor passa a representar
   o FORMATO da curva, em °C, e não o nível. Um dia frio e um dia quente com o
   mesmo ciclo ficam próximos; um dia nublado, de curva achatada, fica longe de
   um dia de sol, com ciclo grande.
   Cuidado: o z-score por dia (dividir também pelo desvio do dia) APAGA a
   amplitude, e o dia achatado vira a mesma curva do dia de sol (medido no e13).
3. Distância euclidiana entre os vetores, em °C: quanto menor, mais parecidos.

KMeans (o mesmo do modelo_1_ml.py do curso) agrupa os perfis em k formatos
típicos. O k é escolhido pela SILHUETA (de -1 a 1: quanto maior, mais cada dia
está perto do próprio grupo e longe dos outros). A inércia de cada k vai junto,
para o gráfico do cotovelo.

Comparação com o texto (e13): para "dias com o mesmo formato de curva", o vetor
numérico tende a ganhar; para "dias com chuva e anomalias de turbidez", o texto.

Documentação: docs/agente/rag.md § 8
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

PONTOS_POR_DIA = 48
PARAMETRO_PERFIL = "TIP-TMP"
MINIMO_PONTOS = PONTOS_POR_DIA // 2


def perfis_diarios(medicoes: list[dict], parametro: str = PARAMETRO_PERFIL) -> dict[tuple[str, date], np.ndarray]:
    """
    (estação, dia) → vetor de 48 pontos do parâmetro, centralizado na média do dia.

    Example:
        >>> from datetime import datetime, timedelta
        >>> inicio = datetime(2026, 6, 1)
        >>> medicoes = [{"estacao_codigo": "EST-1", "codigo_parametro": "TIP-TMP", "valor": 20 + i % 48 // 4,
        ...              "data_hora": inicio + timedelta(minutes=30 * i)} for i in range(96) if i != 10]
        >>> perfis = perfis_diarios(medicoes)
        >>> sorted(perfis), perfis[("EST-1", date(2026, 6, 1))].shape
        ([('EST-1', datetime.date(2026, 6, 1)), ('EST-1', datetime.date(2026, 6, 2))], (48,))
        >>> round(float(perfis[("EST-1", date(2026, 6, 1))].mean()), 6), float(perfis[("EST-1", date(2026, 6, 1))].max())
        (0.0, 5.5)
    """
    tabela = pd.DataFrame([m for m in medicoes if m["codigo_parametro"] == parametro])
    if tabela.empty:
        return {}
    instantes = pd.to_datetime(tabela["data_hora"])
    tabela["dia"] = instantes.dt.date
    tabela["ponto"] = instantes.dt.hour * 2 + instantes.dt.minute // 30
    perfis = {}
    for (estacao, dia), linhas in tabela.groupby(["estacao_codigo", "dia"], sort=True):
        por_ponto = linhas.groupby("ponto")["valor"].mean()
        if len(por_ponto) < MINIMO_PONTOS:
            continue
        # Conceito: interpolação linear. Um ponto que falta recebe o valor da reta
        # entre os vizinhos conhecidos (nas pontas, repete o mais próximo).
        curva = np.interp(np.arange(PONTOS_POR_DIA), por_ponto.index.to_numpy(), por_ponto.to_numpy())
        perfis[(estacao, dia)] = curva - curva.mean()
    return perfis


def vizinhos_por_perfil(perfis: dict[tuple[str, date], np.ndarray], estacao: str, dia: date, top_k: int) -> list[tuple[date, float]]:
    """
    Os top_k dias da mesma estação com a menor distância euclidiana ao dia pedido.

    Raises:
        KeyError: o dia não tem perfil (sem dados ou com pontos de menos).

    Example:
        >>> perfis = {("E", date(2026, 6, d)): np.array(v, dtype=float) for d, v in ((1, [0, 1]), (2, [0, 1.1]), (3, [1, 0]))}
        >>> [(d.day, round(dist, 2)) for d, dist in vizinhos_por_perfil(perfis, "E", date(2026, 6, 1), 2)]
        [(2, 0.1), (3, 1.41)]
    """
    referencia = perfis[(estacao, dia)]
    distancias = [
        (outro_dia, float(np.linalg.norm(vetor - referencia)))
        for (outra_estacao, outro_dia), vetor in perfis.items()
        if outra_estacao == estacao and outro_dia != dia
    ]
    return sorted(distancias, key=lambda par: (par[1], par[0]))[:top_k]


@dataclass(frozen=True)
class Agrupamento:
    """
    Resultado do KMeans sobre os perfis.

    Args:
        k: quantidade de grupos escolhida (a de maior silhueta).
        rotulos: grupo de cada perfil, na ordem da matriz.
        silhuetas: k → silhueta média.
        inercias: k → inércia (soma das distâncias ao quadrado ao centro do grupo).

    Example:
        >>> Agrupamento(2, np.array([0, 1]), {2: 0.8}, {2: 1.5}).k
        2
    """

    k: int
    rotulos: np.ndarray
    silhuetas: dict[int, float]
    inercias: dict[int, float]


def agrupar_perfis(matriz: np.ndarray, ks: Sequence[int] = range(2, 7), semente: int = 0) -> Agrupamento:
    """
    KMeans para cada k, escolhendo o de maior silhueta.

    Raises:
        ValueError: menos perfis do que o menor k + 1 (a silhueta exige k < n).

    Example:
        >>> matriz = np.array([[0, 0], [0, 0.1], [5, 5], [5, 5.1], [10, 0], [10, 0.1]])
        >>> agrupamento = agrupar_perfis(matriz, ks=[2, 3])
        >>> agrupamento.k, len(set(agrupamento.rotulos))
        (3, 3)
    """
    # Por quê: import aqui para quem só usa os resumos não carregar o scikit-learn.
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    validos = [k for k in ks if k < len(matriz)]
    if not validos:
        raise ValueError(f"{len(matriz)} perfis não bastam para agrupar com k em {list(ks)}")
    modelos = {k: KMeans(n_clusters=k, n_init=10, random_state=semente).fit(matriz) for k in validos}
    silhuetas = {k: round(float(silhouette_score(matriz, modelo.labels_)), 4) for k, modelo in modelos.items()}
    melhor = max(silhuetas, key=lambda k: (silhuetas[k], -k))
    return Agrupamento(melhor, modelos[melhor].labels_, silhuetas, {k: round(float(m.inertia_), 4) for k, m in modelos.items()})
