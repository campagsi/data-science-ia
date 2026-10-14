import os
from datetime import datetime

import pandas as pd
import requests
from pydantic import BaseModel

from src.logger import logger
from src.services.normalization_service import NormalizationService
from src.services.validation_service import ValidationService

api_result = requests.get("http://127.0.0.1:8000/api/v1/data-set")


class Extracao_Dados:
    def __init__(self, diretorio_base="data_lake"):
        self.diretorio_base = diretorio_base
        self.diretorio_bronze = os.path.join(diretorio_base, "bronze")
        self.diretorio_silver = os.path.join(diretorio_base, "silver")
        self.diretorio_gold = os.path.join(diretorio_base, "gold")
        self._inicializar_diretorios()
        self.validation_service = ValidationService()
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
        dados_validados, log_erros = self.validation_service.validar_contrato(dados)

        registros_validos = []

        for item in dados_validados:
            registro = item.model_dump(mode="json")
            registros_validos.append(
                {
                    "fonte": item.estacao_nome,
                    "data_ingestao": datetime.now(),
                    **registro,
                }
            )

        logger.info("Criando DF...")
        df_bruto_validos = pd.DataFrame(registros_validos)
        df_bruto_invalidos = pd.DataFrame(log_erros)

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

        if not df_bruto_invalidos.empty:
            logger.warning("Dados inválidos encontrados...")
            arquivo_saida = os.path.join(self.diretorio_bronze, "log_dados_bronze.csv")
            logger.info("Salvando arquivo de log...")
            df_bruto_invalidos.to_csv(
                arquivo_saida,
                index=False,
                sep=";",
                encoding="utf-8-sig",
                decimal=",",
                date_format="iso",
            )

        logger.info(f"Total de dados válidos: {len(df_bruto_validos)}")
        logger.info(f"Total de dados inválidos: {len(df_bruto_invalidos)}")
        logger.info(f"Arquivos salvos em: {self.diretorio_bronze}")

    def extrair_dados_silver(self, nome_arquivo_bronze):
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

        logger.info("[Silver] Realizando Validação...")
        registros_validados = self.validation_service.validate_data(
            registros_normalizados
        )

        log = []
        registros_silver = []

        for i in registros_validados:
            registros_silver.append(i["registro"])

            if not i["valido"] or any(
                [i["campos_nulos"], i["itens_invalidos"], i["motivos"]]
            ):
                if i["valido"]:
                    log.append(
                        {
                            "tipo_rejeição": "campo",
                            "itens_invalidos": i["itens_invalidos"],
                            "motivo": i["motivos"],
                        }
                    )
                else:
                    log.append(
                        {
                            "tipo_rejeição": "total",
                            "campos_nulos": i["campos_nulos"],
                            "motivo": i["motivos"],
                        }
                    )

        df_silver = pd.DataFrame(registros_silver)
        nome_saida = f"silver_{os.path.splitext(nome_arquivo_bronze)[0]}.parquet"
        arquivo_silver = os.path.join(self.diretorio_silver, nome_saida)
        logger.info("[SILVER] Salvando arquivo...")
        df_silver.to_parquet(
            arquivo_silver, engine="pyarrow", index=False, compression="snappy"
        )

        if log:
            logger.warning("Alguns campos/registros não foram salvos, verifique o log")

    def execute(self):
        result = api_result.json()
        self.extrair_dados_bronze(result)
        self.extrair_dados_silver("dados_bronze.json")
