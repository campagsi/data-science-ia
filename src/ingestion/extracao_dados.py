import json
import os
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from pydantic import BaseModel

from src.logger import logger, registrar_resultados_validacao
from src.repository.estado_repository import EstadoRepository
from src.repository.parametro_repository import ParametroRepository
from src.services.normalization_service import NormalizationService
from src.services.parametro_service import ParametroService
from src.services.validation_service import ValidationService

api_result = requests.get("http://127.0.0.1:8000/api/v1/data-set")


class Extracao_Dados:
    def __init__(self, fonte_dados: str, diretorio_base="data_lake"):
        self.diretorio_base = diretorio_base
        self.diretorio_bronze = os.path.join(diretorio_base, "bronze")
        self.diretorio_silver = os.path.join(diretorio_base, "silver")
        self.diretorio_gold = os.path.join(diretorio_base, "gold")
        self.fonte_dados = fonte_dados
        self._inicializar_diretorios()
        self.normalization_service = NormalizationService()

    def _inicializar_diretorios(self):

        os.makedirs(self.diretorio_bronze, exist_ok=True)
        os.makedirs(self.diretorio_silver, exist_ok=True)
        os.makedirs(self.diretorio_gold, exist_ok=True)

    def extrair_dados_bronze(self, dados):
        if not dados:
            logger.warning("Não há dados a serem importados.")
            return

        logger.info("[Bronze] Realizando a ingestdão de dados para a camada Bronze...")

        logger.info("[Bronze] Realizando validação dos dados...")
        dados_validados, log_erros = ValidationService().validar_contrato(dados)

        registros_validos = []

        for item in dados_validados:
            registro = item.model_dump(mode="json")
            registros_validos.append(
                {
                    "fonte": self.fonte_dados,
                    "data_ingestao": datetime.now(),
                    **registro,
                }
            )

        logger.info("Criando DF...")
        df_bruto_validos = pd.DataFrame(registros_validos)

        if not df_bruto_validos.empty:
            arquivo_saida = os.path.join(self.diretorio_bronze, "dados_bronze.json")

            logger.info("Salvando arquivo JSON...")
            df_bruto_validos.to_json(
                arquivo_saida,
                orient="records",
                indent=4,
                force_ascii=False,
                date_format="iso",
            )

        if len(log_erros) > 0:
            logger.warning("Registros que não atendem o contrato encontrados...")

        logger.info(f"Total de dados válidos: {len(df_bruto_validos)}")
        logger.info(f"Total de Registros inválidos: {len(log_erros)}")
        logger.info(f"Data lake salvo em: {self.diretorio_bronze}")
        return log_erros

    def extrair_dados_silver(self, nome_arquivo_bronze) -> list[dict[str, Any]]:
        logger.info("==== [Silver] ====")
        arquivo_bronze = os.path.join(self.diretorio_bronze, nome_arquivo_bronze)

        logger.info(
            f"[Silver] Validando a existencia do arquivo {nome_arquivo_bronze}..."
        )
        if not os.path.exists(arquivo_bronze):
            raise FileNotFoundError(
                f"Arquivo {nome_arquivo_bronze}.json não encontrado no Data Lake Bronze."
            )

        logger.info(
            f"[Silver] Validando a extenção do arquivo {nome_arquivo_bronze}..."
        )
        extensao_arquivo = os.path.splitext(nome_arquivo_bronze)[1].lower()

        if extensao_arquivo != ".json":
            raise ValueError(
                f'Formato de arquivo não suportado: {extensao_arquivo}. Utlize arquivo ".json"!'
            )

        logger.info(f"[Silver] Realizando leitura do arquivo {nome_arquivo_bronze}...")
        dados_bronze = pd.read_json(arquivo_bronze)

        logger.info("[Silver] Eliminando registros duplicados...")
        registros_bronze = dados_bronze.drop_duplicates(
            subset=["registro_codigo"], keep="last"
        ).to_dict(orient="records")

        logger.info("[Silver] Normalizando registros...")
        registros_normalizados = self.normalization_service.normalize(registros_bronze)

        parametros = ParametroService(ParametroRepository()).sincronizar(
            NormalizationService.descobrir_parametros(registros_normalizados)
        )
        siglas = {estado.sigla for estado in EstadoRepository().get_all()}

        logger.info("[Silver] Realizando Validação...")
        registros_validados = ValidationService(
            faixas=ParametroService.faixas(parametros),
            siglas_estados=siglas,
            parametros_validos=set(parametros),
        ).validate_data(registros_normalizados)

        registros_silver = []

        for i in registros_validados:
            if i["valido"]:
                registros_silver.append(
                    {
                        "fonte": self.fonte_dados,
                        "data_ingestao": datetime.now(),
                        **i["registro"],
                    }
                )

        logger.info("[Silver] Realizando a Criação do DF...")
        df_silver = pd.DataFrame(registros_silver)
        df_silver["itens"] = df_silver["itens"].apply(
            lambda x: json.dumps(x, ensure_ascii=False, default=str)
        )
        nome_saida = f"silver_{os.path.splitext(nome_arquivo_bronze)[0]}.parquet"
        arquivo_silver = os.path.join(self.diretorio_silver, nome_saida)

        logger.info("[Silver] Salvando arquivo...")
        df_silver.to_parquet(
            arquivo_silver, engine="pyarrow", index=False, compression="snappy"
        )

        return registros_validados, parametros

    def extrair_dados_gold(
        self, nome_arquivo_silver: str = "silver_dados_bronze.parquet"
    ):
        logger.info("==== [Gold] ====")
        arquivo_bronze = os.path.join(
            self.diretorio_silver,
        )

        logger.info(
            f"[Silver] Validando a existencia do arquivo {nome_arquivo_silver}..."
        )
        if not os.path.exists(arquivo_bronze):
            raise FileNotFoundError(
                f"Arquivo {nome_arquivo_silver}.json não encontrado no Data Lake Silver."
            )

        logger.info(
            f"[Silver] Validando a extenção do arquivo {nome_arquivo_silver}..."
        )
        extensao_arquivo = os.path.splitext(nome_arquivo_silver)[1].lower()

        if extensao_arquivo != ".parquet":
            raise ValueError(
                f'Formato de arquivo não suportado: {extensao_arquivo}. Utlize arquivo ".parquet"!'
            )

        logger.info(f"[Silver] Realizando leitura do arquivo {nome_arquivo_silver}...")
        dados_silver = pd.read_parquet(arquivo_bronze)
        # df_dim_estacoes = self._criar_df_dim_estacoes(dados_silver)
        # df_dim_tempo = self.criar_df_dim_tempo(dados_silver)
        self._criar_df_dim_parametro(dados_silver)

        # df_dim_estacoes.to_parquet(
        #     os.path.join(self.diretorio_gold, "estacoes.parquet"),
        #     engine="pyarrow",
        #     index=False,
        #     compression="snappy",
        # )

        # Criação do DF de Estações

        # pd.DataFrame([dados_silver.cidade_estado, dados_silver.estacao_codigo])
        # print(df_dim_estacoes)

    def _criar_df_dim_estacoes(self, dados_silver: pd.DataFrame):
        estacoes = (
            dados_silver[
                [
                    "estacao_codigo",
                    "estacao_nome",
                    "cidade_estado",
                    "municipio",
                    "estacao_latitude",
                    "estacao_longitude",
                ]
            ]
            .drop_duplicates(subset="estacao_codigo")
            .reset_index(drop=True)
        )
        estacoes.insert(0, "estacao_sk", range(1, len(estacoes) + 1))
        return estacoes

    def criar_df_dim_tempo(self, arquivo_silver: pd.DataFrame):
        itens = pd.to_datetime(arquivo_silver["data_hora_ciclo"]).dt.date
        dim_tempo = pd.DataFrame(
            {"data": pd.date_range(start=itens.min(), end=itens.max(), freq="D")}
        )

        dim_tempo.insert(
            0, "tempo_sk", dim_tempo["data"].dt.strftime("%Y%m%d").astype(int)
        )
        dim_tempo["ano"] = dim_tempo["data"].dt.year
        dim_tempo["mes"] = dim_tempo["data"].dt.month
        dim_tempo["dia"] = dim_tempo["data"].dt.day
        dim_tempo["trimestre"] = dim_tempo["data"].dt.quarter
        dim_tempo["dia_semana"] = dim_tempo["data"].dt.day_of_week
        dim_tempo["dia_util"] = dim_tempo["dia_semana"] < 5

        return dim_tempo

        # datas = pd.to_dateti  me(
        #     itens.apply(
        #         lambda item: (
        #             item["data_hora_leitura"] if isinstance(item, dict) else None
        #         )
        #     ),
        #     errors="coerce",
        # ).dropna()
        print(dim_tempo)

        # dim_tempo = pd.DataFrame({"data_completa": pd.date_range(start=datas.min())})

    def _criar_df_dim_parametro(self, dados_silver: pd.DataFrame):
        itens = self._tratar_leitura_itens(dados_silver)
        df_dim_parametro = pd.DataFrame(itens)
        df_dim_parametro.drop(columns=["data_hora_leitura", "valor"], inplace=True)

        df_dim_parametro.to_parquet(
            os.path.join(self.diretorio_gold, "as.parquet"),
            engine="pyarrow",
            index=False,
            compression="snappy",
        )

    def _criar_df_fato_medicoes(self):
        pass

    def _tratar_leitura_itens(self, dt_silver: pd.DataFrame):
        # Converter  string JSON em dicionário
        lista_dic_itens = dt_silver["itens"].apply(json.loads)

        itens = lista_dic_itens.explode(ignore_index=True)

        norm_parmetro = (
            pd.json_normalize(itens.tolist())
            .drop_duplicates(subset=["codigo_parametro"], keep="last")
            .to_dict(orient="records")
        )

        return norm_parmetro

    # print(type(i.iloc[0]))
    # df_itens = pd.json_normalize(itens.explode(ignore_index=True).tolist())
    # itens_limpo = df_itens.drop_duplicates(
    #     subset=["codigo_parametro"], keep="last"
    # ).to_dict(orient="records")

    # df_dim_itens = pd.DataFrame(itens_limpo)
    # # df_re = pd.concat([df_itens.drop(col)])
    # print(df_itens)
    # arquivo_saida =

    def execute(self):
        self.extrair_dados_gold()

    #     result = api_result.json()
    #     self.extrair_dados_bronze(result)
    #     self.extrair_dados_silver("dados_bronze.json")
