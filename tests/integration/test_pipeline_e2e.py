"""
Execução de ponta a ponta de run_pipeline() com o dataset da API e banco de teste.

A coleta HTTP é substituída pela leitura do mesmo arquivo servido pela API
(DatasetRepository), para o teste não depender do servidor uvicorn. Cobre as
conferências da fase 9 de docs/todo-idempotencia.md.
"""
import re
from collections import Counter

import pytest

import main
import src.config as config
from src.api.dataset_repository import DatasetRepository
from src.services.normalization_service import NormalizationService


@pytest.fixture
def pipeline(monkeypatch, database, connection_string, seguranca, logs_temporarios):
    """Prepara run_pipeline() para o banco de teste e devolve o leitor de logs."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", connection_string)
    monkeypatch.setenv("FONTE_DADOS", "http://api-de-teste")
    dataset = DatasetRepository().get_all()
    monkeypatch.setattr(main.DataClient, "fetch_data", lambda self: dataset)
    return logs_temporarios


def test_duas_execucoes_seguidas_geram_o_mesmo_banco(pipeline, contagens, lote, normalizados):
    validos = lote["validos"]
    itens_gravados = sum(len(registro["itens"]) for registro in validos)
    itens_descartados = sum(
        len(registro["itens_invalidos"])
        for registro in lote["resultados"]
        if registro["valido"]
    )
    primeira = main.run_pipeline()
    depois_da_primeira = contagens()
    segunda = main.run_pipeline()

    assert primeira == {
        "recebidos": len(normalizados),
        "rejeitados_na_normalizacao": 0,
        "registros_validos": len(validos),
        "registros_invalidos": len(normalizados) - len(validos),
        "itens_descartados": itens_descartados,
        "leituras_gravadas": len(validos),
        "leituras_substituidas": 0,
        "itens_gravados": itens_gravados,
    }
    assert segunda == dict(primeira, leituras_substituidas=len(validos))
    assert contagens() == depois_da_primeira
    assert any(
        f"Resumo da ingestão: recebidos={len(normalizados)}" in linha
        for linha in pipeline("pipeline")
    )


def test_banco_mais_rejeitados_fecha_com_o_recebido(pipeline, database, normalizados):
    resumo = main.run_pipeline()
    rejeitados = pipeline("rejeitados")

    leituras_rejeitadas = {
        re.search(r"registro=(\S+)", linha).group(1) for linha in rejeitados if "nivel=leitura" in linha
    }
    leituras_no_banco = database.fetch_one("SELECT COUNT(*) FROM dbo.Leituras")[0]
    assert leituras_no_banco + len(leituras_rejeitadas) == resumo["recebidos"]

    # Por parâmetro: itens gravados + itens rejeitados = leituras gravadas
    # (cada leitura válida traz os 11 parâmetros).
    codigo_do_campo = {
        dados["campo"]: codigo
        for codigo, dados in NormalizationService.descobrir_parametros(normalizados).items()
    }
    rejeitados_por_parametro = Counter(
        codigo_do_campo[re.search(r"campo=(\S+)", linha).group(1)]
        for linha in rejeitados
        if "nivel=item" in linha
    )
    gravados_por_parametro = dict(
        database.fetch_all(
            "SELECT P.codigo_parametro, COUNT(*) FROM dbo.Leitura_Itens I "
            "JOIN dbo.Parametros P ON P.id_parametro = I.parametro_id GROUP BY P.codigo_parametro"
        )
    )
    assert len(gravados_por_parametro) == 11
    for codigo, gravados in gravados_por_parametro.items():
        assert gravados + rejeitados_por_parametro[codigo] == leituras_no_banco, codigo


def test_logs_da_carga_nao_contem_dado_pessoal(pipeline):
    main.run_pipeline()
    texto = "\n".join(pipeline("pipeline") + pipeline("rejeitados"))

    for registro in DatasetRepository().get_all():
        for campo in ("operador_cpf", "operador_nome_completo", "operador_email"):
            valor = (registro.get(campo) or "").strip()
            if valor:
                assert valor not in texto, campo
