from rich.console import Console
from rich.panel import Panel


class painel_opcoes:
    def __init__():
        pass

    @staticmethod
    def exibir(dados: dict, menu: str):
        console = Console()

        if not dados:
            console.print(
                "[bold red]Não foi possível carregar os dados.\nTente novamente.[/]"
            )
            return

        itens_menu = "\n".join(
            f"{numero} - {item['nome']}" for numero, item in dados.items()
        )
        console.clear()
        console.line(2)
        menu_title = f"Lista de {menu}" if menu else ""
        console.print(
            Panel(itens_menu, title=menu_title, style="bold cyan", expand=False)
        )

        msg_acoes = "[italic yellow]Digite 's' para sair.[/]"

        if menu != "Cidades":
            msg_acoes += "[italic yellow] ou 'v' para voltar.[/]"

        console.print(msg_acoes)
