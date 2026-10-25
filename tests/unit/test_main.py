"""Orquestração do pipeline e tratamento de falhas no processo principal."""
import os
import subprocess
import sys
import types
from datetime import date, datetime

import pytest

import main
from src.config import Settings
from src.models import EstacaoModel, ParametroModel


class Falha(Exception):
    pass


PARAMETRO_PH = ParametroModel(
    id_parametro=2, codigo_parametro="TIP-PH", nome="pH", unidade_medida="pH",
    valor_minimo=0, valor_maximo=14,
)
REGISTRO_VALIDO = {"registro_codigo": "R1", "itens": [{"campo": "ph", "valor": 7.0}]}
# Formato de ValidationService.validar_contrato (Bronze) e de validate_data (Silver).
RECUSADO_NO_CONTRATO = {
    "registro_codigo": "R3", "valido": False,
    "motivos": [{"etapa": "Validação do Contrato", "campo": "operador_codigo",
                 "motivo": "Field required", "valor": None}],
}
RESULTADOS_DA_SILVER = (
    {"registro_codigo": "R1", "valido": True, "campos_nulos": [],
     "itens_invalidos": [], "motivos": [], "registro": REGISTRO_VALIDO},
    {"registro_codigo": "R2", "valido": False, "campos_nulos": ["estacao_codigo"],
     "itens_invalidos": [], "motivos": [{"etapa": "completude", "campo": "estacao_codigo",
                                         "motivo": "campo vital nulo", "valor": None}],
     "registro": {"registro_codigo": "R2", "itens": []}},
)
ESTACAO = EstacaoModel(
    id_estacao=5, codigo_estacao="EST-RJ-001", nome="Estação", municipio_id=1, latitude=-22.9, longitude=-43.2,
)
ANOMALIA = {
    "Estação": "Estação", "Parâmetro": "pH", "Unidade": "pH", "Data": datetime(2026, 6, 1, 3),
    "Registro": "R1", "Valor": 13.5, "Limite Inferior": 6.0, "Limite Superior": 8.5,
    "Z-Score": 4.2, "Alerta": "IQR+ZSCORE",
}


@pytest.fixture
def pipeline_falso(monkeypatch):
    """Substitui todas as etapas por versões em memória."""
    chamadas = []

    class DataClientFalso:
        def __init__(self, settings):
            pass

        def fetch_data(self):
            chamadas.append("coleta")
            return ["bruto R1", "bruto R2", "bruto R3"]

    class ExtracaoFalsa:
        """Data lake em memória: Bronze recusa R3, Silver valida R1 e recusa R2."""

        def __init__(self, fonte_dados, diretorio_base):
            chamadas.append(("data lake", fonte_dados, diretorio_base))

        def extrair_dados_bronze(self, dados):
            chamadas.append("bronze")
            return [RECUSADO_NO_CONTRATO]

        def extrair_dados_silver(self, nome_arquivo_bronze):
            chamadas.append(("silver", nome_arquivo_bronze))
            return list(RESULTADOS_DA_SILVER), {"TIP-PH": PARAMETRO_PH}

        def extrair_dados_gold(self, nome_arquivo_silver):
            chamadas.append(("gold", nome_arquivo_silver))

    # Por quê: o run_pipeline importa o módulo do data lake só na execução, e o
    # módulo real chama a API já na importação. Um módulo falso em sys.modules
    # é o que o "from src.ingestion.extracao_dados import ..." vai encontrar.
    modulo_data_lake = types.ModuleType("src.ingestion.extracao_dados")
    modulo_data_lake.Extracao_Dados = ExtracaoFalsa
    monkeypatch.setitem(sys.modules, "src.ingestion.extracao_dados", modulo_data_lake)

    class DatabaseFalso:
        def __init__(self, connection_string):
            self.connection_string = connection_string

    class LeituraRepositoryFalso:
        def __init__(self, database):
            pass

        def save_readings(self, registros, parametros, fonte):
            chamadas.append(("persistência", registros, sorted(parametros), fonte))
            return {"municipios": 1, "operadores": 1, "estacoes": 1,
                    "leituras_removidas": 0, "leituras_gravadas": 1, "itens_gravados": 1}

    class AnaliseFalsa:
        def __init__(self, database):
            chamadas.append(("banco da análise", database.connection_string))

        def buscar_estacao_por_codigo(self, codigo):
            chamadas.append(("estação", codigo))
            return ESTACAO if codigo == ESTACAO.codigo_estacao else None

        def calculate_metrics(self, **kwargs):
            chamadas.append(("análise", kwargs))
            return {"escopo": {"estacao_id": kwargs["estacao_id"]}, "anomalias": [ANOMALIA]}

    def carregar_config():
        chamadas.append("configuração")
        return Settings(fonte_dados="http://api", azure_sql_connectionstring="Server=teste")

    monkeypatch.setattr(main, "load_config", carregar_config)
    monkeypatch.setattr(main, "DataClient", DataClientFalso)
    monkeypatch.setattr(main, "DatabaseConnection", DatabaseFalso)
    monkeypatch.setattr(main, "LeituraRepository", LeituraRepositoryFalso)
    monkeypatch.setattr(main, "AnaliticsService", AnaliseFalsa)
    return chamadas


