from datetime import datetime

from src.cli import Console_APP

try:
    # teste = {
    #     "Medição": "Temperatura da água",
    #     "Unidade": "°C",
    #     "Quantidade": 60,
    #     "Média": 23.22,
    #     "Mediana": 23.15,
    #     "Desvio Padrão": 1.2,
    # }

    # for t in teste:
    #     print(t)
    #     print
    console = Console_APP()

    console.run()
except Exception as erro:
    print(f"{type(erro).__name__}: {erro}")
# criar_tabelas()
