"""Orquestração do pipeline e tratamento de falhas no processo principal."""
import os
import subprocess
import sys

import pytest

import main
from src.config import Settings
from src.services.validation_service import ValidationService


class Falha(Exception):
    pass


REGISTRO_VALIDO = {"registro_codigo": "R1", "itens": [{"campo": "ph", "valor": 7.0}]}


@pytest.fixture
def pipeline_falso(monkeypatch):
    """Substitui todas as etapas por versões em memória."""
    chamadas = []

    class DataClientFalso:
        def __init__(self, settings):
            pass

        def fetch_data(self):
            chamadas.append("coleta")
            return ["bruto"]

    class NormalizacaoFalsa:
        def normalize(self, dados):
            chamadas.append("normalização")
            return ["normalizado"]

    class ValidacaoFalsa:
        def validate_data(self, dados):
            chamadas.append("validação")
            return [
                {"registro_codigo": "R1", "valido": True, "campos_nulos": [],
                 "itens_invalidos": [], "motivos": [], "registro": REGISTRO_VALIDO},
                {"registro_codigo": "R2", "valido": False, "campos_nulos": ["estacao_codigo"],
                 "itens_invalidos": [], "motivos": [{"etapa": "completude", "campo": "estacao_codigo",
                                                     "motivo": "campo vital nulo", "valor": None}],
                 "registro": {"registro_codigo": "R2", "itens": []}},
            ]

        registros_validos = staticmethod(ValidationService.registros_validos)

    class DatabaseFalso:
        def __init__(self, connection_string):
            self.connection_string = connection_string

    class LeituraRepositoryFalso:
        def __init__(self, database):
            pass

        def save_readings(self, registros):
            chamadas.append(("persistência", registros))

    class AnaliseFalsa:
        def __init__(self, database):
            chamadas.append(("banco da análise", database.connection_string))

        def calculate_metrics(self, **kwargs):
            chamadas.append("análise")
            return {"escopo": {"cidade_id": kwargs["cidade_id"]}}

    def carregar_config():
        chamadas.append("configuração")
        return Settings(mock_api="http://api", azure_sql_connectionstring="Server=teste")

    monkeypatch.setattr(main, "load_config", carregar_config)
    monkeypatch.setattr(main, "DataClient", DataClientFalso)
    monkeypatch.setattr(main, "NormalizationService", NormalizacaoFalsa)
    monkeypatch.setattr(main, "ValidationService", ValidacaoFalsa)
    monkeypatch.setattr(main, "DatabaseConnection", DatabaseFalso)
    monkeypatch.setattr(main, "LeituraRepository", LeituraRepositoryFalso)
    monkeypatch.setattr(main, "AnaliticsService", AnaliseFalsa)
    return chamadas


def test_importar_main_nao_executa_o_pipeline():
    assert callable(main.run_pipeline)


def test_run_pipeline_executa_as_etapas_na_ordem(pipeline_falso):
    relatorio = main.run_pipeline()

    assert pipeline_falso == [
        "configuração",
        "coleta",
        "normalização",
        "validação",
        ("persistência", [REGISTRO_VALIDO]),
        ("banco da análise", "Server=teste"),
        "análise",
    ]
    assert relatorio == {"escopo": {"cidade_id": 1}, "periodo": {}, "grupos": {}}


@pytest.mark.parametrize(
    ("alvo", "metodo"),
    [
        ("load_config", None),
        ("DataClient", "fetch_data"),
        ("NormalizationService", "normalize"),
        ("ValidationService", "validate_data"),
        ("LeituraRepository", "save_readings"),
        ("AnaliticsService", "calculate_metrics"),
    ],
)
def test_falha_em_qualquer_etapa_propaga_o_erro_original(pipeline_falso, monkeypatch, alvo, metodo):
    def falhar(*args, **kwargs):
        raise Falha("detalhe")

    if metodo is None:
        monkeypatch.setattr(main, alvo, falhar)
    else:
        monkeypatch.setattr(getattr(main, alvo), metodo, falhar)

    with pytest.raises(Falha, match="detalhe"):
        main.run_pipeline()


def test_falha_interrompe_as_etapas_seguintes(pipeline_falso, monkeypatch):
    monkeypatch.setattr(main.ValidationService, "validate_data", lambda self, d: (_ for _ in ()).throw(Falha("x")))

    with pytest.raises(Falha):
        main.run_pipeline()

    assert ("persistência", [REGISTRO_VALIDO]) not in pipeline_falso
    assert "análise" not in pipeline_falso


def test_execucao_com_falha_termina_com_codigo_1_sem_expor_segredo(tmp_path):
    ambiente = dict(
        os.environ,
        MOCK_API="",
        AZURE_SQL_CONNECTIONSTRING="Server=x;PWD=senha-secreta",
        PYTHONIOENCODING="utf-8",
    )

    processo = subprocess.run(
        [sys.executable, "main.py"],
        cwd=main.__file__.rsplit(os.sep, 1)[0],
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert processo.returncode == 1
    assert "ValueError: A variável MOCK_API deve estar configurada." in processo.stderr
    assert "senha-secreta" not in processo.stderr + processo.stdout


@pytest.mark.parametrize(
    ("chave", "mensagem"),
    [
        ("", "ValueError: A variável CHAVE_CRIPTOGRAFIA deve estar configurada."),
        ("chave-invalida-secreta", "ValueError: CHAVE_CRIPTOGRAFIA inválida"),
    ],
)
def test_aplicacao_nao_inicia_sem_chave_de_criptografia_valida(chave, mensagem):
    ambiente = dict(os.environ, CHAVE_CRIPTOGRAFIA=chave, PYTHONIOENCODING="utf-8")

    processo = subprocess.run(
        [sys.executable, "main.py"],
        cwd=main.__file__.rsplit(os.sep, 1)[0],
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert processo.returncode == 1
    assert "[CRITICAL]" in processo.stderr
    assert mensagem in processo.stderr
    assert "chave-invalida-secreta" not in processo.stderr + processo.stdout


def test_iniciar_aplicacao_configura_logs_antes_da_configuracao(monkeypatch):
    chamadas = []
    settings = Settings(
        mock_api="http://api",
        azure_sql_connectionstring="Server=teste",
        chave_criptografia="chave",
        pepper_hash="pepper",
    )
    monkeypatch.setattr(main, "configurar_logs", lambda: chamadas.append("logs"))
    monkeypatch.setattr(main, "load_config", lambda: chamadas.append("config") or settings)
    monkeypatch.setattr(
        main, "configurar_seguranca", lambda chave, pepper: chamadas.append(("seguranca", chave, pepper))
    )

    assert main.iniciar_aplicacao() is settings
    assert chamadas == ["logs", "config", ("seguranca", "chave", "pepper")]
