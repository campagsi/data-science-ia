import logging
import os
from datetime import datetime

import pandas as pd

# ====================================
# CONFIGURAÇÃO DE LOGGING ESTRUTURADO
# ====================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


class Extracao_Dados:
    def __init__(self, diretorio_base="data_lake"):
        self.diretorio_base = diretorio_base
        self.diretorio_bronze = os.path.join(diretorio_base, "bronze")
        self.diretorio_silver = os.path.join(diretorio_base, "silver")
        self.diretorio_gold = os.path.join(diretorio_base, "gold")

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

        logger.info("Realizando validação dos dados...")
        # =================================
        # Validação do Contrato de Dados
        # Implementar aqui
        # dados_validados = retorno_validacao()
        # =================================

        # DF que recebe todos os dados após a validação
        df_bruto = pd.DataFrame(dados)  # Receberá os dados dados_validados
        df_bruto["data_ingestao"] = datetime.now()
        df_bruto["nome_fonte"] = ""  # Informar a fonte

        # ==== Atenção ======
        # df_bruto["is_valid"] = True  # Acrescentado para testes deve ser removido

        logger.info("Realizando separação de dados válidos e inválidos...")
        # Separa os dados Aprovados dos Rejeitados em DFs distintos
        df_bruto_validos = df_bruto.loc[df_bruto["is_valid"].eq(True)].copy()
        df_bruto_invalidos = df_bruto.loc[df_bruto["is_valid"].eq(False)].copy()

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
