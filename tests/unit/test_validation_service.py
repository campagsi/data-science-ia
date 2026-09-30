import pytest

from src.models import EstacaoModel, LeituraModel
from src.services.validation_service import ValidationService


def test_validate_data_aceita_lote_valido(registro_normalizado):
    segunda_leitura = dict(registro_normalizado, data_hora=registro_normalizado["data_hora"].replace(hour=12))

    validados = ValidationService().validate_data([registro_normalizado, segunda_leitura])

    assert len(validados) == 2
    assert validados[0] == registro_normalizado


def test_validate_data_rejeita_campo_obrigatorio_ausente(registro_normalizado):
    del registro_normalizado["fonte"]

    with pytest.raises(ValueError, match="Registro 0: campos obrigatórios ausentes: fonte"):
        ValidationService().validate_data([registro_normalizado])


def test_validate_data_aceita_medicao_nula(registro_normalizado):
    registro_normalizado["ph"] = None

    validados = ValidationService().validate_data([registro_normalizado])

    assert validados[0]["ph"] is None


def test_validate_data_aceita_medicao_sem_chave(registro_normalizado):
    del registro_normalizado["turbidez"]

    validados = ValidationService().validate_data([registro_normalizado])

    assert "turbidez" not in validados[0]


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("ph", 16.5, "ph deve estar entre 0 e 14"),
        ("umidade", 101.0, "umidade deve estar entre 0 e 100"),
        ("estacao_latitude", -91.0, "estacao_latitude deve estar entre -90 e 90"),
        ("turbidez", -1.0, "turbidez não pode ser negativo"),
        ("cidade_estado", "RJX", "sigla de duas letras"),
    ],
)
def test_validate_data_rejeita_valor_fora_do_contrato(registro_normalizado, campo, valor, mensagem):
    registro_normalizado[campo] = valor

    with pytest.raises(ValueError, match=mensagem):
        ValidationService().validate_data([registro_normalizado])


def test_validate_data_rejeita_codigo_de_estacao_com_dados_conflitantes(registro_normalizado):
    conflito = dict(registro_normalizado, estacao_nome="Outra estação")

    with pytest.raises(ValueError, match="Registro 1: estacao_codigo duplicado"):
        ValidationService().validate_data([registro_normalizado, conflito])


def test_validate_data_rejeita_lote_inteiro(registro_normalizado):
    invalido = dict(registro_normalizado, ph=20.0)

    with pytest.raises(ValueError, match="Lote inválido"):
        ValidationService().validate_data([registro_normalizado, invalido])


def test_validar_estacao_devolve_modelo(registro_normalizado):
    estacao = ValidationService().validar_estacao(registro_normalizado)

    assert isinstance(estacao, EstacaoModel)
    assert estacao.codigo == "EST-RJ-001"


def test_validar_leitura_associa_estacao(registro_normalizado):
    leitura = ValidationService().validar_leitura(registro_normalizado, estacao_id=7)

    assert isinstance(leitura, LeituraModel)
    assert leitura.estacao_id == 7
    assert leitura.ph == 7.49
