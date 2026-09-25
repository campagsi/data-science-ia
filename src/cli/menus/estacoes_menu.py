from rich.console import Console

from src.cli.utils.menu_utils import Utils


class Estacoes_Menu:
    def __init__(self, dados: list):
        self.__estacoes = dados
        self.__utils = Utils(menu_title="Estações")

    def exibir(self):
        console = Console()
        estacoes_index = {}
        mensagem_erro = ""

        if not self.__estacoes:
            console.print(
                "[bold red]Não foi possível carregar os dados.\nTente novamente.[/]"
            )
            return

        estacoes_index = dict(enumerate(self.__estacoes, start=1))

        while True:
            self.__utils.montar_painel(estacoes_index)

            if mensagem_erro:
                console.print("[red bold]Opção selecionada é inválida.[/]")
                mensagem_erro = ""

            opcao = console.input(
                'Iforme a estação ou digite "s" para sair ou "v" para voltar: '
            )

            if (opcao == "s" or opcao == "S") or (opcao == "v" or opcao == "V"):
                return opcao.lower()

            if not opcao.isdecimal() or int(opcao) not in estacoes_index:
                mensagem_erro = "[red bold]Opção selecionada é inválida.[/]"
            else:
                return estacoes_index[int(opcao)]
