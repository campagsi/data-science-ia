"""
Argumentos das ferramentas, validados pelo Pydantic.

Conceito
--------
Validação de entrada é o guardrail mais barato que existe: o LLM pode pedir
qualquer coisa, e o modelo Pydantic recusa o que não faz sentido ANTES de
qualquer acesso ao banco (política POL-06).

- extra="forbid": um argumento desconhecido ("apagar_tudo": true) é erro, e
  não é ignorado em silêncio. No JSON Schema, isso vira
  "additionalProperties": false.
- Literal: valores fechados (granularidade, tipo de alerta) viram "enum" no
  schema, e o LLM vê exatamente as opções válidas.
- description em todo campo: é o que o LLM lê para preencher o argumento.
- Validadores: regras entre campos (data_fim exige data_inicio, fim >= início).

Os mesmos modelos geram o JSON Schema enviado ao LLM (model_json_schema()) e
validam o que ele devolve (model_validate()): uma única fonte de verdade.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_2.py (a lição do
campo nivel_insatisfeito × nivel_insatisfacao)
Documentação: docs/agente/ferramentas.md § 4 e docs/agente/guardrails-e-owasp.md § 9
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Códigos do projeto: letras maiúsculas, números e hífen (EST-RJ-001, TIP-PH).
PADRAO_CODIGO = r"^[A-Z0-9][A-Z0-9-]{0,49}$"

Alerta = Literal["IQR", "ZSCORE", "IQR+ZSCORE"]
Granularidade = Literal["hora", "dia", "semana", "mes"]
Estatistica = Literal["media", "mediana", "minimo", "maximo", "soma"]

_DESCRICAO_ESTACAO = "Código da estação, ex.: EST-RJ-001. Omitir = todas."
_DESCRICAO_INICIO = "Data inicial AAAA-MM-DD. Sozinha = só esse dia."
_DESCRICAO_FIM = "Data final AAAA-MM-DD, inclusiva. Exige data_inicio."
_DESCRICAO_PARAMETRO = 'Código de um parâmetro, ex.: "TIP-PH". Use listar_parametros para traduzir nomes.'


class SemArgumentos(BaseModel):
    """
    Ferramenta sem argumentos (panorama_dados, listar_parametros).

    Example:
        >>> from pydantic import ValidationError
        >>> SemArgumentos.model_validate({})
        SemArgumentos()
        >>> try:
        ...     SemArgumentos.model_validate({"apagar_tudo": True})
        ... except ValidationError as erro:
        ...     print(erro.errors()[0]["type"])
        extra_forbidden
    """

    model_config = ConfigDict(extra="forbid")


class ComPeriodo(BaseModel):
    """
    Base dos filtros de estação e período, com as regras de datas.

    Mesma regra do LeituraRepository.get_medicoes(): só data_inicio = aquele
    dia; data_inicio e data_fim = intervalo fechado.

    Example:
        >>> from pydantic import ValidationError
        >>> try:
        ...     ComPeriodo(data_inicio="2026-06-30", data_fim="2026-06-01")
        ... except ValidationError as erro:
        ...     print(erro.errors()[0]["msg"])
        Value error, data_fim anterior a data_inicio
    """

    model_config = ConfigDict(extra="forbid")

    estacao: str | None = Field(None, pattern=PADRAO_CODIGO, description=_DESCRICAO_ESTACAO)
    data_inicio: date | None = Field(None, description=_DESCRICAO_INICIO)
    data_fim: date | None = Field(None, description=_DESCRICAO_FIM)

    @model_validator(mode="after")
    def _periodo_coerente(self):
        """data_fim exige data_inicio e não pode ser anterior a ela."""
        if self.data_fim and not self.data_inicio:
            raise ValueError("data_fim exige data_inicio")
        if self.data_inicio and self.data_fim and self.data_fim < self.data_inicio:
            raise ValueError("data_fim anterior a data_inicio")
        return self


class ArgumentosResumo(ComPeriodo):
    """
    Argumentos de resumo_estatistico.

    Example:
        >>> ArgumentosResumo(parametros=["TIP-PH"], data_inicio="2026-06-01").parametros
        ['TIP-PH']
    """

    parametros: list[str] | None = Field(
        None,
        min_length=1,
        max_length=20,
        description='Códigos dos parâmetros, ex.: ["TIP-PH"]. Omitir = todos.',
    )


class ArgumentosAnomalias(ComPeriodo):
    """
    Argumentos de listar_anomalias.

    Example:
        >>> ArgumentosAnomalias(parametro="TIP-TUR", limite=5).ordenar_por
        'extremidade'
    """

    parametro: str | None = Field(None, pattern=PADRAO_CODIGO, description=_DESCRICAO_PARAMETRO + " Omitir = todos.")
    alerta: Alerta | None = Field(None, description="Filtra pelo indicador de alerta. Omitir = todos.")
    ordenar_por: Literal["data", "extremidade"] = Field(
        "extremidade", description="extremidade = maior |Z-Score| primeiro; data = ordem cronológica."
    )
    limite: int = Field(10, ge=1, le=50, description="Quantidade de itens devolvidos (1 a 50). O total vem sempre completo.")


class ArgumentosSerie(ComPeriodo):
    """
    Argumentos de serie_temporal. O período é obrigatório.

    Example:
        >>> ArgumentosSerie(parametro="TIP-TMP", data_inicio="2026-08-01",
        ...                 data_fim="2026-08-31", granularidade="semana").estatistica
        'media'
    """

    parametro: str = Field(pattern=PADRAO_CODIGO, description=_DESCRICAO_PARAMETRO)
    data_inicio: date = Field(description="Data inicial AAAA-MM-DD.")
    data_fim: date = Field(description="Data final AAAA-MM-DD, inclusiva.")
    granularidade: Granularidade = Field(description="Tamanho de cada ponto da série.")
    estatistica: Estatistica = Field(
        "media", description="Como agregar cada ponto. soma é a mais útil para chuva (mm acumulados)."
    )


class ArgumentosPerfil(ComPeriodo):
    """
    Argumentos de perfil_horario.

    Example:
        >>> ArgumentosPerfil(parametro="TIP-RAD").estacao is None
        True
    """

    parametro: str = Field(pattern=PADRAO_CODIGO, description=_DESCRICAO_PARAMETRO)


# --- Inferência (Fase 6) ----------------------------------------------------------

Turno = Literal["todas", "dia", "noite"]
Operador = Literal[">", ">=", "<", "<="]
_DESCRICAO_TURNO = 'Horas consideradas: "todas", "dia" (6h às 17h59) ou "noite" (18h às 5h59).'


class ArgumentosComparacao(BaseModel):
    """
    Argumentos de comparar_periodos: o mesmo parâmetro em dois recortes (A e B).

    Dia × noite = o mesmo intervalo de datas com turno_a="dia" e turno_b="noite".

    Example:
        >>> ArgumentosComparacao(parametro="TIP-TMP", inicio_a="2026-06-01", fim_a="2026-06-30",
        ...                      inicio_b="2026-06-01", fim_b="2026-06-30", turno_a="dia", turno_b="noite").turno_b
        'noite'
    """

    model_config = ConfigDict(extra="forbid")

    parametro: str = Field(pattern=PADRAO_CODIGO, description=_DESCRICAO_PARAMETRO)
    estacao: str | None = Field(None, pattern=PADRAO_CODIGO, description=_DESCRICAO_ESTACAO)
    inicio_a: date = Field(description="Início do período A (AAAA-MM-DD).")
    fim_a: date = Field(description="Fim do período A, inclusivo.")
    turno_a: Turno = Field("todas", description=_DESCRICAO_TURNO)
    inicio_b: date = Field(description="Início do período B (AAAA-MM-DD).")
    fim_b: date = Field(description="Fim do período B, inclusivo.")
    turno_b: Turno = Field("todas", description=_DESCRICAO_TURNO)

    @model_validator(mode="after")
    def _periodos_coerentes(self):
        """Cada período com fim >= início, e A diferente de B."""
        if self.fim_a < self.inicio_a or self.fim_b < self.inicio_b:
            raise ValueError("fim anterior ao início em um dos períodos")
        if (self.inicio_a, self.fim_a, self.turno_a) == (self.inicio_b, self.fim_b, self.turno_b):
            raise ValueError("os períodos A e B são iguais; mude as datas ou os turnos")
        return self


class ArgumentosCorrelacao(ComPeriodo):
    """
    Argumentos de correlacao.

    Example:
        >>> ArgumentosCorrelacao(parametros=["TIP-TMP", "TIP-UMI"]).metodo
        'spearman'
    """

    parametros: list[str] = Field(min_length=2, max_length=6, description='De 2 a 6 códigos, ex.: ["TIP-TMP", "TIP-UMI"].')
    metodo: Literal["spearman", "pearson"] = Field(
        "spearman", description="spearman (por postos, robusta a picos; padrão) ou pearson (linear)."
    )

    @model_validator(mode="after")
    def _sem_repeticao(self):
        """Cada parâmetro uma vez só."""
        if len(set(self.parametros)) != len(self.parametros):
            raise ValueError("parâmetros repetidos")
        return self


class ArgumentosProbabilidade(ComPeriodo):
    """
    Argumentos de probabilidade_evento: P(evento) e, opcionalmente, P(evento | condição).

    Example:
        >>> argumentos = ArgumentosProbabilidade(evento_parametro="TIP-CHU", evento_operador=">", evento_valor=0,
        ...     condicao_parametro="TIP-UMI", condicao_operador=">", condicao_valor=90)
        >>> argumentos.condicao_valor
        90.0
    """

    evento_parametro: str = Field(pattern=PADRAO_CODIGO, description="Parâmetro do evento, ex.: TIP-CHU.")
    evento_operador: Operador = Field(description="Comparação do evento.")
    evento_valor: float = Field(description="Valor de referência do evento, na unidade do parâmetro.")
    condicao_parametro: str | None = Field(None, pattern=PADRAO_CODIGO, description="Parâmetro da condição (opcional).")
    condicao_operador: Operador | None = Field(None, description="Comparação da condição.")
    condicao_valor: float | None = Field(None, description="Valor de referência da condição.")

    @model_validator(mode="after")
    def _condicao_completa(self):
        """A condição tem os três campos ou nenhum."""
        campos = (self.condicao_parametro, self.condicao_operador, self.condicao_valor)
        if any(c is not None for c in campos) and not all(c is not None for c in campos):
            raise ValueError("a condição precisa de condicao_parametro, condicao_operador e condicao_valor juntos")
        return self
