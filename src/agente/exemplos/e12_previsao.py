"""
Exemplo 12 — Previsão: validação aleatória × temporal, e modelo × baselines.

Demonstra os dois cuidados centrais da Fase 10:

1. train_test_split ALEATÓRIO × TimeSeriesSplit: o aleatório mistura passado e
   futuro (treina com 10:00 e 11:00 e testa em 10:30), e o MAE sai otimista;
2. modelo × baselines por horizonte: o modelo só vale onde erra menos que o
   ingênuo ("igual a agora") e o ingênuo sazonal ("igual à mesma hora de ontem").

Dados: 60 dias sintéticos de temperatura (ciclo diário + ruído persistente,
como uma frente fria que dura horas), ou as medições do banco com --banco
(AGENTE_SQL_CONNECTIONSTRING, usuário só de leitura).

Como rodar:  python -m src.agente.exemplos.e12_previsao
             python -m src.agente.exemplos.e12_previsao --banco
Observe:     (1) o MAE "aleatório" é menor que o temporal: é o vazamento, e não
             um modelo melhor; (2) o ingênuo é ótimo em 1 h e péssimo em 6 h, e o
             sazonal é o contrário; (3) em que horizonte o modelo vence os dois.

Documentação: docs/agente/todo.md (Fase 10) e docs/agente/ferramentas.md § 4.12
"""
import sys

import numpy as np
import pandas as pd

from src.previsao.atributos import linhas_completas, montar_atributos
from src.previsao.baselines import mae_e_rmse
from src.previsao.dados import series_alvo
from src.previsao.treino import HORIZONTES, avaliar_horizonte, candidatos


def serie_sintetica(dias: int = 60, semente: int = 7) -> pd.Series:
    """Temperatura com ciclo diário (pico às 15h) e ruído AR(1) persistente."""
    indice = pd.date_range("2026-06-01", periods=48 * dias, freq="30min")
    ciclo = 22 + 6 * np.sin(2 * np.pi * (indice.hour + indice.minute / 60 - 9) / 24)
    aleatorio, anomalia, ruidos = np.random.default_rng(semente), 0.0, []
    for _ in indice:
        anomalia = 0.97 * anomalia + aleatorio.normal(0, 0.35)
        ruidos.append(anomalia)
    return pd.Series(ciclo + np.array(ruidos), index=indice, name="TIP-TMP")


def serie_do_banco() -> pd.Series:
    """A série de temperatura da primeira estação, lida com o usuário só de leitura do agente."""
    from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes
    from src.config import load_config_indice
    from src.database.connection import DatabaseConnection

    cfg = load_config_indice()
    consulta = ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))
    series = series_alvo(consulta.medicoes(FiltroMedicoes(parametros=("TIP-TMP",))), ("TIP-TMP",))
    return next(iter(series.values()))


def aleatorio_x_temporal(serie: pd.Series, horas: int = 6) -> tuple[float, float]:
    """MAE do HistGradientBoosting com divisão aleatória e com a divisão temporal (últimos 20%)."""
    from sklearn.model_selection import train_test_split

    X, y = linhas_completas(*montar_atributos(serie, horas))
    fabrica = candidatos()["HistGradientBoosting"]
    Xa, Xb, ya, yb = train_test_split(X, y, test_size=0.2, random_state=0, shuffle=True)
    aleatorio = mae_e_rmse(yb, fabrica().fit(Xa, ya).predict(Xb))["mae"]
    corte = int(len(X) * 0.8)
    temporal = mae_e_rmse(y.iloc[corte:], fabrica().fit(X.iloc[:corte], y.iloc[:corte]).predict(X.iloc[corte:]))["mae"]
    return aleatorio, temporal


def main(argv: list[str]) -> None:
    """Imprime as duas comparações."""
    serie = serie_do_banco() if "--banco" in argv else serie_sintetica()
    print(f"Série: {len(serie)} pontos de 30 min ({serie.index.min():%d/%m} a {serie.index.max():%d/%m}), {int(serie.isna().sum())} lacunas\n")

    aleatorio, temporal = aleatorio_x_temporal(serie)
    print("1. Mesmo modelo (HistGradientBoosting, 6 h), duas formas de validar")
    print(f"   train_test_split aleatório: MAE = {_fmt(aleatorio)} °C   ← otimista: o teste tem vizinhos do treino")
    print(f"   divisão temporal (últimos 20%): MAE = {_fmt(temporal)} °C\n")

    print("2. Modelo × baselines por horizonte (MAE de validação no TimeSeriesSplit)")
    print("   h    modelo                   ingênuo  sazonal  publicado")
    for horas in HORIZONTES:
        a = avaliar_horizonte(serie, "EST", "TIP-TMP", horas, dobras=4, dias_de_teste=7)
        v = a.validacao
        print(f"   {horas:>2} h {a.modelo:<20} {_fmt(v['modelo']['mae']):>5}  {_fmt(v['ingenuo']['mae']):>7}  {_fmt(v['ingenuo_sazonal']['mae']):>7}  "
              f"{'sim' if a.aprovado else 'não supera o baseline'}")


def _fmt(valor: float) -> str:
    """Número com 2 casas e vírgula decimal."""
    return f"{valor:.2f}".replace(".", ",")


if __name__ == "__main__":
    main(sys.argv[1:])
