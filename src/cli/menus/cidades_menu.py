from rich.console import Console

from src.cli.utils.menu_utils import Utils


class Cidades_Menu:
    def __init__(self, dados: list):
        self.__cidades = dados
        self.__utils = Utils(menu_title="Cidades")

    def exibir(self):
        console = Console()
        cidades_index = {}
        mensagem_erro = ""

        if not self.__cidades:
            console.print(
                "[bold red]Não foi possível carregar os dados.\nTente novamente.[/]"
            )
            return

        cidades_index = dict(enumerate(self.__cidades, start=1))

        while True:
            self.__utils.montar_painel(cidades_index)

            if mensagem_erro:
                console.print("[red bold]Opção selecionada é inválida.[/]")
                mensagem_erro = ""

            opcao = console.input('Iforme a cidade ou digite "s" para sair: ')

            if opcao == "s" or opcao == "S":
                return opcao.lower()

            if not opcao.isdecimal() or int(opcao) not in cidades_index:
                mensagem_erro = "[red bold]Opção selecionada é inválida.[/]"
            else:
                return cidades_index[int(opcao)]
