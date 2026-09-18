import requests
from os import getenv
from dotenv import load_dotenv
from src.models.cidade_model import Cidade_Model
#from src.models.operador_model import Operador_Model
from src.repository.cidade_repository import CidadeRepository

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

BASE_URL = getenv('MOCK_API')

# (Presume-se que a sua função execute_query já esteja definida ou importada aqui)

# def importar_dados_cidades():
#     resposta = requests.get(f'{BASE_URL}/cidades', timeout=10)
#     resposta.raise_for_status()
#     dados = resposta.json()

#     # 1. Cria uma lista vazia para guardar o texto de cada linha
#     valores_formatados = []

#     # 2. Percorre os dados e formata cada cidade como: (id, 'nome', 'estado')
#     for cidade in dados:
#         # Usamos .replace("'", "''") para evitar erro caso a cidade tenha apóstrofo no nome (ex: Pau d'Arco)
#         nome_seguro = cidade['nome'].replace("'", "''")
#         texto_valor = f"('{nome_seguro}', '{cidade['estado']}')"
#         valores_formatados.append(texto_valor)

#     # 3. Junta todos os textos da lista usando uma vírgula entre eles
#     valores_sql = ",\n".join(valores_formatados)

#     # 4. Monta a instrução final ÚNICA
#     query_completa = f"INSERT INTO Cidades(nome, estado) VALUES \n{valores_sql}"

#     # 5. Executa no banco (passando apenas 1 argumento, como a sua função exige)
#     execute_query(query_completa)

#     print("Processo concluído! Todas as cidades foram gravadas de uma só vez.")


# def importar_dados_operadores():
#     try:
#         # Supondo que o endpoint da sua mock API para operadores seja /operadores
#         resposta = requests.get(f'{BASE_URL}/operadores', timeout=20)
#         resposta.raise_for_status()
#         dados = resposta.json()



#         valores_formatados = []

#         for item in dados:
#             # 1. O Pydantic recebe o dicionário da API. Se vier um 'id', ele guarda; se não vier, vira None.
#             operador = Operador_Model(**item)

#             # Tratamento de aspas simples para evitar quebra no SQL
#             nome_seguro = operador.nome.replace("'", "''")

#             # 2. O SEGREDO ESTÁ AQUI: Nós extraímos apenas codigo, nome e tipo. O 'operador.id' fica esquecido.
#             texto_valor = f"('{operador.codigo}', '{nome_seguro}', '{operador.tipo}', {operador.cidade_id})"
#             valores_formatados.append(texto_valor)

#         valores_sql = ",\n".join(valores_formatados)

#         # 3. Na instrução INSERT, declaramos apenas as 3 colunas. O banco vai gerar o 'id' sozinho.
#         query_completa = f"INSERT INTO Operadores(codigo, nome, tipo, cidade_id) VALUES \n{valores_sql}"
#         # print(valores_formatados)
#         execute_query(query_completa)

#         print("Processo concluído! Operadores gravados com IDs gerados pelo banco.")
#     except Exception as error:
#         print(error)

def importar_cidades(dados):
    try:
        cidades = []
        #cidades_tuples = [(cidade.nome, cidade.estado) for cidade in cidades]
        for cidade in dados:
       
            cidade_model = Cidade_Model(**{'nome': cidade['cidade_nome'], 'estado': cidade['cidade_estado']})
            if cidade_model not in cidades: 
                cidades.append(cidade_model)
        cidades_tuples = [(cidade.nome, cidade.estado) for cidade in cidades]
        CidadeRepository.create_many_cidades(cidades_tuples)
        print(cidades)
        print("Processo concluído! Todas as cidades foram gravadas de uma só vez.")
    except requests.RequestException as error:
        print(f'Erro ao acessar a API: {error}')
        raise
    except Exception as error:
        print(f'Erro durante a importação: {error}')
        raise

def sanitizar_dados(dados) -> dict:
    cidades = []
    for item in dados:
        
        cidades.append({
                'nome': item['cidade_nome'],
                'estado': item['cidade_estado']  
            })
    return {'cidades': cidades}

def importar_dados():
    try:       
        resposta = requests.get(f'{BASE_URL}/data-set', timeout=30)
        resposta.raise_for_status()
        dados = resposta.json()
        print(importar_cidades(dados))
     #   importar_dados_operadores()
    except requests.RequestException as error:
        print(f'Erro ao acessar a API: {error}')
        raise
    except Exception as error:
        print(f'Erro durante a importação: {error}')
        raise


