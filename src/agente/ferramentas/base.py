"""
A ferramenta: nome, descrição, argumentos tipados e a função que executa.

Conceito
--------
No tool use, o LLM não executa nada: ele lê a ESPECIFICAÇÃO de cada
ferramenta (nome, descrição e JSON Schema dos argumentos) e devolve um pedido
"chame resumo_estatistico com estes argumentos". Quem executa é o nosso código.

Por isso a ferramenta tem três partes, cada uma para um leitor:

- descricao: para o LLM decidir QUANDO usar (o que faz, quando usar, quando não usar);
- argumentos (modelo Pydantic): vira o JSON Schema enviado ao LLM e valida o
  que ele devolver (política POL-06);
- funcao: o código que calcula, recebendo os argumentos já validados.

O retorno passa por normalizar_json(): números arredondados, datas em ISO e
nada que não seja JSON. Retorno compacto = menos tokens = menos custo.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_2.py (saída estruturada)
Documentação: docs/agente/ferramentas.md § 1 e § 2
"""
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

# Retorno compacto: 3 casas bastam (a resposta ao usuário mostra no máximo 2).
CASAS_DECIMAIS = 3


class ErroDeRegra(ValueError):
    """
    Violação de uma regra de negócio, com mensagem que volta ao LLM.

    Exemplos: estação inexistente, série com pontos demais. A mensagem deve
    dizer o que corrigir e nunca conter dado sensível.
    """


@dataclass(frozen=True)
class Ferramenta:
    """
    Uma ferramenta que o LLM pode pedir para executar.

    Args:
        nome: identificador em snake_case, ex.: "resumo_estatistico".
        descricao: texto para o LLM: o que faz, quando usar e quando não usar.
        argumentos: modelo Pydantic dos argumentos (com extra="forbid").
        funcao: recebe os argumentos validados e devolve um dict.
        limite_itens: máximo de itens por lista no retorno. None = o padrão
            do registro (AGENTE_MAX_LINHAS). Ex.: serie_temporal usa 200.

    Example:
        >>> from pydantic import BaseModel, ConfigDict
        >>> class Vazio(BaseModel):
        ...     model_config = ConfigDict(extra="forbid")
        >>> eco = Ferramenta("eco", "Devolve ok.", Vazio, lambda argumentos: {"ok": True})
        >>> eco.executar({})
        {'ok': True}
        >>> sorted(eco.especificacao())
        ['description', 'input_schema', 'name']
    """

    nome: str
    descricao: str
    argumentos: type[BaseModel]
    funcao: Callable[[Any], dict]
    limite_itens: int | None = None

    def especificacao(self) -> dict[str, Any]:
        """
        Especificação no formato interno, que o adaptador do LLM traduz.

        Returns:
            {"name", "description", "input_schema"}, sem as chaves "title" que
            o Pydantic gera (só gastariam tokens).
        """
        return {
            "name": self.nome,
            "description": self.descricao,
            "input_schema": _sem_titulos(self.argumentos.model_json_schema()),
        }

    def executar(self, argumentos: dict[str, Any]) -> dict:
        """
        Valida os argumentos e executa a função.

        Args:
            argumentos: argumentos como vieram do LLM.

        Returns:
            O dict devolvido pela função, ainda sem normalizar.

        Raises:
            pydantic.ValidationError: argumento inválido ou desconhecido.
            ErroDeRegra: regra de negócio violada.
        """
        return self.funcao(self.argumentos.model_validate(argumentos))


def normalizar_json(valor: Any) -> Any:
    """
    Converte um retorno de ferramenta em JSON compacto e seguro.

    Floats com 3 casas, NaN e infinito como None, datas em ISO, tuplas como
    listas e tipos do numpy/pandas como tipos nativos do Python.

    Args:
        valor: dict, lista ou valor simples.

    Returns:
        Estrutura só com dict, list, str, int, float, bool e None.

    Example:
        >>> from datetime import datetime
        >>> normalizar_json({"media": 7.38149, "desvio": float("nan"),
        ...                  "quando": datetime(2026, 6, 1, 6, 30), "itens": (1, 2)})
        {'media': 7.381, 'desvio': None, 'quando': '2026-06-01T06:30:00', 'itens': [1, 2]}
    """
    if isinstance(valor, dict):
        return {str(chave): normalizar_json(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [normalizar_json(item) for item in valor]
    if isinstance(valor, bool) or valor is None or isinstance(valor, str):
        return valor
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    # Conceito: numpy.int64, numpy.float64 etc. têm .item(), que devolve o tipo nativo.
    if hasattr(valor, "item") and not isinstance(valor, (int, float)):
        valor = valor.item()
    if isinstance(valor, Decimal):
        valor = float(valor)
    if isinstance(valor, float):
        return round(valor, CASAS_DECIMAIS) if math.isfinite(valor) else None
    if isinstance(valor, int):
        return valor
    return str(valor)


def _sem_titulos(schema: Any) -> Any:
    """Remove as chaves "title" do JSON Schema do Pydantic, em qualquer nível."""
    if isinstance(schema, dict):
        return {chave: _sem_titulos(item) for chave, item in schema.items() if chave != "title"}
    if isinstance(schema, list):
        return [_sem_titulos(item) for item in schema]
    return schema
