import pytest

import src.config as config


@pytest.fixture(autouse=True)
def sem_arquivo_env(monkeypatch):
    """Isola os testes do arquivo .env local."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)


def test_load_config_retorna_settings(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", "  Server=teste;Database=db  ")
    monkeypatch.setenv("MOCK_API", " http://localhost:8000 ")

    settings = config.load_config()

    assert settings.azure_sql_connectionstring == "Server=teste;Database=db"
    assert settings.mock_api == "http://localhost:8000"


@pytest.mark.parametrize("variavel", ["AZURE_SQL_CONNECTIONSTRING", "MOCK_API"])
def test_load_config_exige_variavel(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "   ")

    with pytest.raises(ValueError, match=variavel):
        config.load_config()


def test_erro_de_configuracao_nao_expoe_segredo(monkeypatch):
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", "Server=x;PWD=senha-secreta")
    monkeypatch.delenv("MOCK_API")

    with pytest.raises(ValueError) as erro:
        config.load_config()

    assert "senha-secreta" not in str(erro.value)

