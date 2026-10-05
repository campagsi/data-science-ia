"""
Execução de ponta a ponta de run_pipeline() com o dataset da API e banco de teste.

A coleta HTTP é substituída pela leitura do mesmo arquivo servido pela API
(DatasetRepository), para o teste não depender do servidor uvicorn.
"""
import pytest

import main
import src.config as config
from src.api.dataset_repository import DatasetRepository
from src.services.normalization_service import NormalizationService
from src.services.validation_service import ValidationService

pytestmark = pytest.mark.skip(
    reason="Usa o modelo antigo (Cidades e Leituras larga); será reescrito para o modelo 3FN "
    "nas fases 8 e 10 de docs/todo-idempotencia.md."
)


@pytest.fixture
def pipeline(monkeypatch, database, connection_string):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("AZURE_SQL_CONNECTIONSTRING", connection_string)
    monkeypatch.setenv("FONTE_DADOS", "http://api-de-teste")

    def usar_dataset(dados):
        monkeypatch.setattr(main.DataClient, "fetch_data", lambda self: dados)

    return usar_dataset


def test_pipeline_com_registros_completos_gera_relatorio(pipeline, contagens, capsys):
    dataset = DatasetRepository().get_all()
    obrigatorios = ValidationService._REQUIRED_FIELDS + NormalizationService._FLOAT_FIELDS
    pipeline([r for r in dataset if all(str(r.get(c, "")).strip() for c in obrigatorios)])

    relatorio = main.run_pipeline()
    main._exibir_resultados(relatorio)

    assert contagens()["Leituras"] > 0
    assert relatorio["escopo"] == {"cidade_id": 1}
    assert set(relatorio["grupos"]) == {"meteorologica", "qualidade_agua"}
    for grupo in relatorio["grupos"].values():
        assert grupo["analise"]["Estatísticas"]
    assert "Temperatura do ar" in capsys.readouterr().out


def test_pipeline_com_dataset_atual_grava_medicoes_ausentes_como_nulo(pipeline, contagens):
    """Os 82 registros com uma medição ausente são gravados com NULL nesse campo."""
    dataset = DatasetRepository().get_all()
    pipeline(dataset)

    main.run_pipeline()

    assert contagens()["Leituras"] == len(dataset)
