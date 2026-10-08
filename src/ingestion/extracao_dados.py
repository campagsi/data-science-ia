import logging
import os
from datetime import datetime

import pandas as pd
import requests
from rich.console import Console

from src.logger import logger
from src.services.normalization_service import NormalizationService
from src.services.validation_service import ValidationService

# ====================================
# CONFIGURAÇÃO DE LOGGING ESTRUTURADO
# ====================================


api_result = requests.get("http://127.0.0.1:8000/api/v1/data-set")


class Extracao_Dados:
    def __init__(self, diretorio_base="data_lake"):
        self.diretorio_base = diretorio_base
        self.diretorio_bronze = os.path.join(diretorio_base, "bronze")
        self.diretorio_silver = os.path.join(diretorio_base, "silver")
        self.diretorio_gold = os.path.join(diretorio_base, "gold")
        self.validation_service = ValidationService()
        self.normalization_service = NormalizationService()

    def _inicializar_diretorios(self):
        os.makedirs(self.diretorio_bronze, exist_ok=True)
        os.makedirs(self.diretorio_silver, exist_ok=True)
        os.makedirs(self.diretorio_gold, exist_ok=True)

    def extrair_dados_bronze(self, data_referencia, dados):
        if not dados:
            logger.warning("Não há dados a serem importados.")
            return

        logger.info(
            f"[Bronze] Realizando a ingestdão de dados para a data: {data_referencia}..."
        )

        logger.info("[Bronze] Realizando a normalização dos dados...")
        dados_normalizados = self.normalization_service.normalize(dados)

        logger.info("[Bronze] Realizando validação dos dados...")
        dados_validados = self.validation_service.validate_data(dados_normalizados)

        registros_validos = []
        log_ingestao = []

        data_ingestao = datetime.now()

        for item in dados_validados:
            registro = item.get("registro") or {}
            registros_validos.append(registro)

            for item_invalido in item.get("itens_invalidos", []):
                log_ingestao.append(
                    {
                        "registro_codigo": registro.get("registro_codigo"),
                        "estacao_codigo": registro.get("estacao_codigo", ""),
                        "estacao_nome": registro.get("estacao_nome"),
                        "data_ingestao": data_ingestao,
                        **item_invalido,
                    }
                )

        nome_da_fonte_dados = ""

        if nome_da_fonte_dados != registros_validos[0]["estacao_nome"]:
            nome_da_fonte_dados = registros_validos[0]["estacao_nome"]

        # DF que recebe todos os dados após a validação
        df_bruto = pd.DataFrame(registros_validos)  # Receberá os dados dados_validados
        df_bruto["data_ingestao"] = datetime.now()
        df_bruto["nome_fonte"] = nome_da_fonte_dados

        # ==== Atenção ======
        # df_bruto["is_valid"] = True  # Acrescentado para testes deve ser removido

        logger.info("Realizando separação de dados válidos e inválidos...")
        # Separa os dados Aprovados dos Rejeitados em DFs distintos
        df_bruto_validos = df_bruto.copy()
        df_bruto_invalidos = pd.DataFrame(log_ingestao)

        if not df_bruto_validos.empty:
            arquivo_saida = os.path.join(
                self.diretorio_bronze, f"cidade_operadora_{data_referencia}.json"
            )

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
            arquivo_saida = os.path.join(
                self.diretorio_bronze, f"log_cidade_operadora_{data_referencia}.csv"
            )
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

    def execute(self):
        result = api_result.json()
        self.extrair_dados_bronze("01_01_206", result)
