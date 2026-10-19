"""Testes da paginação, agregação e formatação do dashboard."""
from datetime import datetime

import pytest

from src.ui.visualizacao import (
    agregar_por_hora,
    formatar_data,
    formatar_data_hora,
    formatar_decimal,
    formatar_milhar,
    ler_inteiro,
    ler_por_pagina,
    paginar,
)


def test_paginar_divide_e_informa_intervalo():
    pagina = paginar(list(range(23)), 2, 10)

    assert pagina.itens == list(range(10, 20))
    assert (pagina.inicio, pagina.fim, pagina.total_paginas) == (11, 20, 3)
    assert pagina.tem_anterior and pagina.tem_proxima


@pytest.mark.parametrize("numero, esperado", [(0, 1), (-3, 1), (50, 3)])
def test_paginar_ajusta_numero_fora_do_intervalo(numero, esperado):
    assert paginar(list(range(23)), numero, 10).numero == esperado


def test_paginar_lista_vazia_tem_uma_pagina():
    pagina = paginar([], 1, 10)

    assert pagina.itens == []
    assert (pagina.inicio, pagina.fim, pagina.total_paginas) == (0, 0, 1)
    assert not pagina.tem_anterior and not pagina.tem_proxima


@pytest.mark.parametrize("numero, esperado", [
    (1, [1, 2, 3, None, 20]),
    (10, [1, None, 8, 9, 10, 11, 12, None, 20]),
    (4, [1, 2, 3, 4, 5, 6, None, 20]),
    (20, [1, None, 18, 19, 20]),
])
def test_paginas_visiveis_usa_reticencias(numero, esperado):
    assert paginar(list(range(200)), numero, 10).paginas_visiveis() == esperado


@pytest.mark.parametrize("texto, esperado", [(None, 5), ("", 5), ("abc", 5), ("-2", 5), ("0", 5), ("7", 7)])
def test_ler_inteiro(texto, esperado):
    assert ler_inteiro(texto, 5) == esperado


@pytest.mark.parametrize("texto, esperado", [("50", 50), ("33", 25), (None, 25), ("100", 100)])
def test_ler_por_pagina_aceita_so_opcoes_validas(texto, esperado):
    assert ler_por_pagina(texto) == esperado


def test_agregar_por_hora_combina_valores_do_mesmo_balde():
    medicoes = [
        {"data_hora": datetime(2026, 6, 12, 10, 30), "valor": 8.0},
        {"data_hora": datetime(2026, 6, 12, 10, 0), "valor": 6.0},
        {"data_hora": "2026-06-12 09:15:00", "valor": 1.5},
    ]

    assert agregar_por_hora(medicoes) == [
        ["2026-06-12T09:00", 1, 1.5, 1.5, 1.5],
        ["2026-06-12T10:00", 2, 14.0, 6.0, 8.0],
    ]


def test_formatadores_pt_br():
    assert formatar_milhar(1234567) == "1.234.567"
    assert formatar_decimal(1234.5) == "1.234,50"
    assert formatar_decimal(7.2, 3) == "7,200"
    assert formatar_decimal(None) == "—"
    assert formatar_decimal(float("nan")) == "—"
    assert formatar_data("2026-10-06") == "06/10/2026"
    assert formatar_data_hora(datetime(2026, 10, 6, 14, 30)) == "06/10/2026 14:30"
    assert formatar_data_hora("2026-10-06 14:30:00") == "06/10/2026 14:30"
