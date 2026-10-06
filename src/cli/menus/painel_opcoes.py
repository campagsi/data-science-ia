from rich.console import Console
from rich.panel import Panel

# Primeiro menu da CLI: não tem para onde voltar.
MENU_INICIAL = "Municípios"


def exibir_painel(dados: dict, menu: str, console: Console | None = None):
    console = console or Console()

    if not dados:
        console.print(
            "[bold red]Não foi possível carregar os dados.\nTente novamente.[/]"
        )
        return

    itens_menu = "\n".join(
        f"{numero} - {item['nome']}" + (f" ({item['sigla']})" if item.get("sigla") else "")
        for numero, item in dados.items()
    )
    menu_title = f"Lista de {menu}" if menu else ""
    console.print(Panel(itens_menu, title=menu_title, style="bold cyan", expand=False))

    msg_acoes = "[italic yellow]Digite 's' para sair.[/]"

    if menu != MENU_INICIAL:
        msg_acoes += "[italic yellow] ou 'v' para voltar.[/]"

    console.print(msg_acoes)
