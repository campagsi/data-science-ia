"""
Guardrails de entrada: o que pode chegar ao LLM (políticas POL-05 e POL-02).

Conceito
--------
A pergunta é texto livre digitado por uma pessoa, e passa por dois filtros
ANTES de qualquer coisa (LLM, histórico ou log):

1. POL-05, entrada controlada: de 1 a 1.000 caracteres, sem caracteres de
   controle (bytes invisíveis que podem esconder instruções ou quebrar o log).
   Uma pergunta gigante custaria tokens à toa; uma vazia não tem o que responder.
2. POL-02, dados pessoais: CPF, e-mail e telefone viram marcadores
   ([CPF], [EMAIL], [TELEFONE]) por src/security.py. Os dados ambientais não
   dependem deles, então nada se perde, e nada pessoal sai para o provedor do
   LLM (decisão L1).

Guardrail forte: é código, e o LLM não tem como contorná-lo.

Documentação: docs/agente/guardrails-e-owasp.md § 9 (POL-02, POL-05)
"""
import unicodedata
from dataclasses import dataclass

from src.security import mascarar_texto_livre

TAMANHO_MAXIMO_PERGUNTA = 1000


class PerguntaInvalida(ValueError):
    """Pergunta vazia ou longa demais. A mensagem é mostrada ao usuário (CLI) ou vira HTTP 400 (web)."""


@dataclass(frozen=True)
class PerguntaPreparada:
    """
    Pergunta pronta para o LLM.

    Args:
        texto: a pergunta limpa e mascarada.
        mascarada: True se algum dado pessoal foi trocado por marcador.

    Example:
        >>> PerguntaPreparada("pH em junho?", mascarada=False).texto
        'pH em junho?'
    """

    texto: str
    mascarada: bool


def preparar_pergunta(texto: str) -> PerguntaPreparada:
    """
    Valida o tamanho, remove caracteres de controle e mascara dados pessoais.

    Args:
        texto: pergunta como o usuário digitou.

    Returns:
        PerguntaPreparada com o texto que pode seguir para o LLM.

    Raises:
        PerguntaInvalida: vazia ou com mais de 1.000 caracteres.

    Example:
        >>> preparar_pergunta("  Qual o pH?\\x00 Meu CPF é 529.982.247-25  ")
        PerguntaPreparada(texto='Qual o pH?  Meu CPF é [CPF]', mascarada=True)
        >>> try:
        ...     preparar_pergunta("   ")
        ... except PerguntaInvalida as erro:
        ...     print(erro)
        a pergunta está vazia
    """
    # Conceito: categoria Unicode "C" = caracteres de controle e formatação
    # invisíveis. Quebras de linha e tabulação viram espaço.
    limpo = "".join(" " if unicodedata.category(c).startswith("C") else c for c in texto).strip()
    if not limpo:
        raise PerguntaInvalida("a pergunta está vazia")
    if len(limpo) > TAMANHO_MAXIMO_PERGUNTA:
        raise PerguntaInvalida(
            f"a pergunta tem {len(limpo)} caracteres; o máximo é {TAMANHO_MAXIMO_PERGUNTA}"
        )
    mascarado = mascarar_texto_livre(limpo)
    return PerguntaPreparada(mascarado, mascarada=mascarado != limpo)
