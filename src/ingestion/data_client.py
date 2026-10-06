"""
Coleta resiliente do lote na API (item 3.1 do enunciado).

- queda de conexão, timeout, HTTP 5xx e 429: nova tentativa com espera
  crescente (1 s, 2 s, 4 s...), respeitando o cabeçalho Retry-After do 429;
- rate limiting: no máximo REQUISICOES_POR_MINUTO requisições por minuto,
  contando as novas tentativas;
- resposta vazia (corpo vazio ou lista vazia): WARNING e lote vazio;
- outros erros HTTP (4xx) e resposta fora do contrato: falha sem nova tentativa.
"""
import time
from collections.abc import Callable
from typing import Any

import requests

from src.config import Settings
from src.logger import logger

TENTATIVAS = 4
ESPERA_INICIAL = 1.0
REQUISICOES_POR_MINUTO = 30
TIMEOUT = 30

_STATUS_TRANSITORIOS = {429, 500, 502, 503, 504}


class FonteIndisponivelError(RuntimeError):
    """A API não respondeu depois de todas as tentativas."""


class DataClient:
    def __init__(
        self,
        settings: Settings,
        tentativas: int = TENTATIVAS,
        espera_inicial: float = ESPERA_INICIAL,
        requisicoes_por_minuto: int = REQUISICOES_POR_MINUTO,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.__settings = settings
        self.__tentativas = tentativas
        self.__espera_inicial = espera_inicial
        self.__intervalo_minimo = 60 / requisicoes_por_minuto
        self.__dormir = dormir
        self.__relogio = relogio
        self.__ultima_requisicao: float | None = None

    def fetch_data(self) -> list[dict[str, Any]]:
        """Obtém o dataset exclusivamente pela API configurada."""
        url = f"{self.__settings.fonte_dados.rstrip('/')}/api/v1/data-set"
        resposta = self.__requisitar(url)

        if not resposta.content or not resposta.content.strip():
            logger.warning("A API respondeu sem conteúdo: lote vazio.")
            return []

        try:
            data = resposta.json()
        except ValueError as error:
            raise ValueError("A fonte de dados não devolveu um JSON válido.") from error

        if not isinstance(data, list):
            raise ValueError("A fonte de dados deve devolver uma lista de registros.")

        if not all(isinstance(record, dict) for record in data):
            raise ValueError("Todos os registros da fonte devem ser objetos JSON.")

        if not data:
            logger.warning("A API devolveu uma lista vazia: lote vazio.")
        else:
            logger.info(f"Coleta: {len(data)} registros recebidos da API.")
        return data

    def __requisitar(self, url: str) -> requests.Response:
        """GET com novas tentativas para falhas transitórias e limite por minuto."""
        for tentativa in range(1, self.__tentativas + 1):
            self.__respeitar_limite()
            espera = self.__espera_inicial * 2 ** (tentativa - 1)
            try:
                resposta = requests.get(url, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as error:
                motivo = f"falha de conexão ({type(error).__name__})"
            else:
                if resposta.status_code not in _STATUS_TRANSITORIOS:
                    resposta.raise_for_status()
                    return resposta
                motivo = f"HTTP {resposta.status_code}"
                if resposta.status_code == 429:
                    espera = max(espera, _retry_after(resposta))

            if tentativa == self.__tentativas:
                logger.error(f"API indisponível: {motivo} na tentativa {tentativa} de {self.__tentativas}.")
                raise FonteIndisponivelError(
                    f"A API não respondeu após {self.__tentativas} tentativas ({motivo})."
                )
            logger.warning(
                f"API: {motivo} na tentativa {tentativa} de {self.__tentativas}; "
                f"nova tentativa em {espera:g} s."
            )
            self.__dormir(espera)

        raise AssertionError("inalcançável")

    def __respeitar_limite(self) -> None:
        """Espera o necessário para não passar de REQUISICOES_POR_MINUTO."""
        agora = self.__relogio()
        if self.__ultima_requisicao is not None:
            falta = self.__intervalo_minimo - (agora - self.__ultima_requisicao)
            if falta > 0:
                self.__dormir(falta)
                agora += falta
        self.__ultima_requisicao = agora


def _retry_after(resposta: requests.Response) -> float:
    """Segundos pedidos pelo cabeçalho Retry-After (0 se ausente ou em formato de data)."""
    try:
        return max(0.0, float(resposta.headers.get("Retry-After", 0)))
    except ValueError:
        return 0.0
