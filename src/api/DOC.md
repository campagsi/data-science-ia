# Documentacao da camada de API

## 1. Objetivo

A pasta `src/api` implementa a API responsavel por disponibilizar o dataset
bruto de monitoramento ambiental. O arquivo `data_set.json` pertence a esta
camada e e exposto por uma rota HTTP para que o pipeline de ingestao possa
consumi-lo.

A implementacao utiliza FastAPI e orientacao a objetos para separar as
responsabilidades da camada de API:

```text
Cliente HTTP
    |
    v
DatasetController
    |
    v
DatasetService
    |
    v
DatasetRepository
    |
    v
src/api/data_set.json
```

Essa separacao evita que a rota HTTP leia diretamente o arquivo. O controller
cuida da comunicacao HTTP, o service coordena a regra da aplicacao e o
repository conhece a forma de armazenamento do dataset.

## 2. Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `__init__.py` | Exporta o objeto principal `app`. |
| `app.py` | Cria e configura a aplicacao FastAPI. |
| `dataset_controller.py` | Define a rota HTTP do dataset e converte falhas em respostas HTTP. |
| `dataset_service.py` | Coordena a consulta do dataset. |
| `dataset_repository.py` | Abre, interpreta e valida a estrutura basica do JSON. |
| `data_set.json` | Arquivo com os registros brutos de monitoramento ambiental. |

## 3. Classe `DatasetRepository`

Arquivo: `dataset_repository.py`

### Responsabilidade

`DatasetRepository` e a camada de acesso aos dados. Ela encapsula o caminho do
arquivo JSON e concentra a operacao de leitura do dataset. As outras camadas
nao precisam conhecer `Path`, `open` ou `json.load`.

### Construtor `__init__`

```python
DatasetRepository(dataset_path: Path | None = None)
```

#### Parametro

- `dataset_path`: caminho opcional para o arquivo JSON.
- Quando nenhum caminho e informado, o repository usa automaticamente
  `data_set.json` localizado na mesma pasta do modulo, por meio de
  `Path(__file__).with_name("data_set.json")`.

O parametro opcional facilita testes unitarios, pois um arquivo temporario ou
um dataset de teste pode ser injetado sem alterar o arquivo oficial da API.

#### Estado interno

O caminho e armazenado no atributo privado `__dataset_path`. O uso do atributo
privado impede que outras camadas alterem acidentalmente a origem dos dados.

### Metodo `get_all`

```python
get_all() -> list[dict[str, Any]]
```

#### Funcao

Abre o arquivo configurado, interpreta seu conteudo como JSON e retorna todos
os registros como uma lista de dicionarios.

#### Fluxo do metodo

1. Abre o arquivo com codificacao UTF-8.
2. Executa `json.load` para converter o JSON em objetos Python.
3. Verifica se o resultado e uma lista.
4. Retorna a lista de registros.

#### Tratamento de erros

- `FileNotFoundError`: convertido em `RuntimeError` com a mensagem
  `Dataset da API nao foi encontrado.`
- `json.JSONDecodeError`: convertido em `RuntimeError` com a mensagem
  `Dataset da API possui JSON invalido.`
- Se o JSON for valido, mas tiver uma estrutura diferente de uma lista, o
  metodo levanta `RuntimeError` com a mensagem
  `Dataset da API deve conter uma lista de registros.`

A validacao garante o contrato minimo esperado pela camada de servico e pela
resposta da API.

## 4. Classe `DatasetService`

Arquivo: `dataset_service.py`

### Responsabilidade

`DatasetService` representa a camada de servico da API. Seu papel e coordenar
o acesso aos dados sem conhecer detalhes de HTTP ou de leitura de arquivo.

Neste momento a regra de negocio e simples: disponibilizar todos os registros
brutos. A classe cria uma fronteira para que regras futuras, como filtros,
paginacao, validacao adicional ou transformacao dos registros, sejam
adicionadas sem colocar essa logica no controller.

### Construtor `__init__`

```python
DatasetService(repository: DatasetRepository | None = None)
```

#### Parametro

- `repository`: dependencia opcional do tipo `DatasetRepository`.
- Quando nao informado, o service cria um `DatasetRepository` padrao.

A injecao opcional de dependencia permite substituir o repository em testes.
Por exemplo, um repository falso pode retornar uma lista pequena sem ler o
arquivo real.

#### Estado interno

A dependencia e armazenada em `__repository`, um atributo privado usado pelos
metodos do servico.

### Metodo `listar_dados`

```python
listar_dados() -> list[dict[str, Any]]
```

#### Funcao

Solicita ao repository todos os registros e devolve o resultado ao controller.
O service nao abre arquivos, nao monta respostas HTTP e nao trata detalhes de
FastAPI.

#### Fluxo do metodo

```text
DatasetController.listar_dados()
    -> DatasetService.listar_dados()
        -> DatasetRepository.get_all()
            -> lista de registros JSON
```

Se o repository levantar `RuntimeError`, o erro sobe para o controller, que o
transforma em uma resposta HTTP adequada.

## 5. Classe `DatasetController`

Arquivo: `dataset_controller.py`

### Responsabilidade

`DatasetController` e a camada de entrada HTTP. Ela registra a rota da API,
chama o service e converte erros internos em respostas compreensiveis para o
cliente.

O controller nao le o JSON diretamente e nao deve conter regras de persistencia
ou analise dos dados.

### Construtor `__init__`

```python
DatasetController(service: DatasetService | None = None)
```

#### Parametro

- `service`: instancia opcional de `DatasetService`.
- Quando nao informado, o controller cria um service padrao.

