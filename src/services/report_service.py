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
