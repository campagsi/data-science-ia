"""Fluxo da CLI (fase 16) com entradas simuladas e análise em memória."""
import builtins
import io
from datetime import date, datetime

import pytest
from rich.console import Console

from src.cli.console_app import Console_APP
from src.models import EstacaoModel
from src.services.report_service import ReportService

ESTACAO = EstacaoModel(
    id_estacao=5, codigo_estacao="EST-1", nome="Estação Norte", municipio_id=1, latitude=-22.9, longitude=-43.2,
)
ESTATISTICA = {
    "Estação": "Estação Norte", "Código": "TIP-PH", "Parâmetro": "pH", "Unidade": "pH",
    "Quantidade": 3, "Média": 7.1, "Mediana": 7.0, "Desvio Padrão": 0.1, "Variância": 0.01,
    "Q1": 6.9, "Q3": 7.3, "IQR": 0.4, "Mínimo": 6.8, "Máximo": 7.5,
    "Limite Inferior": 6.3, "Limite Superior": 7.9, "Anomalias": 1,
}
ANOMALIA = {
    "Estação": "Estação Norte", "Parâmetro": "pH", "Unidade": "pH", "Data": datetime(2026, 6, 1, 3),
    "Registro": "R-1", "Valor": 9.1, "Limite Inferior": 6.3, "Limite Superior": 7.9,
    "Z-Score": 3.4, "Alerta": "IQR+ZSCORE",
}


class AnaliseFalsa:
    def __init__(self, estatisticas=(ESTATISTICA,)):
        self.estatisticas = list(estatisticas)
        self.consultas = []

    def buscar_municipios(self):
        return [{"id": 1, "nome": "Rio de Janeiro", "sigla": "RJ"}]

    def buscar_estacoes(self, municipio_id):
        assert municipio_id == 1
        return [ESTACAO]

    def calculate_metrics(self, **filtros):
        self.consultas.append(filtros)
        return {
            "leituras": 3, "medicoes": 3,
            "estatisticas": self.estatisticas,
            "anomalias": [ANOMALIA] if self.estatisticas else [],
        }


def executar(monkeypatch, tmp_path, entradas, analise=None):
    respostas = iter(entradas)
    monkeypatch.setattr(builtins, "input", lambda *args: next(respostas))
    saida = io.StringIO()
    analise = analise or AnaliseFalsa()
    Console_APP(
        analise=analise,
        relatorio=ReportService(),
        console=Console(file=saida, width=250, color_system=None),
        pasta_relatorios=tmp_path / "relatorios",
    ).run()
    return analise, saida.getvalue()


def test_consulta_completa_usa_estacao_e_datas_convertidas(monkeypatch, tmp_path):
    analise, saida = executar(monkeypatch, tmp_path, ["1", "1", "01/06/2026", "30/06/2026", "", "s"])

    assert analise.consultas == [
        {"estacao_id": 5, "data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30)}
    ]
    assert "Rio de Janeiro (RJ)" in saida
    assert "Variância" in saida and "IQR+ZSCORE" in saida
    assert "Saindo..." in saida
    assert not (tmp_path / "relatorios").exists()
    assert "Relatório salvo" not in saida


def test_salvar_relatorio_cria_a_pasta_e_os_csv(monkeypatch, tmp_path):
    _, saida = executar(monkeypatch, tmp_path, ["1", "1", "01/06/2026", "30/06/2026", "0", "", "s"])

    assert (tmp_path / "relatorios" / "estatisticas.csv").exists()
    assert (tmp_path / "relatorios" / "anomalias.csv").exists()
    assert "Relatório salvo" in saida


@pytest.mark.parametrize(
    ("entradas", "mensagem"),
    [
        (["9", "s"], "A opção selecionada é inválida."),
        (["1", "x", "s"], "A opção selecionada é inválida."),
        (["1", "1", "31/02/2026", "01/03/2026", "s"], "Data inválida"),
        (["1", "1", "30/06/2026", "01/06/2026", "s"], "A data início não pode ser maior que a data fim"),
    ],
)
def test_entradas_invalidas_mostram_erro_e_repetem_a_pergunta(monkeypatch, tmp_path, entradas, mensagem):
    analise, saida = executar(monkeypatch, tmp_path, entradas)

    assert mensagem in saida
    assert analise.consultas == []


def test_voltar_da_estacao_e_do_periodo(monkeypatch, tmp_path):
    # município → volta → município → estação → volta do período → sai nas estações
    analise, saida = executar(monkeypatch, tmp_path, ["1", "v", "1", "1", "v", "s"])

    assert saida.count("Lista de Municípios") == 2
    assert saida.count("Lista de Estações") == 3
    assert analise.consultas == []


def test_periodo_sem_dados_volta_para_as_datas(monkeypatch, tmp_path):
    analise, saida = executar(
        monkeypatch, tmp_path, ["1", "1", "01/01/2020", "02/01/2020", "s"], AnaliseFalsa(estatisticas=())
    )

    assert "Não há dados no período selecionado." in saida
    assert len(analise.consultas) == 1
