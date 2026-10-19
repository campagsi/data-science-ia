"""Paginação e agregação de séries usadas pelo dashboard web."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

POR_PAGINA_PADRAO = 25
OPCOES_POR_PAGINA = (10, 25, 50, 100)


@dataclass(frozen=True)
class Pagina:
    """Fatia de uma lista com os dados para montar a navegação."""

    itens: list
    numero: int
    por_pagina: int
    total: int

    @property
    def total_paginas(self) -> int:
        return max(1, math.ceil(self.total / self.por_pagina))

    @property
    def inicio(self) -> int:
        """Posição (1-based) do primeiro item exibido; 0 quando vazia."""
        return 0 if self.total == 0 else (self.numero - 1) * self.por_pagina + 1

    @property
    def fim(self) -> int:
        return min(self.numero * self.por_pagina, self.total)

    @property
    def tem_anterior(self) -> bool:
        return self.numero > 1

    @property
    def tem_proxima(self) -> bool:
        return self.numero < self.total_paginas

    def paginas_visiveis(self, vizinhas: int = 2) -> list[int | None]:
        """Números a exibir, com None no lugar das reticências (ex.: 1 … 4 5 6 … 20)."""
        ultima = self.total_paginas
        numeros = {1, ultima}
        numeros.update(range(max(1, self.numero - vizinhas), min(ultima, self.numero + vizinhas) + 1))
        visiveis: list[int | None] = []
        anterior = 0
        for numero in sorted(numeros):
            if numero - anterior == 2:
                visiveis.append(numero - 1)
            elif numero - anterior > 2:
                visiveis.append(None)
            visiveis.append(numero)
            anterior = numero
        return visiveis


def ler_inteiro(texto: str | None, padrao: int) -> int:
    """Converte parâmetro de URL em inteiro positivo; inválido = padrão."""
    try:
        valor = int(texto) if texto else padrao
    except ValueError:
        return padrao
    return valor if valor > 0 else padrao


def ler_por_pagina(texto: str | None) -> int:
    valor = ler_inteiro(texto, POR_PAGINA_PADRAO)
    return valor if valor in OPCOES_POR_PAGINA else POR_PAGINA_PADRAO


def paginar(itens: Sequence, numero: int, por_pagina: int = POR_PAGINA_PADRAO) -> Pagina:
    """Página `numero` de `itens`; número fora do intervalo é ajustado ao limite."""
    total = len(itens)
    total_paginas = max(1, math.ceil(total / por_pagina))
    numero = min(max(1, numero), total_paginas)
    inicio = (numero - 1) * por_pagina
    return Pagina(list(itens[inicio:inicio + por_pagina]), numero, por_pagina, total)


def agregar_por_hora(medicoes: list[dict[str, Any]]) -> list[list]:
    """
    Agrupa as medições em baldes de uma hora: [hora ISO, quantidade, soma, mínimo, máximo].

    Baldes horários se combinam sem perda (soma/quantidade/mín./máx.), então o
    navegador reagrega por dia, semana, mês ou ano sem receber cada medição.
    """
    baldes: dict[str, list] = {}
    for row in medicoes:
        valor = float(row["valor"])
        chave = _hora_iso(row["data_hora"])
        balde = baldes.get(chave)
        if balde is None:
            baldes[chave] = [chave, 1, valor, valor, valor]
        else:
            balde[1] += 1
            balde[2] += valor
            balde[3] = min(balde[3], valor)
            balde[4] = max(balde[4], valor)
    return [
        [chave, quantidade, round(soma, 6), minimo, maximo]
        for chave, quantidade, soma, minimo, maximo in sorted(baldes.values())
    ]


def _hora_iso(value: datetime | str) -> str:
    texto = value.isoformat() if isinstance(value, datetime) else str(value).replace(" ", "T")
    return texto[:13] + ":00"


# Filtros de template (formato pt-BR).

def formatar_milhar(valor: int | float | None) -> str:
    """1234567 -> '1.234.567'."""
    if valor is None:
        return "—"
    return f"{round(valor):,}".replace(",", ".")


def formatar_decimal(valor: int | float | None, casas: int = 2) -> str:
    """1234.5 -> '1.234,50'."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "—"
    return f"{valor:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatar_data(valor: datetime | str | None) -> str:
    """'2026-10-06' -> '06/10/2026'."""
    if not valor:
        return ""
    texto = valor.isoformat() if isinstance(valor, datetime) else str(valor)
    return f"{texto[8:10]}/{texto[5:7]}/{texto[:4]}"


def formatar_data_hora(valor: datetime | str | None) -> str:
    """'2026-10-06T14:30:00' -> '06/10/2026 14:30'."""
    if not valor:
        return ""
    texto = valor.isoformat() if isinstance(valor, datetime) else str(valor).replace(" ", "T")
    return f"{formatar_data(texto)} {texto[11:16]}".strip()


def formatar_iso(valor: datetime | str | None) -> str:
    if not valor:
        return ""
    return valor.isoformat() if isinstance(valor, datetime) else str(valor)


FILTROS_TEMPLATE = {
    "milhar": formatar_milhar,
    "decimal": formatar_decimal,
    "data_br": formatar_data,
    "data_hora_br": formatar_data_hora,
    "iso": formatar_iso,
}
