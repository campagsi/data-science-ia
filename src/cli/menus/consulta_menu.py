from rich.console import Console

from src.cli.utils.menu_utils import Utils


class Consulta_Menu:
    def __init__(self):
        self.__utils = Utils("")

    def selecionar_consulta(self):
        mensagem_erro = ""
        console = Console()
        console.clear()
        console.line(2)

        while True:
            console.clear()
            console.line(2)
            print("antes do painel")

            opcoes = {
                1: {"nome": "Qualidade da água"},
                2: {"nome": "Meteorológico"},
            }

            self.__utils.montar_painel(opcoes)

            if mensagem_erro:
                console.print(mensagem_erro)
                mensagem_erro = ""

            opcao = console.input("Escolha o tipo de consulta: ")

            if (opcao == "s" or opcao == "S") or (opcao == "v" or opcao == "V"):
                return opcao.lower()

            if not opcao.isdecimal():
                mensagem_erro = "[red bold]Opção selecionada é inválida.[/]"
            else:
                return opcao

    def exibir_consulta(self, dados: list, title=str):
        return self.__utils.montar_tabela(dados, title)