def test_importar_main_nao_executa_o_pipeline():
    assert callable(main.run_pipeline)


def test_run_pipeline_executa_as_etapas_na_ordem(pipeline_falso):
    resumo = main.run_pipeline()

    # Parte A (data lake) inteira antes da parte B (banco); só R1 chega ao banco.
    assert pipeline_falso == [
        "configuração",
        "coleta",
        ("data lake", "http://api", "data_lake"),
        "bronze",
        ("silver", "dados_bronze.json"),
        ("gold", "dados_silver.parquet"),
        ("persistência", [REGISTRO_VALIDO], ["TIP-PH"], "http://api"),
    ]
    # Fecha com o recebido: 1 recusado antes da validação + 1 válido + 1 inválido = 3.
    assert resumo == {
        "recebidos": 3,
        "rejeitados_na_normalizacao": 1,
        "registros_validos": 1,
        "registros_invalidos": 1,
        "itens_descartados": 0,
        "leituras_gravadas": 1,
        "leituras_substituidas": 0,
        "itens_gravados": 1,
    }


def test_recusados_no_contrato_e_na_validacao_vao_para_o_log(pipeline_falso, logs_temporarios):
    main.run_pipeline()

    rejeitados = logs_temporarios("rejeitados")
    assert any("registro=R3" in linha and "campo=operador_codigo" in linha for linha in rejeitados)
    assert any("registro=R2" in linha and "campo=estacao_codigo" in linha for linha in rejeitados)
    assert not any("registro=R1" in linha for linha in rejeitados)


def test_lote_vazio_encerra_sem_tocar_no_banco(pipeline_falso, monkeypatch):
    monkeypatch.setattr(main.DataClient, "fetch_data", lambda self: [])

    resumo = main.run_pipeline()

    assert pipeline_falso == ["configuração"]
    assert set(resumo) == set(main._CAMPOS_RESUMO)
    assert set(resumo.values()) == {0}


def test_run_pipeline_nao_executa_a_analise(pipeline_falso):
    main.run_pipeline()

    assert not any(isinstance(c, tuple) and c[0] == "banco da análise" for c in pipeline_falso)


def test_gerar_relatorio_resolve_a_estacao_e_repassa_o_periodo(pipeline_falso, logs_temporarios):
    relatorio = main.gerar_relatorio(
        main.DatabaseConnection("Server=teste"), "EST-RJ-001", date(2026, 6, 1), date(2026, 6, 30)
    )

    assert pipeline_falso == [
        ("banco da análise", "Server=teste"),
        ("estação", "EST-RJ-001"),
        ("análise", {"estacao_id": 5, "data_inicio": date(2026, 6, 1), "data_fim": date(2026, 6, 30)}),
    ]
    assert relatorio["escopo"] == {"estacao_id": 5}
    assert relatorio["anomalias"] == [ANOMALIA]


def test_gerar_relatorio_registra_cada_anomalia_em_warning(pipeline_falso, logs_temporarios):
    main.gerar_relatorio(main.DatabaseConnection("Server=teste"))

    alertas = [linha for linha in logs_temporarios("pipeline") if "Alerta de qualidade" in linha]
    assert len(alertas) == 1
    assert "[WARNING]" in alertas[0]
    assert "alerta=IQR+ZSCORE" in alertas[0] and "registro=R1" in alertas[0] and "zscore=4.20" in alertas[0]


def test_gerar_relatorio_com_estacao_inexistente_falha(pipeline_falso):
    with pytest.raises(ValueError, match="Estação não cadastrada: X"):
        main.gerar_relatorio(main.DatabaseConnection("Server=teste"), "X")


