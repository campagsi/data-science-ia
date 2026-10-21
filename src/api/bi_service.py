import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from .gold_repository import GoldRepository

POR_PAGINA_PADRAO = 5000
POR_PAGINA_MAXIMO = 50000


@dataclass(frozen=True)
class FiltroMedicoes:
    """Recorte aplicado à tabela fato. Datas são inclusivas (dia inteiro)."""

    inicio: date | None = None
    fim: date | None = None
    estacao_sk: int | None = None
    parametro_sk: int | None = None
    apenas_outliers: bool = False


def _registros(tabela: pd.DataFrame) -> list[dict[str, Any]]:
    """Converte o DataFrame em JSON serializável (datas ISO, NaN vira null)."""
    return json.loads(tabela.to_json(orient="records", date_format="iso"))


class BiService:
    """Regras de consulta da camada Gold para o Power BI."""

    def __init__(self, repository: GoldRepository | None = None) -> None:
        """Inicializa o serviço com o repositório da camada Gold.

        Args:
            repository: Repositório usado na leitura. Se omitido, lê a pasta
                padrão da Gold.
        """
        self.__repository = repository or GoldRepository()

    def listar_dimensao(self, tabela: str) -> list[dict[str, Any]]:
        """Devolve uma dimensão completa (estacoes, parametros ou tempo)."""
        return _registros(self.__repository.ler(tabela))

    def listar_medicoes(
        self,
        filtro: FiltroMedicoes,
        pagina: int = 1,
        por_pagina: int = POR_PAGINA_PADRAO,
    ) -> dict[str, Any]:
        """Devolve uma página da tabela fato, das medições mais antigas às mais
        recentes, com os dados de paginação para o BI percorrer as páginas."""
        fato = self._filtrar(filtro).sort_values(
            ["data_hora_leitura", "estacao_sk", "parametro_sk"], kind="mergesort"
        )
        total = len(fato)
        total_paginas = max(1, math.ceil(total / por_pagina))
        inicio = (pagina - 1) * por_pagina
        return {
            "pagina": pagina,
            "por_pagina": por_pagina,
            "total": total,
            "total_paginas": total_paginas,
            "tem_proxima": pagina < total_paginas,
            "dados": _registros(fato.iloc[inicio : inicio + por_pagina]),
        }

    def medicoes_diarias(self, filtro: FiltroMedicoes) -> list[dict[str, Any]]:
        """Agrega a fato por dia, estação e parâmetro: quantidade, média,
        mínimo, máximo e quantidade de outliers."""
        fato = self._filtrar(filtro)
        if fato.empty:
            return []
        diarias = (
            fato.groupby(["tempo_sk", "estacao_sk", "parametro_sk"], sort=True)
            .agg(
                quantidade=("valor_lido", "size"),
                media=("valor_lido", "mean"),
                minimo=("valor_lido", "min"),
                maximo=("valor_lido", "max"),
                outliers=("indicador_outlier", "sum"),
            )
            .reset_index()
        )
        diarias["outliers"] = diarias["outliers"].astype("int64")
        return _registros(diarias)

    def _filtrar(self, filtro: FiltroMedicoes) -> pd.DataFrame:
        fato = self.__repository.ler("medicoes")
        mascara = pd.Series(True, index=fato.index)
        if filtro.inicio:
            mascara &= fato["data_hora_leitura"] >= pd.Timestamp(filtro.inicio)
        if filtro.fim:
            mascara &= fato["data_hora_leitura"] < pd.Timestamp(
                filtro.fim + timedelta(days=1)
            )
        if filtro.estacao_sk is not None:
            mascara &= fato["estacao_sk"] == filtro.estacao_sk
        if filtro.parametro_sk is not None:
            mascara &= fato["parametro_sk"] == filtro.parametro_sk
        if filtro.apenas_outliers:
            mascara &= fato["indicador_outlier"].astype(bool)
        return fato[mascara]
