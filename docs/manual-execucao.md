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
CHAVE_CRIPTOGRAFIA="chave Fernet compartilhada pelo time"
PEPPER_HASH="segredo compartilhado pelo time (opcional)"
FONTE_DADOS="API_MOCK"
```

| Variável | Obrigatória | Uso |
|---|---|---|
| `AZURE_SQL_CONNECTIONSTRING` | sim | Conexão com o banco |
| `MOCK_API` | sim | URL da API de ingestão |
| `CHAVE_CRIPTOGRAFIA` | sim | Criptografia reversível do e-mail do operador. A aplicação não inicia sem ela. |
| `PEPPER_HASH` | não | Segredo do hash de CPF e nome; vazio = SHA-256 puro |
| `FONTE_DADOS` | não | Valor gravado em `Leituras.fonte`; padrão `API_MOCK` |

A `CHAVE_CRIPTOGRAFIA` é gerada uma única vez e compartilhada com o time fora do Git:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use a mesma `CHAVE_CRIPTOGRAFIA` e o mesmo `PEPPER_HASH` em todas as máquinas (ver [seguranca-lgpd.md](seguranca-lgpd.md)).

Os logs de cada execução ficam em `logs/` (fora do Git): `pipeline_AAAAMMDD_HHMMSS.log` com a execução e `rejeitados_AAAAMMDD_HHMMSS.log` com tudo o que não foi importado.

Nao use `DB_HOST`, `DB_PORT`, `DB_USER` ou `DB_PASSWORD`: essas variaveis pertencem a uma configuracao PostgreSQL e nao sao lidas pelo codigo atual.

## 4. Criar banco e tabelas

O schema da Parte 2 (modelo 3FN) é mantido **somente** pelos scripts SQL da pasta `sql/`. A aplicação Python não cria nem altera tabelas.

| Script | Uso |
|---|---|
| [sql/ddl_banco_relacional.sql](../sql/ddl_banco_relacional.sql) | Estado **completo e atual** do schema: tabelas, chaves e índices. Usado para criar um banco do zero. **Começa com `DROP TABLE IF EXISTS`: apaga todas as tabelas e dados.** |
| [sql/migrations/](../sql/migrations/) | Alterações incrementais (`VNNN__descricao.sql`) para levar um banco **já existente** ao estado do DDL, sem perder dados. |
| [sql/dml_populacao.sql](../sql/dml_populacao.sql) | Carga inicial de estados e parâmetros (fase 3 do [TODO](todo-idempotencia.md); ainda vazio). |

### Banco novo (vazio)

Execute o DDL e depois o DML. As migrations não são necessárias, porque o DDL já contém todas elas; se forem executadas, não alteram nada, por serem idempotentes.

```bash
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/ddl_banco_relacional.sql
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/dml_populacao.sql
```

### Banco existente (com dados)

**Não execute o DDL.** Aplique apenas as migrations que ainda não foram aplicadas, em ordem de número:

```bash
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/migrations/V001__descricao.sql
```

O `-f 65001` faz o `sqlcmd` ler o arquivo em UTF-8; sem ele, acentos e símbolos como `°`, `µ` e `²` são gravados errados.

O `dml_populacao.sql` também pode ser executado em um banco existente a qualquer momento: ele usa `MERGE`, não duplica estados nem parâmetros e aplica ajustes de nome, unidade e faixa.

Os mesmos scripts podem ser abertos e executados no SSMS ou no Azure Data Studio. Depois de qualquer execução, confira se o banco ficou igual ao DDL com as consultas da Fase 0 de [todo-idempotencia.md](todo-idempotencia.md).

### Como criar uma migration (campo, tabela ou índice novo)

1. Criar `sql/migrations/VNNN__descricao.sql` com o próximo número livre (ex.: `V001__leituras_codigo_registro.sql`).
2. Escrever o script **idempotente**, protegendo cada alteração para que reexecutar não dê erro nem duplique nada:

   ```sql
   IF COL_LENGTH('dbo.Leituras', 'codigo_registro') IS NULL
       ALTER TABLE dbo.Leituras ADD codigo_registro VARCHAR(50) NULL;
   GO
   IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_Leituras_CodigoRegistro')
       CREATE UNIQUE INDEX UQ_Leituras_CodigoRegistro ON dbo.Leituras (codigo_registro);
   GO
   ```

3. Na **mesma entrega**, atualizar o `ddl_banco_relacional.sql` para o estado final, como se a migration sempre tivesse existido.
4. Nunca editar uma migration já aplicada em algum banco ou já enviada ao Git: corrigir com uma nova migration.
5. Mudanças de estrutura precisam de aprovação do time antes de ir para o banco.

Os testes de integração aplicam o DDL e, em seguida, todas as migrations (`tests/integration/conftest.py`), o que também confirma que elas são idempotentes.

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

Ao iniciar, `iniciar_aplicacao()` executa, nesta ordem:

1. `configurar_logs()`: cria `logs/pipeline_AAAAMMDD_HHMMSS.log` e `logs/rejeitados_AAAAMMDD_HHMMSS.log`;
2. `load_config()`: exige `AZURE_SQL_CONNECTIONSTRING`, `MOCK_API` e `CHAVE_CRIPTOGRAFIA`;
3. `configurar_seguranca()`: valida a chave Fernet e o pepper.

Se qualquer passo falhar, a aplicação registra a causa com nível `CRITICAL` e termina com código `1`, sem mostrar senhas nem chaves. Depois, abre a interface de consulta no terminal (`src/cli`), que lê o banco.

A execução do pipeline de ingestão (`run_pipeline()`) está desativada no `main.py` durante a migração para o novo banco e volta na fase 8 do [TODO](todo-idempotencia.md). O pipeline consulta exclusivamente a API configurada em `MOCK_API`.

## 7. Verificar resultados

O fluxo deve:

- carregar o JSON bruto
- normalizar strings numéricas, booleanas e data/hora
- validar registros e intervalos
- persistir os dados no banco
- executar consultas e estatísticas
- exibir o relatório final ou salvar os resultados

Confira os logs da execução:

```bash
# Linux/macOS
ls logs/
tail -n 20 logs/pipeline_*.log

