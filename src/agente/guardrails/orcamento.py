"""
Orçamento de uma pergunta: chamadas de ferramenta, tokens e tempo (política POL-07).

Conceito
--------
Cada chamada ao LLM reenvia todo o contexto (system prompt, ferramentas,
histórico e resultados), e cada token custa. Sem limite, um laço em que o LLM
pede ferramentas sem parar consome tokens e tempo indefinidamente: é o risco
LLM10 ("Unbounded Consumption") do OWASP Top 10 para LLM.

O orçamento conta três coisas e para a pergunta na primeira que estourar:

- chamadas de ferramenta (DA6: 6);
- tokens de entrada acumulados em todas as chamadas ao LLM (60.000);
- tempo total desde o início da pergunta (180 s), incluindo novas tentativas.

Ao estourar, o LLM é chamado mais uma vez SEM poder usar ferramentas, para
responder com o que já tem. Guardrail forte: é o código que conta.

Documentação: docs/agente/guardrails-e-owasp.md § 9 (POL-07)
"""
import time
from collections.abc import Callable


class OrcamentoPergunta:
    """
    Contador de consumo de uma pergunta.

    Args:
        max_chamadas: chamadas de ferramenta permitidas (AGENTE_MAX_FERRAMENTAS).
        max_tokens_entrada: tokens de entrada acumulados (AGENTE_MAX_TOKENS_PERGUNTA).
        prazo_segundos: tempo total da pergunta (AGENTE_PRAZO_PERGUNTA_SEGUNDOS).
        relogio: tempo atual em segundos (injetável nos testes).

    Example:
        >>> orcamento = OrcamentoPergunta(max_chamadas=2, max_tokens_entrada=1000, prazo_segundos=60)
        >>> orcamento.registrar_chamadas(2)
        >>> orcamento.motivo_esgotado(), orcamento.restantes()
        ('chamadas', 0)
    """

    def __init__(
        self,
        max_chamadas: int,
        max_tokens_entrada: int,
        prazo_segundos: float,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        """Começa a contar a partir de agora, com tudo zerado."""
        self.__max_chamadas = max_chamadas
        self.__max_tokens = max_tokens_entrada
        self.__prazo = prazo_segundos
        self.__relogio = relogio
        self.__inicio = relogio()
        self.chamadas = 0
        self.tokens_entrada = 0
        self.tokens_saida = 0

    def registrar_chamadas(self, quantidade: int) -> None:
        """Soma as chamadas de ferramenta executadas."""
        self.chamadas += quantidade

    def registrar_tokens(self, entrada: int, saida: int) -> None:
        """Soma os tokens de uma chamada ao LLM (uso real devolvido pela API)."""
        self.tokens_entrada += entrada
        self.tokens_saida += saida

    def restantes(self) -> int:
        """Chamadas de ferramenta que ainda cabem no orçamento."""
        return max(0, self.__max_chamadas - self.chamadas)

    def motivo_esgotado(self) -> str | None:
        """
        Por que o orçamento acabou: "chamadas", "tokens" ou "prazo". None = ainda há orçamento.

        Example:
            >>> agora = [0.0]
            >>> orcamento = OrcamentoPergunta(6, 1000, prazo_segundos=60, relogio=lambda: agora[0])
            >>> agora[0] = 61.0
            >>> orcamento.motivo_esgotado()
            'prazo'
        """
        if self.tokens_entrada >= self.__max_tokens:
            return "tokens"
        if self.__relogio() - self.__inicio >= self.__prazo:
            return "prazo"
        if self.chamadas >= self.__max_chamadas:
            return "chamadas"
        return None

    def permite_ferramentas(self) -> bool:
        """True enquanto o LLM ainda pode pedir ferramentas."""
        return self.motivo_esgotado() is None

    def permite_correcao(self) -> bool:
        """
        True se ainda cabe UMA chamada extra ao LLM para a correção da POL-03.

        A correção não usa ferramenta, então só os tokens e o prazo importam.
        """
        return self.motivo_esgotado() in (None, "chamadas")

    def milissegundos(self) -> int:
        """Tempo decorrido desde o início da pergunta, em milissegundos."""
        return int((self.__relogio() - self.__inicio) * 1000)
