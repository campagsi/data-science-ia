from rich.console import Console

from src.cli.utils.menu_utils import Utils


class Selecionar_Periodo_Menu:
    def exibir(self):
        console = Console()
        utils = Utils()
        mensagem_erro = ""
        console.clear()
        console.line(2)

        while True:
            if mensagem_erro:
                console.clear()
                console.line(2)
                console.print(
                    "[red bold]Data informada é inválida.\nFormato esperado DD-MM-YYYY exemplo: 01/06/2026[/]"
                )
                mensagem_erro = ""

            data_inicio = console.input("Informe a data inicial: ")
            data_fim = console.input("Informe a data final: ")

            opcao = {"inicio": data_inicio, "fim": data_fim}

            if (opcao == "s" or opcao == "S") or (opcao == "v" or opcao == "V"):
                return opcao.lower()

            if utils.Validar_Data(opcao["inicio"]) and utils.Validar_Data(opcao["fim"]):
                return opcao
            else:
                mensagem_erro = "[red bold]Data informada é inválida.[/]"