A injecao permite testar a rota com um service controlado, sem depender do
arquivo real.

#### Criacao do router

O construtor cria um `APIRouter` com:

- prefixo `/api/v1`;
- tag `Dataset`, usada na documentacao automatica do FastAPI.

Em seguida, registra a rota `GET /data-set` apontando para o metodo
`listar_dados`.

### Configuracao da rota `GET /api/v1/data-set`

A rota possui as seguintes configuracoes:

- metodo HTTP: `GET`;
- caminho final: `/api/v1/data-set`;
- resposta esperada: `list[dict[str, Any]]`;
- resumo OpenAPI: `Retorna o dataset bruto de monitoramento`.

A anotacao `response_model` informa ao FastAPI que a resposta deve ser uma
lista de objetos JSON. Ela tambem participa da documentacao OpenAPI gerada
automaticamente.

### Metodo `listar_dados`

```python
listar_dados() -> list[dict[str, Any]]
```

#### Funcao

Recebe a chamada HTTP, solicita os dados ao service e retorna a lista para o
FastAPI serializar como JSON.

#### Tratamento de erros

O metodo captura `RuntimeError` vindo do service ou repository e cria uma
`HTTPException` com:

- status HTTP `500`;
- campo `detail` contendo a mensagem do problema.

Assim, falhas como arquivo ausente, JSON invalido ou estrutura incorreta nao
ficam expostas como excecoes Python sem tratamento na camada HTTP.

## 6. Modulo `app.py`

O arquivo `app.py` nao define uma classe propria. Ele fornece a funcao de
fabrica `create_app` e cria a instancia global `app`.

### Funcao `create_app`

```python
create_app() -> FastAPI
```

#### Funcao

Cria e configura uma instancia de `FastAPI` com:

- titulo: `API de Ingestao de Dados Ambientais`;
- versao: `1.0.0`;
- descricao sobre a disponibilizacao do dataset bruto.

Depois, instancia `DatasetController` e inclui o router na aplicacao.

A funcao de fabrica torna a criacao da aplicacao explicita e facilita testes,
porque uma nova instancia pode ser criada sem depender de estado global.

### Endpoint `GET /health`

O modulo registra ainda um endpoint simples de verificacao:

```text
GET /health
```

Resposta esperada:

```json
{
  "status": "ok"
}
```

Esse endpoint confirma que o processo HTTP esta ativo. Ele nao valida a
conexao com o banco nem a existencia do dataset.

### Objeto global `app`

```python
app = create_app()
```

O objeto `app` e o ponto de entrada usado pelo Uvicorn:

```bash
python -m uvicorn src.api.app:app --reload
```

A expressao `src.api.app:app` significa:

- modulo Python: `src.api.app`;
- objeto ASGI: `app`.

## 7. Modulo `__init__.py`

O arquivo importa e exporta `app`:

```python
from .app import app

__all__ = ["app"]
```

Isso permite importar a aplicacao pela camada de API de forma mais simples:

```python
from src.api import app
```

## 8. Contrato HTTP da API

### `GET /api/v1/data-set`

Retorna o conteudo bruto de `data_set.json`.

Resposta de sucesso: `200 OK`.

Formato simplificado:

```json
[
  {
    "cidade_nome": "Rio de Janeiro",
    "cidade_estado": "RJ",
    "operador_codigo": "OP-RJ-01",
    "estacao_codigo": "EST-RJ-001",
    "data_hora": "2026-06-01T00:00:00",
    "temperatura": "20.5",
    "fonte": "SIMULADO"
  }
]
```

Os registros sao devolvidos no formato bruto. A conversao de strings para
numeros, booleanos e datas pertence ao pipeline de ingestao e nao a esta API.

### Resposta de erro: `500 Internal Server Error`

Quando o dataset nao pode ser carregado, a API retorna uma resposta semelhante
a:

```json
{
  "detail": "Dataset da API nao foi encontrado."
}
```

## 9. Execucao local

Na raiz de `Data-Science-Ia`, com o ambiente virtual ativado:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn src.api.app:app --reload
```

A API fica disponivel por padrao em:

```text
http://127.0.0.1:8000
```

Rotas principais:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/api/v1/data-set
```

A documentacao interativa do FastAPI fica disponivel em:

```text
http://127.0.0.1:8000/docs
```

## 10. Integracao com a ingestao

O pipeline carrega a variavel `FONTE_DADOS` em `src/config.py` e a
`DataClient` (`src/ingestion/data_client.py`) a usa para consultar a API:

```env
FONTE_DADOS="http://127.0.0.1:8000"
```

A ingestao monta a chamada para:

```text
{FONTE_DADOS}/api/v1/data-set
```

`FONTE_DADOS` e obrigatoria: sem ela, `load_config()` falha antes da ingestao. O mesmo valor e gravado em `Leituras.fonte` (maximo de 100 caracteres).
O pipeline nao le o arquivo `data_set.json` diretamente; o arquivo e usado
somente por esta API, que precisa estar em execucao durante o pipeline.

## 11. Principios de organizacao aplicados

- **Responsabilidade unica:** cada classe possui uma funcao principal.
- **Separacao de camadas:** HTTP, regra de aplicacao e armazenamento ficam
  separados.
- **Inversao simples de dependencia:** service e controller aceitam suas
  dependencias no construtor.
- **Testabilidade:** repositories e services podem ser substituidos por
  implementacoes de teste.
- **Versionamento de rota:** o prefixo `/api/v1` permite evoluir o contrato
  sem quebrar imediatamente os consumidores existentes.
- **Contrato explicito:** o endpoint declara o formato da lista retornada.
