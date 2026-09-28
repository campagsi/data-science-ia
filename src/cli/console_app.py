from rich.columns import Columns
from rich.console import Console

from src.cli.menus.painel_opcoes import painel_opcoes
from src.cli.utils.menu_utils import Utils
from src.services.analytics_service import AnaliticsService


class Console_APP:
    def __init__(self) -> None:
        self.__analitics_service = AnaliticsService()
        self.__utils = Utils()

    # self.__cidades = self.__analitics_service.bucar_cidades()
    # self.__cidades_menu = Cidades_Menu(self.__cidades)
    # self.__consulta_menu = Consulta_Menu()

    def run(self):
        console = Console()
        menu_opcoes = {
            "Cidades": {},
            "Estações": {},
            "Tipos_Consulta": {
                1: {"nome": "Qualidade da água"},
                2: {"nome": "Meteorológico"},
            },
        }
        menu_selecionado = {"atual": "Cidades", "anterior": "", "error": ""}
        dados_pesquisa = {
            "id_estacao": 0,
            "id_cidade": 0,
            "data_inicio": "",
            "data_fim": "",
        }

        while True:
            match menu_selecionado["atual"]:
                case "Cidades":
                    console.clear()
                    console.line(2)
                    if not menu_opcoes["Cidades"]:
                        cidades = self.__analitics_service.buscar_cidades()
                        menu_opcoes["Cidades"] = dict(enumerate(cidades, start=1))

                    painel_opcoes.exibir(
                        dados=menu_opcoes["Cidades"], menu=menu_selecionado["atual"]
                    )

                    if menu_selecionado["error"]:
                        console.print(menu_selecionado["error"])
                        menu_selecionado["error"] = ""

                    opcao_selecionada = console.input("Informe uma cidade: ")
                    if opcao_selecionada.lower() == "s":
                        print("Saindo...")
                        break
                    if (
                        not opcao_selecionada.isdecimal()
                        or int(opcao_selecionada) not in menu_opcoes["Cidades"]
                    ):
                        menu_selecionado["error"] = (
                            "[bold red]A opção selecionada é inválida.[/]"
                        )
                        continue

                    menu_selecionado["atual"] = "Estações"
                    menu_selecionado["anterior"] = "Cidades"
                    dados_pesquisa["id_cidade"] = opcao_selecionada

                case "Estações":
                    console.clear()
                    console.line(2)
                    if not menu_opcoes["Estações"]:
                        estacoes = self.__analitics_service.buscar_estacao_by_cidade_id(
                            int(dados_pesquisa["id_cidade"])
                        )
                        menu_opcoes["Estações"] = dict(enumerate(estacoes, start=1))

                    painel_opcoes.exibir(
                        dados=menu_opcoes["Estações"], menu=menu_selecionado["atual"]
                    )

                    if menu_selecionado["error"]:
                        console.print(menu_selecionado["error"])
                        menu_selecionado["error"] = ""

                    opcao_selecionada = input("Informe a estação para busca: ")

                    if opcao_selecionada.lower() == "v":
                        menu_selecionado["atual"] = "Cidades"
                        menu_selecionado["anterior"] = ""
                        continue
                    elif opcao_selecionada.lower() == "s":
                        console.print("Saindo...")
                        break
                    elif (
                        not opcao_selecionada.isdecimal()
                        or int(opcao_selecionada) not in menu_opcoes["Estações"]
                    ):
                        menu_selecionado["error"] = (
                            "[bold red]A opção selecionada é inválida.[/]"
                        )
                        continue

                    dados_pesquisa["id_estacao"] = int(opcao_selecionada)

                    menu_selecionado["atual"] = "Selecao_Datas"
                    menu_selecionado["anterior"] = "Estações"

                case "Selecao_Datas":
                    console.clear()
                    console.line(2)
                    if menu_selecionado["error"]:
                        console.print(f"[red bold]{menu_selecionado['error']}[/]")
                        menu_selecionado["error"] = ""

                    data_inicio = input("Informe a data início: ")
                    data_fim = input("Informe a data fim: ")

                    if data_inicio == "v" or data_fim == "v":
                        menu_selecionado["atual"] = "Estações"
                        menu_selecionado["anterior"] = "Cidades"
                    elif data_inicio == "s" or data_fim == "s":
                        console.print("Saindo...")
                        break

                    validacao_data = self.__utils.Validar_Datas(data_inicio, data_fim)

                    if validacao_data["error"]:
                        menu_selecionado["error"] = validacao_data["mensagem"]
                        continue

                    dados_pesquisa["data_inicio"] = data_inicio
                    dados_pesquisa["data_fim"] = data_fim
                    menu_selecionado["atual"] = "Tipo_Consulta"
                    menu_selecionado["anterior"] = "Estações"

                case "Tipo_Consulta":
                    console.clear()
                    console.line(2)
                    painel_opcoes.exibir(dados=menu_opcoes["Tipos_Consulta"], menu="")

                    if menu_selecionado["error"]:
                        console.print(menu_selecionado["error"])
                        menu_selecionado["error"] = ""

                    opcao_selecionada = console.input("Informe a consulta: ")

                    if opcao_selecionada.lower() == "v":
                        menu_selecionado["atual"] = "Estações"
                        menu_selecionado["anterior"] = "Cidades"
                        continue
                    elif opcao_selecionada.lower() == "s":
                        console.print("Saindo...")
                        break
                    elif (
                        not opcao_selecionada.isdecimal()
                        or int(opcao_selecionada) not in menu_opcoes["Tipos_Consulta"]
                    ):
                        menu_selecionado["error"] = (
                            "[bold red]A opção selecionada é inválida.[/]"
                        )
                        continue

                    menu_selecionado["atual"] = "Consulta"
                case "Consulta":
                    console.clear()
                    console.line(2)
                    if opcao_selecionada == "1":
                        analise, outliers = (
                            self.__analitics_service.analisar_leituras_qualidade_agua_estacao(
                                dados_pesquisa["id_estacao"],
                                dados_pesquisa["data_inicio"],
                                dados_pesquisa["data_fim"],
                            )
                        )
                    else:
                        analise, outliers = (
                            self.__analitics_service.analisar_leituras_meteriologicas_estacao(
                                dados_pesquisa["id_estacao"],
                                dados_pesquisa["data_inicio"],
                                dados_pesquisa["data_fim"],
                            )
                        )

                    estatisticas = self.__utils.montar_tabela(
                        analise["Estatísticas"], "Estatísticas"
                    )

                    outlier = self.__utils.montar_tabela(outliers, "Outliers")

                    console.print(Columns([estatisticas, outlier], padding=(0, 2)))
                    console.print("[bold yellow]Pressione 'Enter' para voltar.[/]")
                    console.input()
                    menu_selecionado["atual"] = "Cidades"
                    continue
                # mensagem

                # elif (
                #     not opcao_selecionada.isdecimal()
                #     or int(opcao_selecionada) not in estacoes_menu
                # ):
                #     msg_selecao_invalida = (
                #         "[bold red]A opção selecionada é inválida.[/]"
                #     )

            # self.__opcao = ""
            # # Exibe menu de Cidades
            # self.__opcao = self.__cidades_menu.exibir()

            # # Busca e exibe o menu de estações
            # estacoes = self.__analitics_service.buscar_estacao_by_cidade_id(
            #     self.__opcao["id"]
            # )
            # estacao_menu = Estacoes_Menu(estacoes)
            # self.__opcao = estacao_menu.exibir()

            # if self.__opcao["id"]:
            #     # Exibe a seleção de período
            #     data_consulta = Selecionar_Periodo_Menu().exibir()
            #     print(data_consulta)
            #     opcao_consulta = self.__consulta_menu.selecionar_consulta()

            #     if opcao_consulta == "1":
            #         analise, outliers = (
            #             self.__analitics_service.analisar_leituras_qualidade_agua_estacao(
            #                 self.__opcao["id"],
            #                 data_consulta["inicio"],
            #                 data_consulta["fim"],
            #             )
            #         )

            #         table_estatisticas = self.__consulta_menu.exibir_consulta(
            #             analise["Estatísticas"], "Qualidade da água"
            #         )

            #         table_outliers = self.__consulta_menu.exibir_consulta(
            #             outliers, "Qualidade da água"
            #         )

            #         console.print(table_estatisticas)
            #         console.print(table_outliers)

            #         console.input()

        #  if self.__opcao['data_inicio'] and self.__opcao['data_fim']:
