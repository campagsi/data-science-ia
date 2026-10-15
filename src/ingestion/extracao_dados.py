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

    def execute(self):
        result = api_result.json()
        self.extrair_dados_bronze(result)
        self.extrair_dados_silver("dados_bronze.json")
