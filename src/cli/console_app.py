from datetime import datetime
from typing import Literal

from rich.console import Console

from src.cli.menus.cidades_menu import Cidades_Menu
from src.cli.menus.consulta_menu import Consulta_Menu
from src.cli.menus.estacoes_menu import Estacoes_Menu
from src.cli.menus.selecionar_periodo_menu import Selecionar_Periodo_Menu
from src.services.analytics_service import AnaliticsService


class Console_APP:
    def __init__(self) -> None:
        self.__opcao = ""
        self.__analitics_service = AnaliticsService()
        self.__cidades = self.__analitics_service.bucar_cidades()
        self.__cidades_menu = Cidades_Menu(self.__cidades)
        self.__consulta_menu = Consulta_Menu()

    def run(self):
        console = Console()
        while self.__opcao != "exit":
            self.__opcao = ""
            # Exibe menu de Cidades
            self.__opcao = self.__cidades_menu.exibir()

            # Busca e exibe o menu de estações
            estacoes = self.__analitics_service.buscar_estacao_by_cidade_id(
                self.__opcao["id"]
            )
            estacao_menu = Estacoes_Menu(estacoes)
            self.__opcao = estacao_menu.exibir()

            if self.__opcao["id"]:
                # Exibe a seleção de período
                data_consulta = Selecionar_Periodo_Menu().exibir()
                print(data_consulta)
                opcao_consulta = self.__consulta_menu.selecionar_consulta()

                if opcao_consulta == "1":
                    analise, outliers = (
                        self.__analitics_service.analisar_leituras_qualidade_agua_estacao(
                            self.__opcao["id"],
                            data_consulta["inicio"],
                            data_consulta["fim"],
                        )
                    )

                    table_estatisticas = self.__consulta_menu.exibir_consulta(
                        analise["Estatísticas"], "Qualidade da água"
                    )

                    table_outliers = self.__consulta_menu.exibir_consulta(
                        outliers, "Qualidade da água"
                    )

                    console.print(table_estatisticas)
                    console.print(table_outliers)

                    console.input()

        #  if self.__opcao['data_inicio'] and self.__opcao['data_fim']:
