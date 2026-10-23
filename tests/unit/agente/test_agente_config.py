from pathlib import Path

import pytest

import src.config as config

VARIAVEIS_AGENTE = [
    "AGENTE_LLM_FORNECEDOR",
    "AGENTE_LLM_MODELO",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AGENTE_SQL_CONNECTIONSTRING",
    "AGENTE_EMBEDDINGS_MODELO",
    "AGENTE_VETORES",
    "AGENTE_DIR_INDICE",
    "AGENTE_MAX_FERRAMENTAS",
    "AGENTE_MAX_LINHAS",
    "AGENTE_HISTORICO_TURNOS",
    "AGENTE_TIMEOUT_SEGUNDOS",
    "AGENTE_MAX_TOKENS_SAIDA",
    "AGENTE_ESFORCO",
    "AGENTE_MAX_TOKENS_PERGUNTA",
    "AGENTE_PRAZO_PERGUNTA_SEGUNDOS",
]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Isola os testes do .env local e de variáveis do agente já definidas."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for variavel in VARIAVEIS_AGENTE:
        monkeypatch.delenv(variavel, raising=False)


def test_simulado_dispensa_modelo_e_chave_e_usa_os_padroes(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", " Simulado ")

    cfg = config.load_config_agente()

    assert cfg.llm_fornecedor == "simulado"
    assert (cfg.max_ferramentas, cfg.max_linhas, cfg.historico_turnos, cfg.timeout_segundos) == (6, 50, 10, 60)
    assert cfg.vetores == "memoria"
    assert cfg.embeddings_modelo == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert cfg.dir_indice == config.RAIZ_PROJETO / "data" / "agente"
    assert (cfg.max_tokens_saida, cfg.esforco, cfg.max_tokens_pergunta, cfg.prazo_pergunta_segundos) == (16000, "medium", 60000, 180)


def configurar_anthropic(monkeypatch, **valores):
    """Variáveis mínimas do fornecedor anthropic; valores substitui ou remove (None) alguma."""
    padrao = {
        "AGENTE_LLM_FORNECEDOR": "anthropic",
        "AGENTE_LLM_MODELO": "claude-haiku-5-5",
        "ANTHROPIC_API_KEY": "sk-ant-teste",
        "AGENTE_SQL_CONNECTIONSTRING": "Server=x;Database=y;UID=agente_leitura;PWD=senha-leitura",
    }
    for variavel, valor in {**padrao, **valores}.items():
        if valor is None:
            monkeypatch.delenv(variavel, raising=False)
        else:
            monkeypatch.setenv(variavel, valor)


def test_anthropic_le_modelo_chave_e_conexao_do_agente(monkeypatch):
    configurar_anthropic(monkeypatch, AGENTE_LLM_MODELO=" claude-haiku-5-5 ", ANTHROPIC_API_KEY=" sk-ant-teste ")

    cfg = config.load_config_agente()

    assert (cfg.llm_modelo, cfg.anthropic_api_key) == ("claude-haiku-5-5", "sk-ant-teste")
    assert "UID=agente_leitura" in cfg.sql_connectionstring


def test_chave_e_conexao_nao_aparecem_no_repr(monkeypatch):
    configurar_anthropic(monkeypatch, ANTHROPIC_API_KEY="sk-ant-segredo")

    texto = repr(config.load_config_agente())

    assert "sk-ant-segredo" not in texto
    assert "senha-leitura" not in texto


def test_anthropic_exige_a_conexao_so_de_leitura_do_agente(monkeypatch):
    """POL-01: sem a conexão própria, o agente não sobe, nem recai na connection string da ingestão."""
    configurar_anthropic(monkeypatch, AGENTE_SQL_CONNECTIONSTRING=None)
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", "Server=ingestao;PWD=escrita")

    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING") as erro:
        config.load_config_agente()
    assert "escrita" not in str(erro.value)


def test_simulado_dispensa_a_conexao_do_agente(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")

    assert config.load_config_agente().sql_connectionstring == ""


@pytest.mark.parametrize("valor", ["", "  ", "gemini", "azure_openai"])
def test_fornecedor_ausente_ou_desconhecido(monkeypatch, valor):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", valor)

    with pytest.raises(ValueError, match="AGENTE_LLM_FORNECEDOR"):
        config.load_config_agente()


def test_anthropic_exige_modelo(monkeypatch):
    configurar_anthropic(monkeypatch, AGENTE_LLM_MODELO=None)

    with pytest.raises(ValueError, match="AGENTE_LLM_MODELO"):
        config.load_config_agente()


def test_anthropic_exige_chave_sem_expor_valores(monkeypatch):
    configurar_anthropic(monkeypatch, ANTHROPIC_API_KEY=None)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY") as erro:
        config.load_config_agente()
    assert "claude-haiku-5-5" not in str(erro.value)


def test_vetores_desconhecido(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.setenv("AGENTE_VETORES", "pinecone")

    with pytest.raises(ValueError, match="AGENTE_VETORES"):
        config.load_config_agente()


def test_dir_indice_relativo_e_resolvido_a_partir_da_raiz(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.setenv("AGENTE_DIR_INDICE", "outra/pasta")
    assert config.load_config_agente().dir_indice == config.RAIZ_PROJETO / "outra" / "pasta"

    monkeypatch.setenv("AGENTE_DIR_INDICE", str(tmp_path))
    assert config.load_config_agente().dir_indice == Path(tmp_path)


def test_limites_customizados(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.setenv("AGENTE_MAX_FERRAMENTAS", "3")
    monkeypatch.setenv("AGENTE_HISTORICO_TURNOS", " 4 ")

    cfg = config.load_config_agente()

    assert (cfg.max_ferramentas, cfg.historico_turnos) == (3, 4)


@pytest.mark.parametrize(
    "variavel",
    [
        "AGENTE_MAX_FERRAMENTAS",
        "AGENTE_MAX_LINHAS",
        "AGENTE_HISTORICO_TURNOS",
        "AGENTE_TIMEOUT_SEGUNDOS",
        "AGENTE_MAX_TOKENS_SAIDA",
        "AGENTE_MAX_TOKENS_PERGUNTA",
        "AGENTE_PRAZO_PERGUNTA_SEGUNDOS",
    ],
)
@pytest.mark.parametrize("valor, motivo", [("abc", "número inteiro"), ("2.5", "número inteiro"), ("0", "maior que zero"), ("-1", "maior que zero")])
def test_limite_invalido(monkeypatch, variavel, valor, motivo):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.setenv(variavel, valor)

    with pytest.raises(ValueError, match=f"{variavel} deve ser .*{motivo}"):
        config.load_config_agente()


def test_agente_nao_exige_variaveis_da_ingestao(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.delenv("AZURE_SQL_CONNECTIONSTRING", raising=False)
    monkeypatch.delenv("FONTE_DADOS", raising=False)

    assert config.load_config_agente().llm_fornecedor == "simulado"


def test_esforco_aceita_os_niveis_e_recusa_os_outros(monkeypatch):
    monkeypatch.setenv("AGENTE_LLM_FORNECEDOR", "simulado")
    monkeypatch.setenv("AGENTE_ESFORCO", " LOW ")
    assert config.load_config_agente().esforco == "low"

    monkeypatch.setenv("AGENTE_ESFORCO", "max")
    with pytest.raises(ValueError, match="AGENTE_ESFORCO"):
        config.load_config_agente()


def test_openai_le_a_propria_chave_e_exige_a_conexao_do_agente(monkeypatch):
    """DA11: o fornecedor openai usa OPENAI_API_KEY e o mesmo usuário só de leitura (POL-01)."""
    configurar_anthropic(monkeypatch, AGENTE_LLM_FORNECEDOR="openai", AGENTE_LLM_MODELO="gpt-4.1-mini", ANTHROPIC_API_KEY=None)
    monkeypatch.setenv("OPENAI_API_KEY", " sk-proj-teste ")

    cfg = config.load_config_agente()

    assert (cfg.llm_fornecedor, cfg.llm_modelo, cfg.openai_api_key) == ("openai", "gpt-4.1-mini", "sk-proj-teste")
    assert "sk-proj-teste" not in repr(cfg)
    monkeypatch.delenv("AGENTE_SQL_CONNECTIONSTRING")
    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        config.load_config_agente()


def test_openai_exige_chave(monkeypatch):
    configurar_anthropic(monkeypatch, AGENTE_LLM_FORNECEDOR="openai", AGENTE_LLM_MODELO="gpt-4.1-mini")

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        config.load_config_agente()