@pytest.mark.parametrize(
    ("argv", "esperado"),
    [
        ([], {"ingestao": False, "analise": False, "estacao": None, "inicio": None, "fim": None}),
        (["--ingestao"], {"ingestao": True, "analise": False, "estacao": None, "inicio": None, "fim": None}),
        (
            ["--analise", "--estacao", "EST-1", "--inicio", "2026-06-01", "--fim", "2026-06-30"],
            {"ingestao": False, "analise": True, "estacao": "EST-1",
             "inicio": date(2026, 6, 1), "fim": date(2026, 6, 30)},
        ),
    ],
)
def test_ler_argumentos(argv, esperado):
    sem_agente = {"agente": False, "pergunta": None, "indexar": False, "indexar_dias": False, "treinar_previsao": False, "laudo": False, "limite": None}
    assert vars(main.ler_argumentos(argv)) == {**esperado, **sem_agente}


def test_ler_argumentos_do_agente():
    assert main.ler_argumentos(["--agente"]).agente
    assert main.ler_argumentos(["--pergunta", "Qual o pH médio em junho?"]).pergunta == "Qual o pH médio em junho?"


@pytest.mark.parametrize(
    "argv",
    [
        ["--ingestao", "--analise"],
        ["--ingestao", "--estacao", "EST-1"],
        ["--analise", "--fim", "2026-06-30"],
        ["--analise", "--inicio", "2026-07-01", "--fim", "2026-06-30"],
        ["--analise", "--inicio", "01/06/2026"],
        ["--agente", "--pergunta", "pH?"],
        ["--analise", "--agente"],
        ["--pergunta", "pH?", "--estacao", "EST-1"],
        ["--indexar", "--agente"],
        ["--indexar", "--indexar-dias"],
        ["--treinar-previsao", "--indexar"],
        ["--laudo"],
        ["--laudo", "--inicio", "2026-06-01", "--limite", "-1"],
        ["--analise", "--limite", "5"],
        ["--laudo", "--analise", "--inicio", "2026-06-01"],
    ],
)
def test_argumentos_invalidos_encerram_com_erro(argv):
    with pytest.raises(SystemExit) as erro:
        main.ler_argumentos(argv)
    assert erro.value.code == 2


def falhar(*args, **kwargs):
    raise Falha("detalhe")


@pytest.mark.parametrize(
    ("alvo", "metodo"),
    [
        ("load_config", None),
        ("DataClient", "fetch_data"),
        ("LeituraRepository", "save_readings"),
    ],
)
def test_falha_em_qualquer_etapa_propaga_o_erro_original(pipeline_falso, monkeypatch, alvo, metodo):
    if metodo is None:
        monkeypatch.setattr(main, alvo, falhar)
    else:
        monkeypatch.setattr(getattr(main, alvo), metodo, falhar)

    with pytest.raises(Falha, match="detalhe"):
        main.run_pipeline()


@pytest.mark.parametrize("camada", ["extrair_dados_bronze", "extrair_dados_silver", "extrair_dados_gold"])
def test_falha_no_data_lake_interrompe_antes_do_banco(pipeline_falso, monkeypatch, camada):
    monkeypatch.setattr(sys.modules["src.ingestion.extracao_dados"].Extracao_Dados, camada, falhar)

    with pytest.raises(Falha, match="detalhe"):
        main.run_pipeline()

    assert not any(c[0] in {"persistência", "banco da análise"} for c in pipeline_falso if isinstance(c, tuple))


def test_execucao_com_falha_termina_com_codigo_1_sem_expor_segredo(tmp_path):
    ambiente = dict(
        os.environ,
        FONTE_DADOS="",
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
    assert "ValueError: A variável FONTE_DADOS deve estar configurada." in processo.stderr
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
        fonte_dados="http://api",
        azure_sql_connectionstring="Server=teste",
        chave_criptografia="chave",
        chave_hash="chave-hash",
    )
    monkeypatch.setattr(main, "configurar_logs", lambda etapa: chamadas.append(("logs", etapa)))
    monkeypatch.setattr(main, "load_config", lambda: chamadas.append("config") or settings)
    monkeypatch.setattr(
        main, "configurar_seguranca", lambda chave, chave_hash: chamadas.append(("seguranca", chave, chave_hash))
    )

    assert main.iniciar_aplicacao("analise") is settings
    assert chamadas == [("logs", "analise"), "config", ("seguranca", "chave", "chave-hash")]


@pytest.mark.parametrize(
    ("argv", "etapa"),
    [(["--ingestao"], "ingestao"), (["--analise"], "analise"), ([], "consulta"),
     (["--agente"], "agente"), (["--pergunta", "pH?"], "agente"), (["--indexar"], "indexacao"),
     (["--indexar-dias"], "indexacao"), (["--treinar-previsao"], "previsao"),
     (["--laudo", "--inicio", "2026-06-01"], "laudo")],
)
def test_etapa_da_execucao_vem_dos_argumentos(argv, etapa):
    assert main.etapa_da_execucao(main.ler_argumentos(argv)) == etapa
