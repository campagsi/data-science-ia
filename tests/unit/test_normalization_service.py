from datetime import datetime

import pytest

from src.services.normalization_service import NormalizationService


def test_normalize_converte_tipos(registro_bruto):
    registro = NormalizationService().normalize([registro_bruto])[0]

    assert registro["cidade_nome"] == "Rio de Janeiro"
    assert registro["cidade_estado"] == "RJ"
    assert registro["estacao_latitude"] == -22.8768
    assert registro["ph"] == 7.49
    assert registro["operador_ativo"] is True
    assert registro["estacao_ativa"] is True
    assert registro["data_hora"] == datetime(2026, 6, 1, 0, 0)


def test_normalize_nao_altera_payload_original(registro_bruto):
    original = dict(registro_bruto)

    NormalizationService().normalize([registro_bruto])

    assert registro_bruto == original


def test_normalize_converte_numero_vazio_para_none(registro_bruto):
    registro_bruto["turbidez"] = "   "

    assert NormalizationService().normalize([registro_bruto])[0]["turbidez"] is None


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("ph", "sete", "numérico"),
        ("estacao_ativa", "talvez", "booleano"),
        ("data_hora", "01/06/2026", "data ISO"),
    ],
)
def test_normalize_rejeita_valor_invalido(registro_bruto, campo, valor, mensagem):
    registro_bruto[campo] = valor

    with pytest.raises(ValueError, match=f"Registro 0: campo {campo}.*{mensagem}"):
        NormalizationService().normalize([registro_bruto])


def test_normalize_rejeita_payload_que_nao_e_lista():
    with pytest.raises(ValueError, match="lista"):
        NormalizationService().normalize({"cidade_nome": "x"})


def test_normalize_rejeita_registro_que_nao_e_objeto(registro_bruto):
    with pytest.raises(ValueError, match="Registro 1"):
        NormalizationService().normalize([registro_bruto, "x"])
