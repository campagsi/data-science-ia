"""
Baselines da previsão e as métricas de erro (Fase 10).

Conceito
--------
Baseline = a previsão mais simples possível. Um modelo só vale a pena se errar
MENOS que ela, como no curso: "o modelo tem que bater o baseline".

- ingênuo: o valor previsto é a última medição (lag_0). "Daqui a 1 h vai estar
  como agora." Difícil de bater em 1 h e fácil em 6 h, quando o ciclo do dia já mudou;
- ingênuo sazonal: o valor na mesma hora do instante previsto, um dia antes.
  "Amanhã às 15h vai estar como hoje às 15h." É a referência justa para
  horizontes longos, com ciclo diário forte.

Métricas (as mesmas do modelo_2_ml.py do curso):

    MAE  = média de |real − previsto|            "erro médio, na unidade do parâmetro"
    RMSE = raiz da média de (real − previsto)²   "pune mais os erros grandes"

Ex.: erros de 1, 1 e 4 °C → MAE = 2,0 °C e RMSE = √6 ≈ 2,45 °C. O RMSE bem
maior que o MAE indica alguns erros grandes.

Documentação: docs/agente/ferramentas.md § 4.12
"""
import numpy as np
import pandas as pd

BASELINES = ("ingenuo", "ingenuo_sazonal")


def previsoes_dos_baselines(X: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Previsão de cada baseline, a partir das colunas de atributos (mesmo alinhamento do modelo).

    Example:
        >>> X = pd.DataFrame({"lag_0": [20.0, 21.0], "sazonal": [19.0, 22.0]})
        >>> {nome: serie.tolist() for nome, serie in previsoes_dos_baselines(X).items()}
        {'ingenuo': [20.0, 21.0], 'ingenuo_sazonal': [19.0, 22.0]}
    """
    return {"ingenuo": X["lag_0"], "ingenuo_sazonal": X["sazonal"]}


def mae_e_rmse(real, previsto) -> dict[str, float]:
    """
    MAE e RMSE, arredondados em 4 casas.

    Example:
        >>> mae_e_rmse([10, 10, 10], [11, 9, 14])
        {'mae': 2.0, 'rmse': 2.4495}
    """
    erro = np.asarray(real, dtype=float) - np.asarray(previsto, dtype=float)
    return {"mae": round(float(np.mean(np.abs(erro))), 4), "rmse": round(float(np.sqrt(np.mean(erro**2))), 4)}
