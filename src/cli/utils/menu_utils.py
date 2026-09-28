from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class Utils:
    def __init__(self, menu_title=""):
        self.__menu_title = menu_title

    def montar_tabela(self, dados: list[dict], title=str) -> Table:
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

    def Validar_Datas(self, dt_inicio: str, dt_fim: str):
        try:
            inicio = datetime.strptime(dt_inicio, "%d/%m/%Y")
            fim = datetime.strptime(dt_fim, "%d/%m/%Y")

            return {
                "error": inicio > fim,
                "mensagem": "A data início não pode ser maior que a data fim"
                if inicio > fim
                else "",
            }

        except ValueError:
            return {
                "error": True,
                "mensagem": "Data inválida, informe a data no formato: dd/mm/yyyy",
            }
