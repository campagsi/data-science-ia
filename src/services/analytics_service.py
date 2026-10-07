"""
Análise estatística das medições gravadas no modelo 3FN (item 3.4 do enunciado).

Agrupa por estação + parâmetro (um parâmetro tem uma única unidade, então os
grupos nunca misturam unidades) e sinaliza as medições anômalas sem removê-las.
As regras estão em docs/analise-estatistica.md.
"""
from datetime import date
from typing import Any

import pandas as pd

from src.database import DatabaseConnection
from src.models import EstacaoModel
from src.repository import EstacaoRepository, LeituraRepository, MunicipioRepository

# D10: anômala se fora do intervalo IQR ou com |Z| acima do limite.
LIMITE_ZSCORE = 3.0
# Abaixo disso os quartis não são representativos e a regra IQR não é aplicada.
MINIMO_VALORES_IQR = 4

ALERTA_IQR = "IQR"
ALERTA_ZSCORE = "ZSCORE"
ALERTA_AMBOS = "IQR+ZSCORE"


class AnaliticsService:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.__leitura_repository = LeituraRepository(database)
        self.__municipio_repository = MunicipioRepository(database)
        self.__estacao_repository = EstacaoRepository(database)

    def buscar_municipios(self) -> list[dict]:
        """Municípios com estação: [{"id", "nome", "sigla"}]."""
        return self.__municipio_repository.get_com_estacoes()

    def buscar_estacoes(self, municipio_id: int) -> list[EstacaoModel]:
        return self.__estacao_repository.get_by_municipio(municipio_id)

    def buscar_estacao_por_codigo(self, codigo_estacao: str) -> EstacaoModel | None:
        return self.__estacao_repository.get_by_codigo(codigo_estacao)

    def calculate_metrics(
        self,
        estacao_id: int | None = None,
        municipio_id: int | None = None,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> dict[str, Any]:
        """
        Lê as medições do recorte (sem filtro = todas as estações) e devolve
        escopo, período, estatísticas e anomalias (ver analisar_medicoes).
        """
        medicoes = self.__leitura_repository.get_medicoes(
            estacao_id=estacao_id,
            municipio_id=municipio_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )
        escopo = {
            chave: valor
            for chave, valor in (("estacao_id", estacao_id), ("municipio_id", municipio_id))
            if valor is not None
        }
        return {
            "escopo": escopo,
            "periodo": {"data_inicio": data_inicio, "data_fim": data_fim},
            **self.analisar_medicoes(medicoes),
        }

    @staticmethod
    def analisar_medicoes(medicoes: list[dict]) -> dict[str, Any]:
        """
        Estatísticas e anomalias por estação + parâmetro.

        medicoes: linhas de LeituraRepository.get_medicoes().
        Devolve:
        - "leituras": leituras distintas analisadas;
        - "medicoes": quantidade de valores;
        - "estatisticas": uma linha por estação + parâmetro (média, mediana,
          desvio padrão e variância amostrais, Q1, Q3, IQR, mínimo, máximo,
          limites IQR e quantidade de anomalias);
        - "anomalias": uma linha por medição anômala, com o indicador de
          alerta de qualidade (IQR, ZSCORE ou IQR+ZSCORE) e o Z-Score.
        """
        df = pd.DataFrame(medicoes)
        if df.empty:
            return {"leituras": 0, "medicoes": 0, "estatisticas": [], "anomalias": []}

        chaves = ["estacao_codigo", "codigo_parametro"]
        grupos = df.groupby(chaves, sort=True)["valor"]

        resumo = grupos.agg(
            quantidade="count", media="mean", mediana="median", desvio="std",
            variancia="var", minimo="min", maximo="max",
        )
        resumo["q1"] = grupos.quantile(0.25)
        resumo["q3"] = grupos.quantile(0.75)
        resumo["iqr"] = resumo["q3"] - resumo["q1"]
        com_iqr = resumo["quantidade"] >= MINIMO_VALORES_IQR
        resumo["limite_inferior"] = (resumo["q1"] - 1.5 * resumo["iqr"]).where(com_iqr)
        resumo["limite_superior"] = (resumo["q3"] + 1.5 * resumo["iqr"]).where(com_iqr)

        df = df.join(resumo, on=chaves)
        # Desvio zero ou um único valor: Z-Score indefinido (NaN), sem alerta.
        df["zscore"] = (df["valor"] - df["media"]) / df["desvio"].where(df["desvio"] > 0)
        df["fora_iqr"] = (df["valor"] < df["limite_inferior"]) | (df["valor"] > df["limite_superior"])
        df["fora_zscore"] = df["zscore"].abs() > LIMITE_ZSCORE
        df["alerta"] = None
        df.loc[df["fora_iqr"], "alerta"] = ALERTA_IQR
        df.loc[df["fora_zscore"], "alerta"] = ALERTA_ZSCORE
        df.loc[df["fora_iqr"] & df["fora_zscore"], "alerta"] = ALERTA_AMBOS

        anomalas = df[df["alerta"].notna()]
        resumo["anomalias"] = anomalas.groupby(chaves).size().reindex(resumo.index, fill_value=0)
        descricao = df.drop_duplicates(chaves).set_index(chaves)[["estacao", "parametro", "unidade_medida"]]
        resumo = resumo.join(descricao).reset_index()

        estatisticas = [
            {
                "Estação": linha.estacao,
                "Código": linha.codigo_parametro,
                "Parâmetro": linha.parametro,
                "Unidade": linha.unidade_medida,
                "Quantidade": int(linha.quantidade),
                "Média": linha.media,
                "Mediana": linha.mediana,
                "Desvio Padrão": linha.desvio,
                "Variância": linha.variancia,
                "Q1": linha.q1,
                "Q3": linha.q3,
                "IQR": linha.iqr,
                "Mínimo": linha.minimo,
                "Máximo": linha.maximo,
                "Limite Inferior": linha.limite_inferior,
                "Limite Superior": linha.limite_superior,
                "Anomalias": int(linha.anomalias),
            }
            for linha in resumo.itertuples(index=False)
        ]
        anomalias = [
            {
                "Estação": linha.estacao,
                "Parâmetro": linha.parametro,
                "Unidade": linha.unidade_medida,
                "Data": linha.data_hora,
                "Registro": linha.codigo_registro,
                "Valor": linha.valor,
                "Limite Inferior": linha.limite_inferior,
                "Limite Superior": linha.limite_superior,
                "Z-Score": linha.zscore,
                "Alerta": linha.alerta,
            }
            for linha in anomalas.sort_values(chaves + ["data_hora"]).itertuples(index=False)
        ]

        return {
            "leituras": int(df["codigo_registro"].nunique()),
            "medicoes": len(df),
            "estatisticas": [_sem_nan(linha) for linha in estatisticas],
            "anomalias": [_sem_nan(linha) for linha in anomalias],
        }


def _sem_nan(linha: dict) -> dict:
    """Troca NaN por None (valor indefinido, ex.: desvio de um único valor)."""
    return {chave: None if isinstance(valor, float) and pd.isna(valor) else valor for chave, valor in linha.items()}
