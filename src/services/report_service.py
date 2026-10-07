from pathlib import Path
from typing import Any

import pandas as pd

# Colunas exibidas no texto; o CSV leva todas.
COLUNAS_ESTATISTICAS = (
    "Estação", "Parâmetro", "Unidade", "Quantidade", "Média", "Mediana",
    "Desvio Padrão", "Variância", "IQR", "Mínimo", "Máximo", "Anomalias",
)
COLUNAS_ANOMALIAS = (
    "Estação", "Parâmetro", "Data", "Registro", "Valor",
    "Limite Inferior", "Limite Superior", "Z-Score", "Alerta",
)


class ReportService:
    def generate_report(self, indicadores: dict[str, Any]) -> dict[str, Any]:
        """Entrega o resultado de AnaliticsService.calculate_metrics() em formato estruturado."""
        return {
            "escopo": indicadores.get("escopo", {}),
            "periodo": indicadores.get("periodo", {}),
            "leituras": indicadores.get("leituras", 0),
            "medicoes": indicadores.get("medicoes", 0),
            "estatisticas": list(indicadores.get("estatisticas", [])),
            "anomalias": list(indicadores.get("anomalias", [])),
        }

    def format_report(self, report: dict[str, Any]) -> str:
        """Converte o relatório estruturado em texto para o log ou o console."""
        if not report["estatisticas"]:
            return "Nenhuma leitura encontrada."

        linhas = [
            f"Leituras analisadas: {report['leituras']} | medições: {report['medicoes']} "
            f"| anomalias: {len(report['anomalias'])}",
            self.__tabela(report["estatisticas"], COLUNAS_ESTATISTICAS),
        ]
        if report["anomalias"]:
            linhas.append(self.__tabela(report["anomalias"], COLUNAS_ANOMALIAS))
        else:
            linhas.append("Nenhuma anomalia identificada (IQR e Z-Score).")
        return "\n".join(linhas)

    def salvar_csv(self, report: dict[str, Any], pasta: Path | str) -> dict[str, Path]:
        """Grava estatisticas.csv e anomalias.csv (separador ;), criando a pasta se preciso."""
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        arquivos = {
            "estatisticas": pasta / "estatisticas.csv",
            "anomalias": pasta / "anomalias.csv",
        }
        colunas = {"estatisticas": None, "anomalias": list(COLUNAS_ANOMALIAS) + ["Unidade"]}
        for nome, caminho in arquivos.items():
            pd.DataFrame(report[nome], columns=colunas[nome]).to_csv(
                caminho, index=False, sep=";", encoding="utf-8-sig"
            )
        return arquivos

    @staticmethod
    def __tabela(dados: list[dict], colunas: tuple[str, ...]) -> str:
        tabela = pd.DataFrame(dados)[list(colunas)]
        numericas = tabela.select_dtypes("number").columns
        tabela[numericas] = tabela[numericas].round(2)
        return tabela.to_string(index=False)
