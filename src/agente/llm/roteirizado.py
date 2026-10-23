"""
LLM simulado com respostas pré-definidas (roteiro).

Conceito
--------
Para testar o laço do agente não é preciso um LLM de verdade: basta algo que
cumpra o contrato LLMClient. O LLMRoteirizado devolve, em ordem, as respostas
de um roteiro, e guarda tudo o que recebeu. Assim os testes conferem o que o
agente ENVIOU ao LLM (ex.: se o resultado da ferramenta foi anexado), sem
rede, sem chave e sem custo.

É o mesmo papel do "LLM simulado" do ia_gen_1.py do módulo, com uma diferença:
aqui o roteiro é explícito, e o teste falha se o agente chamar o LLM mais
vezes do que o previsto.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_1.py
Documentação: docs/agente/avaliacao.md § 2
"""
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from src.agente.contratos import Mensagem
from src.agente.llm.base import RespostaLLM


@dataclass(frozen=True)
class EntradaLLM:
    """
    Uma chamada recebida pelo LLM roteirizado: o que o agente enviou.

    Example:
        >>> EntradaLLM("system", (), ()).permitir_ferramentas
        True
    """

    system: str
    mensagens: tuple[Mensagem, ...]
    ferramentas: tuple[dict[str, Any], ...]
    permitir_ferramentas: bool = True


class RoteiroEsgotado(RuntimeError):
    """O agente chamou o LLM mais vezes do que o roteiro previa."""


class LLMRoteirizado:
    """
    LLMClient que devolve as respostas de um roteiro, na ordem.

    Um item do roteiro pode ser uma exceção: ela é lançada naquela chamada,
    para simular falhas do provedor (ex.: ErroProvedorLLM por tempo limite).

    Args:
        roteiro: respostas (RespostaLLM) ou exceções, na ordem de uso.

    Example:
        >>> from src.agente.contratos import ChamadaFerramenta, Mensagem
        >>> llm = LLMRoteirizado([
        ...     RespostaLLM(chamadas=[ChamadaFerramenta("c1", "panorama_dados")]),
        ...     RespostaLLM(texto="Há 1 estação com dados."),
        ... ])
        >>> llm.gerar("system", [Mensagem.usuario("Que dados você tem?")], []).chamadas[0].nome
        'panorama_dados'
        >>> llm.gerar("system", [], []).texto
        'Há 1 estação com dados.'
        >>> len(llm.chamadas_recebidas), llm.restantes
        (2, 0)
        >>> try:
        ...     llm.gerar("system", [], [])
        ... except RoteiroEsgotado as erro:
        ...     print(erro)
        roteiro esgotado: o LLM foi chamado 3 vezes, mas o roteiro tinha 2 respostas
    """

    def __init__(self, roteiro: Iterable[RespostaLLM | BaseException]) -> None:
        """Guarda o roteiro e a lista vazia de entradas recebidas."""
        self.__roteiro: deque[RespostaLLM | BaseException] = deque(roteiro)
        self.__tamanho = len(self.__roteiro)
        self.chamadas_recebidas: list[EntradaLLM] = []

    @property
    def restantes(self) -> int:
        """Respostas do roteiro ainda não usadas."""
        return len(self.__roteiro)

    def gerar(
        self,
        system: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[dict[str, Any]],
        permitir_ferramentas: bool = True,
    ) -> RespostaLLM:
        """Registra a entrada e devolve (ou lança) o próximo item do roteiro."""
        # Por quê: tuple() tira uma "foto" da lista. O orquestrador continua
        # anexando mensagens à mesma lista depois desta chamada. Sem a cópia,
        # o teste veria as mensagens futuras e não o que foi enviado agora.
        self.chamadas_recebidas.append(EntradaLLM(system, tuple(mensagens), tuple(ferramentas), permitir_ferramentas))

        if not self.__roteiro:
            raise RoteiroEsgotado(
                f"roteiro esgotado: o LLM foi chamado {len(self.chamadas_recebidas)} vezes, "
                f"mas o roteiro tinha {self.__tamanho} respostas"
            )
        item = self.__roteiro.popleft()
        if isinstance(item, BaseException):
            raise item
        return item
