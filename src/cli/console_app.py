import os

import pandas as pd
from rich.columns import Columns
from rich.console import Console

from src.cli.menus.painel_opcoes import exibir_painel
from src.cli.utils.menu_utils import Utils
from src.services.analytics_service import AnaliticsService
from src.services.report_service import ReportService


class Console_APP:
    def __init__(self) -> None:
        self.__analitics_service = AnaliticsService()
        self.__utils = Utils()
        self.__report_service = ReportService()

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

                    exibir_painel(
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
                    cidade = menu_opcoes["Cidades"][int(opcao_selecionada)]
                    dados_pesquisa["id_cidade"] = cidade["id"]
                    menu_opcoes["Estações"] = {}

                case "Estações":
                    console.clear()
                    console.line(2)

                    if not menu_opcoes["Estações"]:
                        estacoes = self.__analitics_service.buscar_estacao_by_cidade_id(
                            int(dados_pesquisa["id_cidade"])
                        )
                        menu_opcoes["Estações"] = dict(enumerate(estacoes, start=1))

                    exibir_painel(
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

                    estacao = menu_opcoes["Estações"][int(opcao_selecionada)]
                    dados_pesquisa["id_estacao"] = estacao["id"]

                    menu_selecionado["atual"] = "Selecao_Datas"
                    menu_selecionado["anterior"] = "Estações"

                case "Selecao_Datas":
                    console.clear()
                    console.line(2)
                    if menu_selecionado["error"]:
                        console.print(f"[red bold]{menu_selecionado['error']}[/]")
                        menu_selecionado["error"] = ""

                    data_inicio = input("Informe a data início: ")
                    if data_inicio == "s":
                        console.print("Saindo...")
                        break

                    if data_inicio == "v":
                        menu_selecionado["atual"] = "Estações"
                        menu_selecionado["anterior"] = "Cidades"
                        continue

                    data_fim = input("Informe a data fim: ")

                    if data_fim == "s":
                        console.print("Saindo...")
                        break

                    if data_fim == "v":
                        menu_selecionado["atual"] = "Estações"
                        menu_selecionado["anterior"] = "Cidades"
                        continue

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
                    exibir_painel(dados=menu_opcoes["Tipos_Consulta"], menu="")

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
                    menu_selecionado["error"] = ""
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

                    if (
                        isinstance(analise, dict)
                        and analise.get("Estatísticas")
                        and isinstance(outliers, list)
                    ):
                        estatisticas = self.__utils.montar_tabela(
                            analise["Estatísticas"], "Estatísticas"
                        )

                        outlier = self.__utils.montar_tabela(outliers, "Outliers")

                        console.print(Columns([estatisticas, outlier], padding=(0, 2)))
                        console.print(
                            "[bold yellow]Pressione '0' para salvar um relatório ou qualquer tecla para voltar ao início.[/]"
                        )
                        opcao_selecionada = console.input()
                        if opcao_selecionada == "0":
                            pasta = "relatorios"

                            pd.DataFrame(analise["Estatísticas"]).to_csv(
                                os.path.join(pasta, "estatisticas.csv"),
                                index=False,
                                sep=";",
                                encoding="utf-8-sig",
                            )

                            pd.DataFrame(outliers).to_csv(
                                os.path.join(pasta, "outliers.csv"),
                                index=False,
                                sep=";",
                                encoding="utf-8-sig",
                            )

                        console.print(
                            f"[bold green] Rellatório salvo em {os.path.join(pasta)}[/]"
                        )

                        console.print("Pressione qualquer tecla para voltar")
                        console.input()

                        menu_selecionado["atual"] = "Cidades"
                        continue

                    else:
                        menu_selecionado["atual"] = "Selecao_Datas"
                        menu_selecionado["anterior"] = "Estações"
                        menu_selecionado["error"] = (
                            "[bold red]Não há dados na data selecionada.[/]"
                        )
                        continue
