import os
import secrets
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from .bi_service import POR_PAGINA_MAXIMO, POR_PAGINA_PADRAO, BiService, FiltroMedicoes
from .gold_repository import GoldIndisponivelError


def verificar_chave(x_api_key: str | None = Header(default=None)) -> None:
    """Exige o header ``X-API-Key`` quando ``CHAVE_API_BI`` está configurada.

    Sem a variável (uso local), as rotas do BI ficam abertas.
    """
    esperada = os.getenv("CHAVE_API_BI", "")
    if esperada and not secrets.compare_digest(x_api_key or "", esperada):
        raise HTTPException(status_code=401, detail="Chave de API inválida ou ausente.")


def _filtro(
    inicio: date | None = Query(None, description="Data inicial (AAAA-MM-DD), inclusiva."),
    fim: date | None = Query(None, description="Data final (AAAA-MM-DD), inclusiva."),
    estacao_sk: int | None = Query(None, description="Chave da dimensão estação."),
    parametro_sk: int | None = Query(None, description="Chave da dimensão parâmetro."),
    apenas_outliers: bool = Query(False, description="Somente medições marcadas como outlier."),
) -> FiltroMedicoes:
    if inicio and fim and inicio > fim:
        raise HTTPException(status_code=422, detail="inicio deve ser anterior ou igual a fim.")
    return FiltroMedicoes(inicio, fim, estacao_sk, parametro_sk, apenas_outliers)


class BiController:
    """Expõe a camada Gold do Data Lake para o Power BI."""

    def __init__(self, service: BiService | None = None) -> None:
        """Inicializa o controlador e registra as rotas do BI.

        Args:
            service: Serviço de consulta da Gold. Quando não informado, uma
                instância padrão de ``BiService`` é criada.
        """
        self.__service = service or BiService()
        self.router = APIRouter(
            prefix="/api/v1/bi",
            tags=["BI (camada Gold)"],
            dependencies=[Depends(verificar_chave)],
        )
        for caminho, tabela, resumo in (
            ("/estacoes", "estacoes", "Dimensão estação"),
            ("/parametros", "parametros", "Dimensão parâmetro"),
            ("/tempo", "tempo", "Dimensão tempo (calendário)"),
        ):
            self.router.add_api_route(
                caminho,
                self._rota_dimensao(tabela),
                methods=["GET"],
                response_model=list[dict[str, Any]],
                summary=resumo,
            )
        self.router.add_api_route(
            "/medicoes",
            self.listar_medicoes,
            methods=["GET"],
            response_model=dict[str, Any],
            summary="Fato medições, paginada",
        )
        self.router.add_api_route(
            "/medicoes/diarias",
            self.medicoes_diarias,
            methods=["GET"],
            response_model=list[dict[str, Any]],
            summary="Medições agregadas por dia, estação e parâmetro",
        )

    def _rota_dimensao(self, tabela: str):
        def listar() -> list[dict[str, Any]]:
            return self._executar(self.__service.listar_dimensao, tabela)

        listar.__name__ = f"listar_{tabela}"
        return listar

    def listar_medicoes(
        self,
        filtro: FiltroMedicoes = Depends(_filtro),
        pagina: int = Query(1, ge=1),
        por_pagina: int = Query(POR_PAGINA_PADRAO, ge=1, le=POR_PAGINA_MAXIMO),
    ) -> dict[str, Any]:
        """Retorna uma página da fato medições no recorte informado."""
        return self._executar(self.__service.listar_medicoes, filtro, pagina, por_pagina)

    def medicoes_diarias(
        self, filtro: FiltroMedicoes = Depends(_filtro)
    ) -> list[dict[str, Any]]:
        """Retorna as medições agregadas por dia no recorte informado."""
        return self._executar(self.__service.medicoes_diarias, filtro)

    @staticmethod
    def _executar(funcao, *args):
        """Converte a ausência da camada Gold em HTTP 503."""
        try:
            return funcao(*args)
        except GoldIndisponivelError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
