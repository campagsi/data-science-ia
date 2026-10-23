"""
Interface única dos clientes de LLM.

Conceito
--------
Uma interface diz O QUE um componente faz, sem dizer COMO. Em Python, isso é
um typing.Protocol: qualquer classe com um método gerar() de mesma assinatura
"é" um LLMClient, sem precisar herdar de nada (tipagem estrutural, ou "duck
typing" verificado pelo type checker).

O LLM só faz duas coisas: devolver texto ou pedir ferramentas. Quem executa
as ferramentas é o orquestrador. Por isso a resposta (RespostaLLM) tem o
texto, as chamadas pedidas e o uso de tokens, que define o custo.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_1.py (tokens)
Documentação: docs/agente/arquitetura.md § 4
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, get_args, runtime_checkable

from src.agente.contratos import ChamadaFerramenta, Mensagem

# Por que o LLM parou de gerar, no formato interno (o adaptador traduz o do fornecedor):
# fim = resposta completa; ferramentas = pediu ferramentas; limite_tokens = cortada
# pelo max_tokens; recusa = o modelo recusou por segurança.
MotivoParada = Literal["fim", "ferramentas", "limite_tokens", "recusa"]
MOTIVOS_PARADA: tuple[str, ...] = get_args(MotivoParada)


@dataclass(frozen=True)
class RespostaLLM:
    """
    O que o LLM devolveu numa chamada.

    Args:
        texto: texto gerado. Pode vir junto com chamadas (ex.: "Vou consultar...").
        chamadas: ferramentas pedidas. Vazio = resposta final.
        tokens_entrada: tokens enviados (system + histórico + ferramentas + resultados).
        tokens_saida: tokens gerados (inclui o raciocínio interno do modelo).
        motivo_parada: "fim", "ferramentas", "limite_tokens" ou "recusa".
        bruto: blocos originais do fornecedor, devolvidos intactos na chamada
            seguinte (ver Mensagem.bruto).

    Example:
        >>> RespostaLLM(texto="O pH médio foi 7,30.").pediu_ferramentas
        False
        >>> pedido = RespostaLLM(chamadas=[ChamadaFerramenta("c1", "panorama_dados")], tokens_entrada=900)
        >>> pedido.pediu_ferramentas, pedido.chamadas[0].nome
        (True, 'panorama_dados')
    """

    texto: str = ""
    chamadas: tuple[ChamadaFerramenta, ...] = ()
    tokens_entrada: int = 0
    tokens_saida: int = 0
    motivo_parada: MotivoParada = "fim"
    bruto: tuple[Any, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Converte em tuplas, recusa tokens negativos e confere o motivo da parada."""
        object.__setattr__(self, "chamadas", tuple(self.chamadas))
        object.__setattr__(self, "bruto", tuple(self.bruto))
        if self.tokens_entrada < 0 or self.tokens_saida < 0:
            raise ValueError("tokens não podem ser negativos")
        if self.motivo_parada not in MOTIVOS_PARADA:
            raise ValueError(f"motivo de parada inválido: {self.motivo_parada!r}")

    @property
    def pediu_ferramentas(self) -> bool:
        """True se o LLM pediu ferramentas. False se esta é a resposta final."""
        return bool(self.chamadas)


@runtime_checkable
class LLMClient(Protocol):
    """
    Contrato de qualquer cliente de LLM usado pelo agente.

    Example:
        >>> class SempreOla:
        ...     def gerar(self, system, mensagens, ferramentas, permitir_ferramentas=True):
        ...         return RespostaLLM(texto="olá")
        >>> isinstance(SempreOla(), LLMClient)
        True
    """

    def gerar(
        self,
        system: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[dict[str, Any]],
        permitir_ferramentas: bool = True,
    ) -> RespostaLLM:
        """
        Envia a conversa ao LLM e devolve a resposta.

        Args:
            system: system prompt (papel, regras e contexto).
            mensagens: histórico no formato interno, terminando na pergunta,
                nos resultados de ferramentas ou numa mensagem de sistema.
            ferramentas: especificações (nome, descrição, JSON Schema).
            permitir_ferramentas: False = o LLM deve responder SEM pedir
                ferramentas (resposta forçada). As especificações continuam
                sendo enviadas iguais.

        Cuidado: no Claude Haiku 5.5, mudar o system ou as ferramentas no meio
        de uma pergunta invalida os blocos de raciocínio já enviados (erro 400).
        Por isso a resposta forçada não tira as ferramentas: só as proíbe.

        Returns:
            Texto e/ou pedidos de ferramenta, com o uso de tokens.

        Raises:
            ErroProvedorLLM: falha de rede, tempo limite ou erro do provedor.
        """
        ...


class ErroProvedorLLM(Exception):
    """
    Falha ao falar com o provedor do LLM (rede, tempo limite, chave inválida...).

    O adaptador converte as exceções do SDK nesta. A mensagem deve ser curta e
    nunca conter a chave nem cabeçalhos HTTP (docs/agente/seguranca-e-prompts.md § 7).
    O orquestrador transforma o erro numa resposta amigável ao usuário.
    """
