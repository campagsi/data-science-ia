from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class Utils:
    def __init__(self, menu_title=""):
        self.__menu_title = menu_title

    def montar_painel(self, dados: list) -> Panel:
        console = Console()
        print(dados)
        itens_menu = "\n".join(
            f"{numero} - {item['nome']}" for numero, item in dados.items()
        )
        console.clear()
        console.line(2)
        console.print(
            Panel(itens_menu, title=self.__menu_title, style="bold blue", expand=False)
        )

    def montar_tabela(self, dados: list[dict], title=str):
        tabela = Table(
            title=title,
            style="cyan bold",
            title_style="cyan bold",
        )

        if not dados:
            return tabela

        colunas = list(dados[0])

        for coluna in colunas:
            tabela.add_column(coluna)

        for item in dados:
            # tabela.add_row(*(str(item[coluna]) for coluna in colunas))
            tabela.add_row(
                *(
                    f"{item[coluna]:.2f}"
                    if isinstance(item[coluna], float)
                    else str(item[coluna])
                    for coluna in colunas
                )
            )

        return tabela

    def Validar_Data(self, data: str):
        try:
            datetime.strptime(data, "%d/%m/%Y")
            return True
        except ValueError:
            return False