# Windows (PowerShell)
Get-ChildItem logs
Get-Content (Get-ChildItem logs\pipeline_*.log | Sort-Object LastWriteTime | Select-Object -Last 1) -Tail 20
```

O arquivo `rejeitados_*.log` lista tudo o que não foi importado, uma linha por ocorrência, sem dados pessoais (formato na seção 6 de [analise-implementacao.md](analise-implementacao.md)).

## 8. Executar os testes

Os testes não precisam da API em execução nem do banco do Azure. Com o ambiente virtual ativado, a partir da pasta `Data-Science-Ia`:

```bash
python -m pytest tests

# somente segurança (LGPD) e logs
python -m pytest tests/unit/test_security.py tests/unit/test_logger.py
```

Sem configuração adicional, os testes unitários são executados e os de integração são ignorados (resultado esperado: `103 passed, 7 skipped`). Os testes usam chaves próprias definidas em `tests/conftest.py`, então não dependem da `CHAVE_CRIPTOGRAFIA` do `.env`. O guia completo (testes de integração em SQL Server de teste, cobertura, execução de testes específicos e problemas comuns) está na seção 4 de [plano-testes.md](plano-testes.md).

## Estrutura executada

A execução segue a seguinte ordem lógica:

```text
logs -> configuração -> segurança -> ingestão -> normalização e anonimização -> validação -> persistência -> análise -> relatório
```

## Dicas

- mantenha `.env` fora do controle de versão
- sempre atualize o `.env.example` quando novas variáveis forem adicionadas
- teste cada módulo separadamente antes de rodar o pipeline completo
