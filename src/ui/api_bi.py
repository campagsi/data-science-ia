"""Teste da API do Power BI (/api/v1/bi) a partir do dashboard.

O Flask chama a API do lado do servidor: a CHAVE_API_BI não chega ao navegador
e não há CORS entre as portas do Flask e do Uvicorn.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

import requests

ROTAS_BI = {
    "estacoes": "Dimensão estação",
    "parametros": "Dimensão parâmetro",
    "tempo": "Dimensão tempo",
    "medicoes": "Fato medições (paginada)",
    "medicoes/diarias": "Medições por dia",
}
ROTAS_COM_FILTRO = ("medicoes", "medicoes/diarias")
FILTROS = ("inicio", "fim", "estacao_sk", "parametro_sk", "apenas_outliers")
LINHAS_AMOSTRA = 20
TIMEOUT_SEGUNDOS = 60


def url_base() -> str:
    """Servidor da API: o mesmo de FONTE_DADOS, que também serve /api/v1/bi."""
    return (os.getenv("FONTE_DADOS") or "http://127.0.0.1:8000").rstrip("/")


def chave_configurada() -> bool:
    return bool(os.getenv("CHAVE_API_BI"))


def _parametros(rota: str, args) -> dict[str, str]:
    if rota not in ROTAS_COM_FILTRO:
        return {}
    parametros = {nome: args.get(nome) for nome in FILTROS if args.get(nome)}
    if rota == "medicoes":
        parametros.update(
            {nome: args.get(nome) for nome in ("pagina", "por_pagina") if args.get(nome)}
        )
    return parametros


def _detalhe(resposta) -> str:
    try:
        detalhe = resposta.json().get("detail")
    except (ValueError, AttributeError):
        return resposta.reason or "Resposta inesperada da API."
    if isinstance(detalhe, list):  # erros de validação do FastAPI
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detalhe)
    return str(detalhe or resposta.reason)


def consultar(rota: str, args, get: Callable = requests.get) -> dict[str, Any]:
    """Chama uma rota do BI e resume a resposta: status, tempo, total de
    linhas, colunas e uma amostra das primeiras linhas.

    Raises:
        ValueError: Se a rota não pertencer à API do BI.
    """
    if rota not in ROTAS_BI:
        raise ValueError(f"Rota desconhecida: {rota}")

    url = f"{url_base()}/api/v1/bi/{rota}"
    headers = {"X-API-Key": os.environ["CHAVE_API_BI"]} if chave_configurada() else {}
    resultado: dict[str, Any] = {"rota": rota, "descricao": ROTAS_BI[rota], "url": url}

    inicio = time.perf_counter()
    try:
        resposta = get(url, params=_parametros(rota, args), headers=headers, timeout=TIMEOUT_SEGUNDOS)
    except requests.RequestException as error:
        return resultado | {
            "ok": False,
            "status": None,
            "tempo_ms": round((time.perf_counter() - inicio) * 1000),
            "mensagem": (
                f"API indisponível em {url_base()} ({type(error).__name__}). "
                "Inicie com: python -m uvicorn src.api.app:app"
            ),
        }
    resultado |= {
        "status": resposta.status_code,
        "tempo_ms": round((time.perf_counter() - inicio) * 1000),
        "url": resposta.url or url,
    }
    if resposta.status_code != 200:
        return resultado | {"ok": False, "mensagem": _detalhe(resposta)}

    try:
        corpo = resposta.json()
    except ValueError:
        return resultado | {"ok": False, "mensagem": "A API não devolveu JSON."}

    if isinstance(corpo, dict) and "dados" in corpo:
        linhas = corpo["dados"]
        resultado["paginacao"] = {
            chave: corpo.get(chave)
            for chave in ("pagina", "por_pagina", "total", "total_paginas", "tem_proxima")
        }
        resultado["total"] = corpo.get("total", len(linhas))
    else:
        linhas = corpo if isinstance(corpo, list) else []
        resultado["total"] = len(linhas)

    return resultado | {
        "ok": True,
        "linhas": len(linhas),
        "colunas": list(linhas[0]) if linhas else [],
        "amostra": linhas[:LINHAS_AMOSTRA],
    }


def verificar_todas(get: Callable = requests.get) -> list[dict[str, Any]]:
    """Chama cada rota uma vez (a fato com uma linha por página), sem amostra."""
    resultados = []
    for rota in ROTAS_BI:
        args = {"por_pagina": "1"} if rota == "medicoes" else {}
        resultado = consultar(rota, args, get)
        resultado.pop("amostra", None)
        resultados.append(resultado)
    return resultados


def status(get: Callable = requests.get) -> dict[str, Any]:
    """Situação geral para a página: API no ar (/health), rotas do BI e se a
    camada Gold tem dados. Com a API fora do ar, as rotas não são chamadas."""
    inicio = time.perf_counter()
    try:
        resposta = get(f"{url_base()}/health", timeout=5)
        api = {"online": resposta.status_code == 200, "status": resposta.status_code}
    except requests.RequestException as error:
        api = {
            "online": False,
            "status": None,
            "mensagem": (
                f"API indisponível em {url_base()} ({type(error).__name__}). "
                "Inicie com: python -m uvicorn src.api.app:app"
            ),
        }
    api["tempo_ms"] = round((time.perf_counter() - inicio) * 1000)

    rotas = verificar_todas(get) if api["online"] else []
    sem_gold = [r for r in rotas if r.get("status") == 503]
    medicoes = next((r for r in rotas if r["rota"] == "medicoes" and r["ok"]), None)
    return {
        "servidor": url_base(),
        "chave_configurada": chave_configurada(),
        "api": api,
        "rotas": rotas,
        "rotas_ok": sum(r["ok"] for r in rotas),
        "gold_disponivel": bool(rotas) and all(r["ok"] for r in rotas),
        "gold_mensagem": sem_gold[0]["mensagem"] if sem_gold else None,
        "total_medicoes": medicoes["total"] if medicoes else None,
    }
