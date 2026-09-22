from datetime import date

import pandas as pd

from src.services.analytics_service import AnaliticsService

try:
    service = AnaliticsService()

    analise, outliers = service.analisar_leituras_meteriologicas_cidade(
        cidade_id=1,
        data_inicio=date(2026, 6, 1),
        data_fim=date(2026, 12, 1),
    )

    analise, outliers = service.analisar_leituras_qualidade_agua_cidade(
        cidade_id=1,
        data_inicio=date(2026, 6, 1),
        data_fim=date(2026, 12, 1),
    )

    if analise["Estatísticas"]:
        print(pd.DataFrame(analise["Estatísticas"]).to_string(index=False))
    else:
        print("Nenhuma leitura encontrada.")

    if outliers.empty:
        print("Nenhum outlier identificado pelo método IQR.")
    else:
        # Arredonda somente as colunas numéricas.
        print(
            outliers.round(
                {
                    "valor": 2,
                    "Limite Inferior": 2,
                    "Limite Superior": 2,
                }
            ).to_string(index=False)
        )
except Exception as erro:
    print(f"{type(erro).__name__}: {erro}")
# criar_tabelas()
