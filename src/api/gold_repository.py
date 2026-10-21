import os
import threading
from pathlib import Path

import pandas as pd

# Arquivos gerados por Extracao_Dados.extrair_dados_gold (modelo estrela).
TABELAS_GOLD = {
    "estacoes": "estacoes.parquet",
    "parametros": "parametros.parquet",
    "tempo": "tempo.parquet",
    "medicoes": "medicoes.parquet",
}


class GoldIndisponivelError(RuntimeError):
    """A camada Gold ainda não foi gerada ou um arquivo não pode ser lido."""


class GoldRepository:
    """Lê as tabelas Parquet da camada Gold do Data Lake.

    Cada tabela fica em memória e só é relida quando o arquivo muda no disco
    (data de modificação ou tamanho), ou seja, depois de uma nova execução do
    pipeline. Assim as requisições do BI não releem o Parquet a cada chamada.
    """

    def __init__(self, diretorio_gold: Path | str | None = None) -> None:
        """Define a pasta da camada Gold.

        Args:
            diretorio_gold: Pasta com os arquivos Parquet. Se omitida, usa a
                variável de ambiente ``DIRETORIO_GOLD`` ou ``data_lake/gold``.
        """
        self.__diretorio = Path(
            diretorio_gold or os.getenv("DIRETORIO_GOLD") or "data_lake/gold"
        )
        self.__lock = threading.Lock()
        self.__cache: dict[str, tuple[tuple[int, int], pd.DataFrame]] = {}

    def ler(self, tabela: str) -> pd.DataFrame:
        """Devolve a tabela da Gold (estacoes, parametros, tempo ou medicoes).

        Raises:
            KeyError: Se a tabela não pertencer à camada Gold.
            GoldIndisponivelError: Se o arquivo não existir ou estiver inválido.
        """
        caminho = self.__diretorio / TABELAS_GOLD[tabela]
        try:
            info = caminho.stat()
        except FileNotFoundError as error:
            raise GoldIndisponivelError(
                f"Camada Gold não encontrada ({caminho}). Execute o pipeline antes."
            ) from error

        versao = (info.st_mtime_ns, info.st_size)
        with self.__lock:
            em_cache = self.__cache.get(tabela)
            if em_cache and em_cache[0] == versao:
                return em_cache[1]
            try:
                dados = pd.read_parquet(caminho)
            except Exception as error:
                raise GoldIndisponivelError(
                    f"Não foi possível ler {caminho.name}: {error}"
                ) from error
            self.__cache[tabela] = (versao, dados)
            return dados
