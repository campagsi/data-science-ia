from typing import Any

import pandas as pd


class ReportService:
    def generate_report(self, indicadores: dict[str, Any]) -> dict[str, Any]:
        """Entrega o resultado consolidado em formato estruturado e imprimível."""
        report = {
            "escopo": indicadores.get("escopo", {}),
            "periodo": indicadores.get("periodo", {}),
            "grupos": {},
        }

        for nome, grupo in indicadores.items():
            if nome not in {"meteorologica", "qualidade_agua"}:
                continue
            outliers = grupo.get("outliers", pd.DataFrame())
            report["grupos"][nome] = {
                "analise": grupo.get("analise", {}),
                "outliers": outliers.to_dict(orient="records")
                if isinstance(outliers, pd.DataFrame)
                else outliers,
            }

        return report

    def format_report(self, report: dict[str, Any]) -> str:
        """Converte o relatório estruturado em texto para exibição."""
        linhas = []

        for grupo in report["grupos"].values():
            analise = grupo["analise"]
            outliers = pd.DataFrame(grupo["outliers"])

            if analise["Estatísticas"]:
                linhas.append(pd.DataFrame(analise["Estatísticas"]).to_string(index=False))
            else:
                linhas.append("Nenhuma leitura encontrada.")

            if outliers.empty:
                linhas.append("Nenhum outlier identificado pelo método IQR.")
            else:
                linhas.append(
                    outliers.round(
                        {
                            "valor": 2,
                            "Valor": 2,
                            "Limite Inferior": 2,
                            "Limite Superior": 2,
                        }
                    ).to_string(index=False)
                )

        return "\n".join(linhas)
