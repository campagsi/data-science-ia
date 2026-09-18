from src.database.criar_tabelas import criar_tabelas
from src.injestion.importar_dados import importar_dados
try:
    importar_dados()
except Exception as erro:
    print(erro)
# criar_tabelas()
