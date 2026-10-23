"""
O contrato do laudo de anomalia e a validação da resposta do LLM (Fase 11).

Conceito
--------
Saída estruturada: em vez de texto livre, o LLM devolve um JSON com campos
fixos, que o código consegue usar (gravar num CSV, contar por causa, filtrar
por severidade). Mas o LLM pode errar o formato: esquecer um campo, inventar
outro nome ("nivel_insatisfacao" no lugar de "nivel_insatisfeito", a lição do
ia_gen_2.py do curso) ou escrever fora da faixa.

Por isso a resposta passa por um contrato Pydantic com extra="forbid" (POL-06):

    {"registro": "REG-...", "causa_provavel": "falha_sensor", "severidade": 3,
     "justificativa": "Pico isolado sem chuva e com retorno imediato ao patamar."}

e por mais duas conferências:

- o registro do laudo é o da anomalia pedida (o LLM não pode trocar de leitura);
- os números da justificativa vêm do contexto enviado (POL-03, a mesma
  verificação das respostas do chat).

Resposta que falha em qualquer conferência é DESCARTADA, e o motivo vai para o
log em WARNING com o id da política (POL-13), sem o texto do LLM.

Documentação: docs/agente/seguranca-e-prompts.md § 9
"""
import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agente.guardrails.saida import numeros_sem_origem

Causa = Literal["falha_sensor", "evento_real", "inconclusivo"]
_OBJETO_JSON = re.compile(r"\{.*\}", re.DOTALL)


class LaudoAnomalia(BaseModel):
    """
    A classificação de uma anomalia feita pelo LLM.

    Example:
        >>> LaudoAnomalia(registro="REG-1", causa_provavel="evento_real", severidade=2, justificativa="Chuva forte antes.").severidade
        2
    """

    model_config = ConfigDict(extra="forbid")

    registro: str = Field(min_length=1, max_length=60, description="Código do registro da anomalia.")
    causa_provavel: Causa = Field(description="falha_sensor, evento_real ou inconclusivo.")
    severidade: int = Field(ge=1, le=5, description="1 (leve) a 5 (grave).")
    justificativa: str = Field(min_length=1, max_length=400, description="Até 400 caracteres.")


@dataclass(frozen=True)
class ValidacaoLaudo:
    """
    O laudo validado, ou o motivo do descarte.

    Args:
        laudo: o LaudoAnomalia, ou None se descartado.
        politica: política que descartou ("POL-06" ou "POL-03"), ou None.
        motivo: motivo curto, sem espaços e sem o texto do LLM (vai para o log).

    Example:
        >>> ValidacaoLaudo(None, "POL-06", "json_invalido").valido
        False
    """

    laudo: LaudoAnomalia | None
    politica: str | None = None
    motivo: str | None = None

    @property
    def valido(self) -> bool:
        """True se o laudo passou em todas as conferências."""
        return self.laudo is not None


def validar_resposta(texto: str, registro_esperado: str, contexto: str) -> ValidacaoLaudo:
    """
    Confere a resposta do LLM: JSON, contrato, registro e números.

    Args:
        texto: a resposta do LLM (pode vir entre ```json e ```).
        registro_esperado: o registro da anomalia enviada.
        contexto: o texto enviado ao LLM (origem válida dos números).

    Example:
        >>> ok = '{"registro": "REG-1", "causa_provavel": "falha_sensor", "severidade": 3, "justificativa": "Pico isolado."}'
        >>> validar_resposta(ok, "REG-1", "").valido
        True
        >>> validar_resposta(ok.replace('"severidade"', '"nivel"'), "REG-1", "").motivo
        'campos:nivel,severidade'
        >>> validar_resposta(ok, "REG-2", "").motivo
        'registro_trocado'
    """
    achado = _OBJETO_JSON.search(texto)
    if achado is None:
        return ValidacaoLaudo(None, "POL-06", "json_ausente")
    try:
        dados = json.loads(achado.group(0))
    except json.JSONDecodeError:
        return ValidacaoLaudo(None, "POL-06", "json_invalido")
    try:
        laudo = LaudoAnomalia.model_validate(dados)
    except ValidationError as erro:
        # Cuidado: só os NOMES dos campos vão para o log, nunca os valores escritos pelo LLM.
        campos = sorted({str(detalhe["loc"][0]) for detalhe in erro.errors() if detalhe["loc"]})
        return ValidacaoLaudo(None, "POL-06", f"campos:{','.join(campos)}")
    if laudo.registro != registro_esperado:
        return ValidacaoLaudo(None, "POL-06", "registro_trocado")
    sem_origem = numeros_sem_origem(laudo.justificativa, [], contexto=[contexto])
    if sem_origem:
        return ValidacaoLaudo(None, "POL-03", f"numeros_sem_origem:{len(sem_origem)}")
    return ValidacaoLaudo(laudo)
