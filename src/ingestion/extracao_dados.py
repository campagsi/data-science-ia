import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from src.logger import logger
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
        nome_saida = "dados_silver.parquet"
        arquivo_silver = os.path.join(self.diretorio_silver, nome_saida)

        logger.info("[Silver] Salvando arquivo...")
        df_silver.to_parquet(
            arquivo_silver, engine="pyarrow", index=False, compression="snappy"
        )

        return registros_validados, parametros

    def extrair_dados_gold(
        self, nome_arquivo_silver: str = "silver_dados_bronze.parquet"
    ):
        logger.info("==== [Gold] Iniciando processamento ====")

        origem = Path(self.diretorio_silver) / nome_arquivo_silver
        destino = Path(self.diretorio_gold)

        logger.info("==== [Gold] Validando arquivo de entrada ====")
        if origem.suffix.lower() != ".parquet":
            raise ValueError("O arquivo Silver deve ser .parquet")

        if not origem.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {origem}")

        logger.info("==== [Gold] Criando diretório de saída ====")
        destino.mkdir(parents=True, exist_ok=True)

        logger.info("==== [Gold] Processando dados ====")
        # Carregar e normalizar uma única vez
        dados_silver = pd.read_parquet(origem)
        medicoes = self._normalizar_medicoes(dados_silver)

        logger.info("[Gold] Criando dimensões e tabela fato...")
        # Criar dimensões
        dim_estacao = self._criar_dim_estacao(dados_silver)
        dim_parametro = self._criar_dim_parametro(medicoes)
        dim_tempo = self._criar_dim_tempo(medicoes)

        # Criar tabela fato
        fato_medicoes = self._criar_fato_medicoes(
            medicoes, dim_estacao, dim_parametro, dim_tempo
        )

        logger.info("[Gold] Centralizando persistência de dados...")
        # Centralizar a persistência
        tabelas = {
            "estacoes.parquet": dim_estacao,
            "parametros.parquet": dim_parametro,
            "tempo.parquet": dim_tempo,
            "medicoes.parquet": fato_medicoes,
        }

        for nome, tabela in tabelas.items():
            tabela.to_parquet(
                destino / nome, engine="pyarrow", compression="snappy", index=False
            )

            logger.info(f"[Gold] {nome}: {len(tabela)} registros salvos.")

        logger.info("==== [Gold] Processamento concluído ====")

        return tabelas

    @staticmethod
    def _converter_itens(valor):
        if isinstance(valor, str):
            valor = json.loads(valor)
        elif isinstance(valor, np.ndarray):
            valor = valor.tolist()

        if not isinstance(valor, list):
            raise ValueError("O campo itens deve conter uma lista JSON.")

        return valor

    def _normalizar_medicoes(self, dados_silver):
        df = dados_silver[["registro_codigo", "estacao_codigo", "itens"]].copy()

        df["itens"] = df["itens"].apply(self._converter_itens)

        df = (
            df.explode("itens", ignore_index=True)
            .dropna(subset=["itens"])
            .reset_index(drop=True)
        )

        if df.empty:
            raise ValueError("Não existem medições para processar.")

        if not df["itens"].map(lambda item: isinstance(item, dict)).all():
            raise ValueError("Cada medição deve ser um dicionário.")

        parametros = pd.json_normalize(df["itens"].tolist())

        medicoes = pd.concat([df.drop(columns=["itens"]), parametros], axis=1)

        medicoes["data_hora_leitura"] = pd.to_datetime(
            medicoes["data_hora_leitura"], errors="raise"
        )

        medicoes["valor_lido"] = pd.to_numeric(medicoes["valor"], errors="raise")

        obrigatorios = [
            "registro_codigo",
            "estacao_codigo",
            "codigo_parametro",
            "data_hora_leitura",
            "valor_lido",
        ]

        if medicoes[obrigatorios].isna().any().any():
            raise ValueError("Existem medições com campos obrigatórios nulos.")

        if not np.isfinite(medicoes["valor_lido"]).all():
            raise ValueError("Existem medições com valores infinitos.")

        return medicoes

    def _atribuir_sks(self, tabela, chave, sk, nome_arquivo):
        if tabela[chave].isna().any():
            raise ValueError(f"Chave nula na coluna {chave}")

        tabela = tabela.drop_duplicates(subset=[chave], keep="last").reset_index(
            drop=True
        )

        caminho = Path(self.diretorio_gold) / nome_arquivo

        if caminho.exists():
            anterior = pd.read_parquet(caminho)

            if (
                anterior[chave].duplicated().any()
                or anterior[sk].duplicated().any()
                or anterior[[chave, sk]].isna().any().any()
            ):
                raise ValueError(
                    f"Dimensão anterior possui chaves inválidas: {nome_arquivo}"
                )

            # Manter SKs antigas e adicionar apenas novas entidades
            novos = tabela[~tabela[chave].isin(anterior[chave])].copy()

            proxima_sk = int(anterior[sk].max()) + 1 if not anterior.empty else 1

            novos.insert(0, sk, range(proxima_sk, proxima_sk + len(novos)))

            return pd.concat([anterior, novos], ignore_index=True)

        # Primeira execução
        tabela.insert(0, sk, range(1, len(tabela) + 1))

        return tabela

    def _criar_dim_estacao(self, dados_silver):
        colunas = [
            "estacao_codigo",
            "estacao_nome",
            "cidade_estado",
            "municipio",
            "estacao_latitude",
            "estacao_longitude",
        ]

        return self._atribuir_sks(
            dados_silver[colunas].copy(),
            chave="estacao_codigo",
            sk="estacao_sk",
            nome_arquivo="estacoes.parquet",
        )

    def _criar_dim_parametro(self, medicoes):
        colunas = ["codigo_parametro", "campo", "unidade_medida"]

        return self._atribuir_sks(
            medicoes[colunas].copy(),
            chave="codigo_parametro",
            sk="parametro_sk",
            nome_arquivo="parametros.parquet",
        )

    def _criar_dim_tempo(self, medicoes):
        datas = medicoes["data_hora_leitura"]

        inicio = datas.min().normalize()
        fim = datas.max().normalize()

        # Preservar também o intervalo temporal já existente
        caminho = Path(self.diretorio_gold) / "tempo.parquet"

        if caminho.exists():
            anterior = pd.read_parquet(caminho)
            datas_anteriores = pd.to_datetime(anterior["data"])

            inicio = min(inicio, datas_anteriores.min().normalize())
            fim = max(fim, datas_anteriores.max().normalize())

        dim = pd.DataFrame({"data": pd.date_range(inicio, fim, freq="D")})

        dim["tempo_sk"] = dim["data"].dt.strftime("%Y%m%d").astype("int64")

        dim["ano"] = dim["data"].dt.year
        dim["mes"] = dim["data"].dt.month
        dim["dia"] = dim["data"].dt.day
        dim["trimestre"] = dim["data"].dt.quarter
        dim["dia_semana"] = dim["data"].dt.dayofweek
        dim["dia_util"] = dim["dia_semana"] < 5

        return dim[
            [
                "tempo_sk",
                "data",
                "ano",
                "mes",
                "dia",
                "trimestre",
                "dia_semana",
                "dia_util",
            ]
        ]

    def _calcular_indicadores(self, fato):
        fato = fato.sort_values(
            ["estacao_sk", "parametro_sk", "data_hora_leitura"], kind="mergesort"
        )

        grupos = []

        for _, grupo in fato.groupby(["estacao_sk", "parametro_sk"], sort=False):
            grupo = grupo.copy()

            # Média móvel temporal de 24 horas
            grupo["media_movel"] = (
                grupo.rolling("24h", on="data_hora_leitura", min_periods=1)[
                    "valor_lido"
                ]
                .mean()
                .to_numpy()
            )

            valores = grupo["valor_lido"]

            # Tratamento específico para precipitação
            if grupo["codigo_parametro"].iloc[0] == "TIP-CHU":
                positivos = valores[valores > 0]

                if len(positivos) >= 30:
                    limite = positivos.quantile(0.99)
                    grupo["indicador_outlier"] = valores > limite
                else:
                    grupo["indicador_outlier"] = False

            else:
                q1 = valores.quantile(0.25)
                q3 = valores.quantile(0.75)
                iqr = q3 - q1

                if len(valores) >= 8 and iqr > 0:
                    inferior = q1 - 1.5 * iqr
                    superior = q3 + 1.5 * iqr

                    grupo["indicador_outlier"] = (valores < inferior) | (
                        valores > superior
                    )
                else:
                    grupo["indicador_outlier"] = False

            grupos.append(grupo)

        return pd.concat(grupos, ignore_index=True)

    def _criar_fato_medicoes(self, medicoes, dim_estacao, dim_parametro, dim_tempo):
        # Relacionar estações
        fato = medicoes.merge(
            dim_estacao[["estacao_codigo", "estacao_sk"]],
            on="estacao_codigo",
            how="left",
            validate="many_to_one",
        )

        # Relacionar parâmetros
        fato = fato.merge(
            dim_parametro[["codigo_parametro", "parametro_sk"]],
            on="codigo_parametro",
            how="left",
            validate="many_to_one",
        )

        # Relacionar tempo
        fato["tempo_sk"] = (
            fato["data_hora_leitura"].dt.strftime("%Y%m%d").astype("int64")
        )

        # Validar integridade referencial
        dimensoes = {
            "estacao_sk": dim_estacao,
            "parametro_sk": dim_parametro,
            "tempo_sk": dim_tempo,
        }

        for sk, dimensao in dimensoes.items():
            if fato[sk].isna().any():
                raise ValueError(f"Chave {sk} contém valores nulos.")

            if not fato[sk].isin(dimensao[sk]).all():
                raise ValueError(f"Relacionamento inválido: {sk}")

        # Evitar leituras duplicadas na fato
        chaves = ["registro_codigo", "estacao_sk", "parametro_sk", "data_hora_leitura"]

        if fato.duplicated(subset=chaves).any():
            raise ValueError("Existem medições duplicadas na tabela fato.")

        # Calcular os indicadores
        fato = self._calcular_indicadores(fato)

        return fato[
            [
                "registro_codigo",
                "estacao_sk",
                "parametro_sk",
                "tempo_sk",
                "data_hora_leitura",
                "valor_lido",
                "media_movel",
                "indicador_outlier",
            ]
        ].copy()

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

    def execute(self):
        self.extrair_dados_bronze(api_result.json())
        self.extrair_dados_silver("dados_bronze.json")
        self.extrair_dados_gold()
