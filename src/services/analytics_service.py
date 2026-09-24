from datetime import date
from typing import ClassVar

import pandas as pd

from src.repository import CidadeRepository, EstacaoRepository, LeituraRepository


class AnaliticsService:
    __COLUNAS_OUTLIERS = (
        "Estação",
        "Variável",
        "Data",
        "Valor",
        "Limite Inferior",
        "Limite Superior",
    )

    __COLUNAS: ClassVar[dict[str, dict[str, str]]] = {
        "meteriologico": (
            "temperatura",
            "pressao",
            "umidade",
            "precipitacao",
            "velocidade_vento",
            "radiacao_solar",
        ),
        "qualidade_agua": (
            "temperatura_agua",
            "ph",
            "oxigenio_dissolvido",
            "condutividade",
            "turbidez",
        ),
    }

    __NOMES: ClassVar[dict[str, dict[str, str]]] = {
        "meteriologico": {
            "temperatura": "Temperatura do ar",
            "umidade": "Umidade relativa do ar",
            "pressao": "Pressão atmosférica ao nível do mar",
            "precipitacao": "Chuva acumulada em 12 horas",
            "velocidade_vento": "Velocidade do vento",
            "direcao_vento": "Direção de origem do vento",
            "radiacao_solar": "Radiação solar",
        },
        "qualidade_agua": {
            "temperatura_agua": "Temperatura da água",
            "ph": "pH",
            "oxigenio_dissolvido": "Oxigênio dissolvido",
            "condutividade": "Condutividade elétrica a 25 °C",
            "turbidez": "Turbidez",
        },
    }

    __UNIDADES: ClassVar[dict[str, dict[str, str]]] = {
        "meteriologico": {
            "temperatura": "°C",
            "umidade": "%",
            "pressao": "hPa",
            "precipitacao": "mm",
            "velocidade_vento": "km/h",
            "radiacao_solar": "W/m²",
        },
        "qualidade_agua": {
            "temperatura_agua": "°C",
            "ph": "ph",
            "oxigenio_dissolvido": "mg/L",
            "condutividade": "µS/cm",
            "turbidez": "NTU",
        },
    }

    def __init__(self) -> None:
        self.__leitura_repository = LeituraRepository()
        self.__cidade_repository = CidadeRepository()
        self.__estacao_repository = EstacaoRepository()

    def __preparar_dataframe(self, dados: list[dict], tipo=str) -> pd.DataFrame:
        df = pd.DataFrame(dados or [])

        if df.empty:
            return df

        colunas = list(self.__COLUNAS[tipo])

        # Converte somente as medições, preservando data_hora.
        df[colunas] = df[colunas].apply(
            pd.to_numeric,
            errors="coerce",
        )

        return df

    def __analisar_leituras(self, df: pd.DataFrame, tipo="") -> dict:
        if df.empty:
            return "Não há dados a serem analisados.\nLeituras: 0\nEstatisticas: []"

        colunas = self.__COLUNAS[tipo]
        nomes = self.__NOMES[tipo]
        unidades = self.__UNIDADES[tipo]

        resumo = df[list(colunas)].agg(["count", "mean", "median", "std"]).T.round(2)

        resumo = resumo.rename(
            columns={
                "count": "Quantidade",
                "mean": "Média",
                "median": "Mediana",
                "std": "Desvio Padrão",
            }
        )

        resumo.rename_axis("variavel").reset_index()

        resumo = resumo.rename_axis("variavel").reset_index()
        # Faz o mapeamento antes de substituir os nomes originais.
        resumo.insert(1, "Unidade", resumo["variavel"].map(unidades))
        resumo["variavel"] = resumo["variavel"].replace(nomes)

        resumo = resumo.rename(columns={"variavel": "Medição"})
        resumo["Quantidade"] = resumo["Quantidade"].astype(int)

        resumo = resumo.astype(object).where(resumo.notna(), None)

        return {
            "Quantide Leituras": len(df),
            "Estatísticas": resumo.to_dict(orient="records"),
        }

    def __identificar_outliers(self, df: pd.DataFrame, tipo: str) -> pd.DataFrame:
        colunas_resultado = list(self.__COLUNAS_OUTLIERS)
        colunas = self.__COLUNAS[tipo]

        if df.empty:
            return pd.DataFrame(columns=colunas_resultado)

        valores = df[list(colunas)]

        # Verifica se existe pelo menos 4 valores válidos por variável
        valores = valores.loc[:, valores.count() >= 4]

        if valores.empty:
            return pd.DataFrame(columns=colunas_resultado)

        # Calcula os limites
        q1 = valores.quantile(0.25)
        q3 = valores.quantile(0.75)

        iqr = q3 - q1

        limite_inferior = q1 - 1.5 * iqr
        limite_superior = q3 + 1.5 * iqr

        # Transforma as colunas de medições em linhas.
        registros = valores.copy()

        registros["Data"] = df["data_hora"]
        id_vars = ["Data"]
        colunas_resultado = list(self.__COLUNAS_OUTLIERS)

        if "estacao" in df.columns:
            registros["Estação"] = df["estacao"]
            id_vars.append("Estação")
        else:
            colunas_resultado.remove("Estação")

        registros = registros.melt(
            id_vars=id_vars,
            var_name="Variável",
            value_name="Valor",
        )

        # Associa cada variável aos seus limites.
        registros["Limite Inferior"] = registros["Variável"].map(limite_inferior)
        registros["Limite Superior"] = registros["Variável"].map(limite_superior)

        mascara = (registros["Valor"] < registros["Limite Inferior"]) | (
            registros["Valor"] > registros["Limite Superior"]
        )

        return (
            registros.loc[mascara, colunas_resultado]
            .sort_values(["Variável", "Data", "Valor"])
            .reset_index(drop=True)
        )

    def analisar_leituras_meteriologicas_cidade(
        self,
        cidade_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> tuple[dict, pd.DataFrame]:
        dados = self.__leitura_repository.get_leituras_meteorologicas_by_cidade(
            cidade_id,
            data_inicio,
            data_fim,
        )

        tipo = "meteriologico"

        df = self.__preparar_dataframe(dados, tipo)

        estatisticas = self.__analisar_leituras(df, tipo)
        outliers = self.__identificar_outliers(df, tipo)

        return estatisticas, outliers

    def analisar_leituras_qualidade_agua_cidade(
        self,
        cidade_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> tuple[dict, pd.DataFrame]:
        dados = self.__leitura_repository.get_leituras_qualidade_agua_by_cidade(
            cidade_id,
            data_inicio,
            data_fim,
        )

        tipo = "qualidade_agua"

        df = self.__preparar_dataframe(dados, tipo)

        estatisticas = self.__analisar_leituras(df, tipo)
        outliers = self.__identificar_outliers(df, tipo)

        return estatisticas, outliers

    def analisar_leituras_meteriologicas_estacao(
        self,
        estacao_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> tuple[dict, pd.DataFrame]:
        dados = self.__leitura_repository.get_leituras_meteorologicas_by_estacao(
            estacao_id,
            data_inicio,
            data_fim,
        )

        tipo = "meteriologico"
        print(self.__UNIDADES[tipo])

        df = self.__preparar_dataframe(dados, tipo)

        estatisticas = self.__analisar_leituras(df, tipo)
        outliers = self.__identificar_outliers(df, tipo)

        return estatisticas, outliers

    def analisar_leituras_qualidade_agua_estacao(
        self,
        estacao_id: int,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> tuple[dict, pd.DataFrame]:
        dados = self.__leitura_repository.get_leituras_qualidade_agua_by_estacao(
            estacao_id,
            data_inicio,
            data_fim,
        )

        tipo = "qualidade_agua"

        df = self.__preparar_dataframe(dados, tipo)

        estatisticas = self.__analisar_leituras(df, tipo)
        outliers = self.__identificar_outliers(df, tipo)

        return estatisticas, outliers

    def buscar_estacoes(self):
        result = self.__estacao_repository.get_all()
        return result

    def bucar_cidades(self):
        result = self.__cidade_repository.get_all()
        return result

    def calculate_metrics(
        self,
        cidade_id: int | None = None,
        estacao_id: int | None = None,
        data_inicio: date | None = None,
        data_fim: date | None = None,
    ) -> dict:
        """Consolida as análises existentes por cidade ou por estação."""
        if cidade_id is None and estacao_id is None:
            raise ValueError("Informe cidade_id ou estacao_id para calcular as métricas.")
        if cidade_id is not None and estacao_id is not None:
            raise ValueError("Informe somente um escopo de análise.")

        if cidade_id is not None:
            analise_meteorologica = self.analisar_leituras_meteriologicas_cidade(
                cidade_id, data_inicio, data_fim
            )
            analise_qualidade_agua = self.analisar_leituras_qualidade_agua_cidade(
                cidade_id, data_inicio, data_fim
            )
            escopo = {"cidade_id": cidade_id}
        else:
            analise_meteorologica = self.analisar_leituras_meteriologicas_estacao(
                estacao_id, data_inicio, data_fim
            )
            analise_qualidade_agua = self.analisar_leituras_qualidade_agua_estacao(
                estacao_id, data_inicio, data_fim
            )
            escopo = {"estacao_id": estacao_id}

        return {
            "escopo": escopo,
            "periodo": {"data_inicio": data_inicio, "data_fim": data_fim},
            "meteorologica": {
                "analise": analise_meteorologica[0],
                "outliers": analise_meteorologica[1],
            },
            "qualidade_agua": {
                "analise": analise_qualidade_agua[0],
                "outliers": analise_qualidade_agua[1],
            },
        }
