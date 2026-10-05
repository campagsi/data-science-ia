# Manual de execução

## Requisitos

Antes de executar o projeto, certifique-se de que o ambiente atende aos requisitos mínimos:

- Python 3.10 ou superior
- pip atualizado
- acesso ao banco de dados configurado
- arquivo `.env` com variáveis necessárias

## 1. Preparar o ambiente

Crie um ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente:

```bash
# Windows
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate
```

## 2. Instalar dependências

```bash
pip install -r requirements.txt
```

No PowerShell, caso a execução de scripts esteja bloqueada:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

## 3. Configurar variáveis de ambiente

Crie `Data-Science-Ia/.env` com base no `.env.example` e informe a string do Azure SQL:

> **Compatibilidade com o enunciado:** a configuração e o código atuais usam Azure SQL. O enunciado original cita SQLite ou PostgreSQL; confirme que Azure SQL é aceito para a entrega. O manual descreve a implementação atual, não altera essa exigência.

```env
AZURE_SQL_CONNECTIONSTRING="Server=tcp:seu-servidor.database.windows.net,1433;Database=seu_banco;UID=seu_usuario;PWD=sua_senha;Encrypt=yes;TrustServerCertificate=no"
MOCK_API="http://127.0.0.1:8000"
```

Nao use `DB_HOST`, `DB_PORT`, `DB_USER` ou `DB_PASSWORD`: essas variaveis pertencem a uma configuracao PostgreSQL e nao sao lidas pelo codigo atual.

## 4. Criar banco e tabelas

O pipeline chama `criar_tabelas()` antes de persistir os dados; ele cria somente as tabelas que ainda não existem.

Para **apagar e recriar** as tabelas, execute a partir da pasta `Data-Science-Ia`:

```bash
python -m src.database.criar_tabelas
```

Atenção:

- a execução direta desse módulo chama `recriar_tabelas()` e apaga todos os dados;
- em um banco sem tabelas, a criação falha porque `__criar_tabela_estacoes()` executa `ALTER TABLE Leituras` antes de a tabela `Leituras` existir (ver pendências da Fase 7 em [analise-implementacao.md](analise-implementacao.md));
- o schema não possui restrições de unicidade: executar o pipeline novamente com o mesmo dataset duplica cidades, operadores, estações e leituras.

## 5. Iniciar a API de ingestao

A API disponibiliza o dataset no endpoint:

```text
GET http://127.0.0.1:8000/api/v1/data-set
```

Inicie o servidor com:

```bash
python -m uvicorn src.api.app:app --reload
```

O endpoint de verificacao fica em `GET /health`.

## 6. Executar a aplicação

```bash
python main.py
```

O pipeline consulta exclusivamente a API configurada em `MOCK_API`. Essa
variavel e obrigatoria; sem ela, a configuracao falha antes da ingestao.

## 7. Verificar resultados

O fluxo deve:

- carregar o JSON bruto
- normalizar strings numéricas, booleanas e data/hora
- validar registros e intervalos
- persistir os dados no banco
- executar consultas e estatísticas
- exibir o relatório final ou salvar os resultados

## 8. Executar os testes

Os testes não precisam da API em execução nem do banco do Azure. Com o ambiente virtual ativado, a partir da pasta `Data-Science-Ia`:

```bash
python -m pytest tests
```

Sem configuração adicional, os testes unitários são executados e os de integração são ignorados. O guia completo (testes de integração em SQL Server de teste, cobertura, execução de testes específicos e problemas comuns) está na seção 4 de [plano-testes.md](plano-testes.md).

## Estrutura executada

A execução segue a seguinte ordem lógica:

```text
configuração -> ingestão -> validação -> persistência -> análise -> relatório
```

## Dicas

- mantenha `.env` fora do controle de versão
- sempre atualize o `.env.example` quando novas variáveis forem adicionadas
- teste cada módulo separadamente antes de rodar o pipeline completo
