"""
Chat do agente analítico no terminal (python main.py --agente e --pergunta "...").

Interface fina: lê a pergunta, chama Agente.perguntar() e mostra a resposta
em Markdown, as fontes (montadas pelo código, política POL-04) e o consumo de
tokens. Toda regra de negócio e de segurança fica no agente, não aqui.

Documentação: docs/agente/arquitetura.md § 11 e docs/manual-execucao.md § 6
"""
from collections.abc import Callable

from rich.console import Console
from rich.markdown import Markdown

from src.agente.contratos import RespostaAgente
from src.agente.guardrails.entrada import PerguntaInvalida
from src.agente.orquestrador import Agente

PALAVRAS_SAIR = {"sair", "exit", "quit"}


def mostrar_resposta(console: Console, resposta: RespostaAgente) -> None:
    """Resposta em Markdown, seguida das fontes e do consumo da pergunta."""
    console.print(Markdown(resposta.texto))
    if resposta.fontes:
        console.print("\n[bold]Fontes:[/bold]")
        for fonte in resposta.fontes:
            # markup=False: a descrição tem colchetes (ex.: ["TIP-PH"]) que o rich leria como estilo.
            console.print(f"  • {fonte.descricao}", markup=False)
    console.print(
        f"[dim]tokens: {resposta.tokens_entrada} de entrada, {resposta.tokens_saida} de saída · "
        f"{resposta.latencia_ms / 1000:.1f} s[/dim]"
    )


def responder_uma(agente: Agente, pergunta: str, console: Console | None = None) -> RespostaAgente | None:
    """
    Responde uma pergunta só (python main.py --pergunta "...").

    Returns:
        A resposta, ou None se a pergunta foi recusada pela validação (POL-05).
    """
    console = console or Console()
    try:
        resposta = agente.perguntar(pergunta)
    except PerguntaInvalida as erro:
        console.print(f"[red]Pergunta inválida:[/red] {erro}")
        return None
    mostrar_resposta(console, resposta)
    return resposta


def conversar(agente: Agente, console: Console | None = None, ler: Callable[[str], str] = input) -> int:
    """
    Chat interativo (python main.py --agente). "sair" ou Ctrl+C encerram.

    A mesma conversa_id é mantida entre as perguntas, para o agente entender
    continuações como "e em julho?".

    Returns:
        Quantidade de perguntas respondidas.
    """
    console = console or Console()
    console.print("[bold]Agente analítico[/bold] — pergunte sobre as medições. Digite [bold]sair[/bold] para encerrar.\n")
    conversa_id, respondidas = None, 0
    while True:
        try:
            pergunta = ler("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if pergunta.lower() in PALAVRAS_SAIR:
            break
        if not pergunta:
            continue
        try:
            resposta = agente.perguntar(pergunta, conversa_id)
        except PerguntaInvalida as erro:
            console.print(f"[red]Pergunta inválida:[/red] {erro}\n")
            continue
        conversa_id = resposta.conversa_id
        respondidas += 1
        console.print("\n[bold]Agente:[/bold]")
        mostrar_resposta(console, resposta)
        console.print()
    console.print("Até logo.")
    return respondidas
