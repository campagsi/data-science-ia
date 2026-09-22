from dotenv import load_dotenv
from os import getenv
from pathlib import Path
from mssql_python import connect

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

AZ_SQL_CONNECTIONSTRING = getenv("AZURE_SQL_CONNECTIONSTRING")

def execute_query(sql: str) -> None:
    '''
    Executa uma instrução SQL no banco de dados.

    Abre uma conexão com o SQL Server utilizando a string de conexão
    configurada em AZ_SQL_CONNECTIONSTRING no .env e executa a instrução SQL
    recebida.

    Args:
        sql (str): Instrução SQL que será executada no banco de dados.

    Returns:
        None
    '''
    if not AZ_SQL_CONNECTIONSTRING:
        raise RuntimeError(
            "AZURE_SQL_CONNECTIONSTRING nao foi configurada. "
            "Crie Data-Science-Ia/.env com a string de conexao do Azure SQL."
        )

    try:
        with connect(AZ_SQL_CONNECTIONSTRING) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)

            # O commit é feito na CONEXÃO (conn), após o cursor executar a query
            conn.commit()

    except Exception as error:
        # Melhorar a mensagem ajuda a não confundir erro de conexão com erro de sintaxe SQL
        print(f"Erro de banco de dados: {error}")
        raise