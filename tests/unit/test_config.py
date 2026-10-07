import pytest

import src.config as config


@pytest.fixture(autouse=True)
def sem_arquivo_env(monkeypatch):
    """Isola os testes do arquivo .env local."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)


def test_load_config_retorna_settings(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", "  Server=teste;Database=db  ")
    monkeypatch.setenv("FONTE_DADOS", " http://localhost:8000 ")

    settings = config.load_config()

    assert settings.azure_sql_connectionstring == "Server=teste;Database=db"
    assert settings.fonte_dados == "http://localhost:8000"


def test_load_config_le_chaves_de_seguranca(monkeypatch):
    monkeypatch.setenv("CHAVE_CRIPTOGRAFIA", " chave ")
    monkeypatch.setenv("CHAVE_HASH", " chave-hash ")

    settings = config.load_config()

    assert settings.chave_criptografia == "chave"
    assert settings.chave_hash == "chave-hash"


def test_chave_hash_e_opcional(monkeypatch):
    monkeypatch.delenv("CHAVE_HASH", raising=False)

    assert config.load_config().chave_hash == ""


def test_fonte_dados_acima_do_tamanho_da_coluna_e_recusada(monkeypatch):
    monkeypatch.setenv("FONTE_DADOS", "http://" + "a" * 100)

    with pytest.raises(ValueError, match="FONTE_DADOS deve ter no máximo 100 caracteres"):
        config.load_config()


@pytest.mark.parametrize(
    "variavel", ["AZURE_SQL_CONNECTIONSTRING", "FONTE_DADOS", "CHAVE_CRIPTOGRAFIA"]
)
def test_load_config_exige_variavel(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "   ")

    with pytest.raises(ValueError, match=variavel):
        config.load_config()


def test_erro_de_configuracao_nao_expoe_segredo(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", "Server=x;PWD=senha-secreta")
    monkeypatch.delenv("FONTE_DADOS")

    with pytest.raises(ValueError) as erro:
        config.load_config()

    assert "senha-secreta" not in str(erro.value)

