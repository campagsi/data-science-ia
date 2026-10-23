"""
Seleção de ferramentas em lote, pela Batch API da Anthropic (50% de desconto).

Conceito
--------
Batch API: em vez de uma chamada por vez, com resposta na hora, o lote envia
todas as perguntas de uma vez e devolve os resultados quando terminar (em geral
em menos de 1 hora, no máximo 24 h), pela METADE do preço.

Limitação: o lote faz UMA chamada por pergunta. O laço do agente precisa de
várias (pede ferramenta → recebe o resultado → responde), e cada volta do laço
teria que esperar um lote inteiro. Por isso o lote mede só a PRIMEIRA decisão
do modelo, a escolha das ferramentas, que é a métrica mais sensível às
descrições das ferramentas e ao system prompt:

    pergunta → [system + ferramentas + pergunta] → lote → ferramentas pedidas

O recall medido assim é um limite inferior: uma ferramenta que o modelo só
chamaria na segunda volta conta como não chamada. Os números, as recusas e a
recuperação exigem a avaliação completa (sem --lote).

Documentação: docs/agente/avaliacao.md § 6
"""
import time
from collections.abc import Callable, Sequence
from typing import Any

from src.agente.avaliacao.golden import CasoGolden
from src.agente.avaliacao.metricas import contar_selecao, razao
from src.agente.contratos import Mensagem
from src.agente.guardrails.entrada import preparar_pergunta
from src.agente.llm.cliente_anthropic import ClienteAnthropic, resposta_da_api
from src.logger import logger

INTERVALO_CONSULTA_SEGUNDOS = 60


def pedidos_do_lote(casos: Sequence[CasoGolden], llm: ClienteAnthropic, system: str, ferramentas: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Um pedido da Batch API por caso, com os mesmos parâmetros do agente.

    As continuações ("e em julho?") ficam de fora: sem a conversa anterior, não
    fazem sentido sozinhas. A pergunta passa pela mesma preparação do agente
    (tamanho e máscara de dados pessoais, POL-02 e POL-05).

    Example:
        >>> llm = ClienteAnthropic("chave", "claude-haiku-5-5", cliente=object())
        >>> casos = [CasoGolden(id="seg-01", categoria="seguranca", pergunta="Meu CPF é 529.982.247-25. pH?")]
        >>> pedido = pedidos_do_lote(casos, llm, "system", [])[0]
        >>> pedido["custom_id"], pedido["params"]["messages"][0]["content"]
        ('seg-01', 'Meu CPF é [CPF]. pH?')
    """
    return [
        {
            "custom_id": caso.id,
            "params": llm.parametros_do_pedido(system, [Mensagem.usuario(preparar_pergunta(caso.pergunta).texto)], ferramentas),
        }
        for caso in casos
        if caso.continua_de is None
    ]


def selecionar_em_lote(
    pedidos: list[dict[str, Any]],
    sdk: Any,
    esperar: Callable[[float], None] = time.sleep,
    intervalo_segundos: float = INTERVALO_CONSULTA_SEGUNDOS,
) -> dict[str, tuple[str, ...]]:
    """
    Envia o lote, espera terminar e devolve as ferramentas pedidas em cada pergunta.

    Args:
        pedidos: saída de pedidos_do_lote().
        sdk: cliente do SDK (anthropic.Anthropic). Os testes passam um falso.
        esperar: função de espera (injetável nos testes).
        intervalo_segundos: tempo entre as consultas ao estado do lote.

    Returns:
        custom_id → nomes das ferramentas pedidas. Pedidos com erro, cancelados
        ou expirados ficam de fora, com um aviso no log.

    Example:
        >>> from types import SimpleNamespace as N
        >>> class LotesFalsos:
        ...     def create(self, requests): return N(id="lote-1", processing_status="in_progress")
        ...     def retrieve(self, id_lote): return N(id=id_lote, processing_status="ended")
        ...     def results(self, id_lote):
        ...         mensagem = N(content=[N(type="tool_use", id="t1", name="panorama_dados", input={})],
        ...                      stop_reason="tool_use", usage=N(input_tokens=1, output_tokens=1))
        ...         return [N(custom_id="pan-01", result=N(type="succeeded", message=mensagem))]
        >>> esperas = []
        >>> selecionar_em_lote([], N(messages=N(batches=LotesFalsos())), esperar=esperas.append)
        {'pan-01': ('panorama_dados',)}
        >>> esperas
        [60]
    """
    lote = sdk.messages.batches.create(requests=pedidos)
    logger.info(f"Avaliação: lote {lote.id} enviado com {len(pedidos)} perguntas")
    while lote.processing_status != "ended":
        esperar(intervalo_segundos)
        lote = sdk.messages.batches.retrieve(lote.id)
    selecao = {}
    for item in sdk.messages.batches.results(lote.id):
        if item.result.type == "succeeded":
            selecao[item.custom_id] = tuple(c.nome for c in resposta_da_api(item.result.message).chamadas)
        else:
            logger.warning(f"Avaliação: pergunta {item.custom_id} do lote terminou como {item.result.type}")
    return selecao


def metricas_do_lote(casos: Sequence[CasoGolden], selecao: dict[str, tuple[str, ...]]) -> dict[str, float | None]:
    """
    Precisão e recall da seleção na primeira chamada.

    Example:
        >>> casos = [CasoGolden(id="desc-01", categoria="descritiva", pergunta="pH?", ferramentas_esperadas=["resumo_estatistico"])]
        >>> metricas_do_lote(casos, {"desc-01": ("resumo_estatistico", "listar_anomalias")})
        {'precisao_selecao': 0.5, 'recall_selecao': 1.0, 'respondidos': 1}
    """
    vp = fp = fn = 0
    respondidos = 0
    for caso in casos:
        if caso.id in selecao:
            respondidos += 1
            a, b, c = contar_selecao(caso.ferramentas_esperadas, selecao[caso.id], caso.deve_recusar)
            vp, fp, fn = vp + a, fp + b, fn + c
    return {"precisao_selecao": razao(vp, vp + fp), "recall_selecao": razao(vp, vp + fn), "respondidos": respondidos}
