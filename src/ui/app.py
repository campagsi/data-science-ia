"""Aplicacao web Flask para ingestao e visualizacao ambiental."""
from __future__ import annotations

import csv
import io
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, url_for

from main import iniciar_aplicacao, run_pipeline
from src.config import load_config
from src.database.connection import DatabaseConnection
from src.repository.leitura_repository import LeituraRepository
from src.services.analytics_service import AnaliticsService
from src.ui.visualizacao import (
    FILTROS_TEMPLATE,
    OPCOES_POR_PAGINA,
    agregar_por_hora,
    ler_inteiro,
    ler_por_pagina,
    paginar,
)

# As medições do banco são relidas no máximo a cada 2 minutos (ou após uma
# ingestão): trocar de página ou de período não repete a consulta inteira.
TTL_CACHE_SEGUNDOS = 120
MAXIMO_RECORTES_EM_CACHE = 16
ANALISE_VAZIA = {"leituras": 0, "medicoes": 0, "estatisticas": [], "anomalias": []}


class _CacheMedicoes:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._medicoes: list[dict[str, Any]] | None = None
        self._lido_em = 0.0
        self._analises: OrderedDict[tuple, dict[str, Any]] = OrderedDict()

    def medicoes(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._medicoes is None or time.monotonic() - self._lido_em > TTL_CACHE_SEGUNDOS:
                settings = load_config()
                self._medicoes = LeituraRepository(
                    DatabaseConnection(settings.azure_sql_connectionstring)
                ).get_medicoes()
                self._lido_em = time.monotonic()
                self._analises.clear()
            return self._medicoes

    def analise(self, chave: tuple, selecionadas: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if chave in self._analises:
                self._analises.move_to_end(chave)
                return self._analises[chave]
        analise = AnaliticsService.analisar_medicoes(selecionadas) if selecionadas else ANALISE_VAZIA
        with self._lock:
            self._analises[chave] = analise
            while len(self._analises) > MAXIMO_RECORTES_EM_CACHE:
                self._analises.popitem(last=False)
        return analise

    def limpar(self) -> None:
        with self._lock:
            self._medicoes = None
            self._analises.clear()


cache = _CacheMedicoes()


def limpar_cache() -> None:
    """Descarta as medições em memória (usado após a ingestão e nos testes)."""
    cache.limpar()


def create_app() -> Flask:
    application = Flask(__name__)
    application.jinja_env.filters.update(FILTROS_TEMPLATE)

    def carregar() -> tuple[list[dict[str, Any]], bool]:
        try:
            return cache.medicoes(), False
        except Exception:
            application.logger.exception("Falha ao carregar medicoes do banco.")
            return [], True

    @application.get("/")
    def dashboard():
        medicoes, erro_banco = carregar()
        filtros = _Filtros(request.args)
        selecionadas = _filtrar(medicoes, filtros)
        analise = cache.analise(filtros.chave, selecionadas)

        estacoes = sorted(
            {
                (str(row["estacao_id"]), row["estacao_codigo"], row["estacao"])
                for row in medicoes
            },
            key=lambda row: (row[1], row[2]),
        )
        parametros = sorted(
            {
                (row["codigo_parametro"], row["parametro"], row["unidade_medida"])
                for row in medicoes
            },
            key=lambda row: (row[1], row[0]),
        )
        parametros_no_recorte = sorted(
            {
                (row["codigo_parametro"], row["parametro"], row["unidade_medida"])
                for row in selecionadas
            },
            key=lambda row: (row[1], row[0]),
        )

        por_pagina = ler_por_pagina(request.args.get("por_pagina"))
        # Tabela de medições: mais recentes primeiro.
        recentes = sorted(selecionadas, key=lambda row: _iso_datetime(row["data_hora"]), reverse=True)
        pagina_medicoes = paginar(recentes, ler_inteiro(request.args.get("pagina"), 1), por_pagina)
        pagina_alertas = paginar(
            analise["anomalias"], ler_inteiro(request.args.get("pagina_alertas"), 1), por_pagina
        )
        pagina_estatisticas = paginar(
            analise["estatisticas"], ler_inteiro(request.args.get("pagina_estatisticas"), 1), por_pagina
        )

        periodo = None
        if selecionadas:
            datas = [_iso_datetime(row["data_hora"]) for row in selecionadas]
            periodo = (min(datas)[:10], max(datas)[:10])

        def url_pagina(nome: str, numero: int, ancora: str) -> str:
            argumentos = {**request.args.to_dict(), nome: numero}
            return url_for("dashboard", **argumentos) + f"#{ancora}"

        filtros_url = {
            chave: valor
            for chave, valor in (
                ("estacao", filtros.estacao_id),
                ("parametro", filtros.codigo_parametro),
                ("inicio", filtros.inicio_texto),
                ("fim", filtros.fim_texto),
            )
            if valor
        }
        return render_template(
            "dashboard.html",
            erro_banco=erro_banco,
            erro_filtros=filtros.erro,
            tem_dados=bool(medicoes),
            ultima_data=max((_iso_datetime(row["data_hora"])[:10] for row in medicoes), default=""),
            estacoes=estacoes,
            parametros=parametros,
            parametros_no_recorte=parametros_no_recorte,
            estacao_selecionada=filtros.estacao_id,
            parametro_selecionado=filtros.codigo_parametro,
            inicio=filtros.inicio_texto,
            fim=filtros.fim_texto,
            total_medicoes=len(selecionadas),
            periodo=periodo,
            analise=analise,
            pagina_medicoes=_formatar_pagina(pagina_medicoes),
            pagina_alertas=pagina_alertas,
            pagina_estatisticas=pagina_estatisticas,
            por_pagina=por_pagina,
            opcoes_por_pagina=OPCOES_POR_PAGINA,
            url_pagina=url_pagina,
            url_serie=url_for("serie", **filtros_url),
            url_csv=url_for("exportar_csv", **filtros_url),
        )

    @application.get("/api/serie")
    def serie():
        """
        Série horária de um parâmetro no recorte filtrado, para o gráfico por período.

        Devolve baldes [hora, quantidade, soma, mínimo, máximo] e as anomalias
        [data/hora, valor, alerta] do parâmetro; o navegador reagrega por semana,
        mês ou ano.
        """
        medicoes, erro_banco = carregar()
        if erro_banco:
            return jsonify({"ok": False, "mensagem": "Não foi possível consultar o banco."}), 503

        filtros = _Filtros(request.args)
        codigo = request.args.get("codigo") or filtros.codigo_parametro
        if not codigo:
            return jsonify({"ok": False, "mensagem": "Informe o parâmetro (codigo)."}), 400

        selecionadas = [row for row in _filtrar(medicoes, filtros) if row["codigo_parametro"] == codigo]
        if not selecionadas:
            return jsonify({"ok": True, "codigo": codigo, "parametro": codigo, "unidade": "",
                            "pontos": [], "anomalias": []})

        # A análise é por estação + parâmetro, então restringir ao parâmetro não muda o resultado.
        analise = cache.analise(filtros.chave + (codigo,), selecionadas)
        return jsonify({
            "ok": True,
            "codigo": codigo,
            "parametro": selecionadas[0]["parametro"],
            "unidade": selecionadas[0]["unidade_medida"],
            "estacoes": len({row["estacao_id"] for row in selecionadas}),
            "pontos": agregar_por_hora(selecionadas),
            "anomalias": [
                [_iso_datetime(row["Data"])[:16], row["Valor"], row["Alerta"]]
                for row in analise["anomalias"]
            ],
        })

    @application.get("/exportar.csv")
    def exportar_csv():
        """Todas as medições do recorte filtrado (não só a página exibida)."""
        medicoes, erro_banco = carregar()
        if erro_banco:
            return Response("Não foi possível consultar o banco.", status=503, mimetype="text/plain")

        selecionadas = _filtrar(medicoes, _Filtros(request.args))
        saida = io.StringIO()
        saida.write("﻿")
        escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
        escritor.writerow(["Data e hora", "Registro", "Estação", "Parâmetro", "Unidade", "Valor"])
        for row in sorted(selecionadas, key=lambda row: _iso_datetime(row["data_hora"])):
            escritor.writerow([
                _iso_datetime(row["data_hora"]).replace("T", " ")[:16],
                row["codigo_registro"],
                row["estacao_codigo"],
                row["parametro"],
                row["unidade_medida"],
                f"{float(row['valor']):.3f}".replace(".", ","),
            ])
        return Response(
            saida.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=medicoes_ambientais.csv"},
        )

    @application.post("/ingestao")
    def ingestao():
        try:
            iniciar_aplicacao("ingestao")
            resumo = run_pipeline()
            limpar_cache()
            return jsonify({"ok": True, "resumo": resumo})
        except Exception as error:
            application.logger.exception("Falha na ingestao iniciada pelo dashboard.")
            return jsonify({
                "ok": False,
                "mensagem": f"Ingestão não concluída ({type(error).__name__}). Consulte os logs.",
            }), 500

    return application


class _Filtros:
    def __init__(self, args) -> None:
        self.estacao_id = args.get("estacao", "")
        self.codigo_parametro = args.get("parametro", "")
        self.inicio_texto = args.get("inicio", "")
        self.fim_texto = args.get("fim", "")
        self.erro: str | None = None
        try:
            self.inicio = date.fromisoformat(self.inicio_texto) if self.inicio_texto else None
            self.fim = date.fromisoformat(self.fim_texto) if self.fim_texto else None
            if self.inicio and self.fim and self.inicio > self.fim:
                raise ValueError("A data inicial deve ser anterior ou igual à data final.")
        except ValueError:
            self.inicio = self.fim = None
            self.inicio_texto = self.fim_texto = ""
            self.erro = "Informe um período válido, com a data inicial antes da final."

    @property
    def chave(self) -> tuple:
        return (self.estacao_id, self.codigo_parametro, self.inicio, self.fim)


def _filtrar(medicoes: list[dict[str, Any]], filtros: _Filtros) -> list[dict[str, Any]]:
    return [
        row for row in medicoes
        if (not filtros.estacao_id or str(row["estacao_id"]) == filtros.estacao_id)
        and (not filtros.codigo_parametro or row["codigo_parametro"] == filtros.codigo_parametro)
        and (filtros.inicio is None or _data(row["data_hora"]) >= filtros.inicio)
        and (filtros.fim is None or _data(row["data_hora"]) <= filtros.fim)
    ]


def _formatar_pagina(pagina):
    """Converte data/hora para texto só nas linhas da página exibida."""
    return replace(pagina, itens=[
        {**row, "data_hora": _iso_datetime(row["data_hora"])} for row in pagina.itens
    ])


def _data(value: datetime | str) -> date:
    return value.date() if isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def _iso_datetime(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


app = create_app()
