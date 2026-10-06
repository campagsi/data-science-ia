from datetime import date, datetime
from pathlib import Path

from rich.console import Console

from src.cli.menus.painel_opcoes import exibir_painel
from src.cli.utils.menu_utils import Utils
from src.services.analytics_service import AnaliticsService
from src.services.report_service import COLUNAS_ANOMALIAS, COLUNAS_ESTATISTICAS, ReportService

PASTA_RELATORIOS = Path(__file__).resolve().parents[2] / "relatorios"


class Console_APP:
    """
    Consulta interativa: Município → Estação → período → métricas e anomalias
    de todos os parâmetros da estação (D11). Digite 's' para sair e 'v' para voltar.
    """

    def __init__(
        self,
        analise: AnaliticsService | None = None,
        relatorio: ReportService | None = None,
        console: Console | None = None,
        pasta_relatorios: Path = PASTA_RELATORIOS,
    ) -> None:
        self.__analise = analise or AnaliticsService()
        self.__relatorio = relatorio or ReportService()
        self.__console = console or Console()
        self.__utils = Utils()
        self.__pasta_relatorios = Path(pasta_relatorios)

    def run(self) -> None:
        console = self.__console
        etapa = "Municípios"
        erro = ""
        municipios: dict[int, dict] = {}
        estacoes: dict[int, dict] = {}
        pesquisa: dict = {}

        while True:
            console.clear()
            console.line(2)

            match etapa:
                case "Municípios":
                    if not municipios:
                        municipios = dict(enumerate(self.__analise.buscar_municipios(), start=1))
                    opcao = self.__escolher(municipios, "Municípios", erro, "Informe um município: ")
                    erro = ""
                    if opcao == "s":
                        break
                    if opcao is None:
                        erro = "[bold red]A opção selecionada é inválida.[/]"
                        continue
                    pesquisa["municipio_id"] = municipios[opcao]["id"]
                    estacoes = {}
                    etapa = "Estações"

                case "Estações":
                    if not estacoes:
                        estacoes = {
                            numero: {"id": e.id_estacao, "nome": e.nome}
                            for numero, e in enumerate(
                                self.__analise.buscar_estacoes(pesquisa["municipio_id"]), start=1
                            )
                        }
                    opcao = self.__escolher(estacoes, "Estações", erro, "Informe a estação para busca: ")
                    erro = ""
                    if opcao == "s":
                        break
                    if opcao == "v":
                        etapa = "Municípios"
                        continue
                    if opcao is None:
                        erro = "[bold red]A opção selecionada é inválida.[/]"
                        continue
                    pesquisa["estacao_id"] = estacoes[opcao]["id"]
                    etapa = "Período"

                case "Período":
                    if erro:
                        console.print(f"[red bold]{erro}[/]")
                        erro = ""
                    console.print("[italic yellow]Datas no formato dd/mm/aaaa. Digite 's' para sair ou 'v' para voltar.[/]")
                    data_inicio = console.input("Informe a data início: ").strip().lower()
                    if data_inicio in {"s", "v"}:
                        if data_inicio == "s":
                            break
                        etapa = "Estações"
                        continue
                    data_fim = console.input("Informe a data fim: ").strip().lower()
                    if data_fim in {"s", "v"}:
                        if data_fim == "s":
                            break
                        etapa = "Estações"
                        continue

                    validacao = self.__utils.Validar_Datas(data_inicio, data_fim)
                    if validacao["error"]:
                        erro = validacao["mensagem"]
                        continue
                    pesquisa["data_inicio"] = _data(data_inicio)
                    pesquisa["data_fim"] = _data(data_fim)
                    etapa = "Consulta"

                case "Consulta":
                    relatorio = self.__relatorio.generate_report(
                        self.__analise.calculate_metrics(
                            estacao_id=pesquisa["estacao_id"],
                            data_inicio=pesquisa["data_inicio"],
                            data_fim=pesquisa["data_fim"],
                        )
                    )
                    if not relatorio["estatisticas"]:
                        erro = "Não há dados no período selecionado."
                        etapa = "Período"
                        continue

                    self.__exibir(relatorio)
                    console.print(
                        "[bold yellow]Pressione '0' para salvar o relatório em CSV "
                        "ou Enter para voltar ao início.[/]"
                    )
                    if console.input().strip() == "0":
                        arquivos = self.__relatorio.salvar_csv(relatorio, self.__pasta_relatorios)
                        console.print(f"[bold green]Relatório salvo em {arquivos['estatisticas'].parent}[/]")
                        console.input("Pressione Enter para voltar.")
                    etapa = "Municípios"

        console.print("Saindo...")

    def __escolher(self, opcoes: dict[int, dict], menu: str, erro: str, pergunta: str) -> int | str | None:
        """Mostra o menu e devolve o número escolhido, 's', 'v' ou None se inválido."""
        exibir_painel(dados=opcoes, menu=menu, console=self.__console)
        if erro:
            self.__console.print(erro)
        resposta = self.__console.input(pergunta).strip().lower()
        if resposta in {"s", "v"}:
            return resposta
        if resposta.isdecimal() and int(resposta) in opcoes:
            return int(resposta)
        return None

    def __exibir(self, relatorio: dict) -> None:
        console = self.__console
        console.print(
            f"Leituras: {relatorio['leituras']} | medições: {relatorio['medicoes']} "
            f"| anomalias: {len(relatorio['anomalias'])}"
        )
        console.print(self.__utils.montar_tabela(
            [{c: linha[c] for c in COLUNAS_ESTATISTICAS} for linha in relatorio["estatisticas"]],
            "Estatísticas",
        ))
        if relatorio["anomalias"]:
            console.print(self.__utils.montar_tabela(
                [{c: linha[c] for c in COLUNAS_ANOMALIAS} for linha in relatorio["anomalias"]],
                "Anomalias (alerta de qualidade)",
            ))
        else:
            console.print("[green]Nenhuma anomalia identificada (IQR e Z-Score).[/]")


def _data(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()
