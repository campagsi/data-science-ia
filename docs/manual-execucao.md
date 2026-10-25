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
FONTE_DADOS="http://127.0.0.1:8000"
CHAVE_CRIPTOGRAFIA="chave Fernet compartilhada pelo time"
CHAVE_HASH="segredo compartilhado pelo time (opcional)"
```

| Variável | Obrigatória | Uso |
|---|---|---|
| `AZURE_SQL_CONNECTIONSTRING` | sim | Conexão com o banco |
| `FONTE_DADOS` | sim | URL da API de ingestão; também é gravada em `Leituras.fonte` (máximo de 100 caracteres). Substitui a antiga `MOCK_API`. |
| `CHAVE_CRIPTOGRAFIA` | sim | Criptografia reversível do e-mail do operador. A aplicação não inicia sem ela. |
| `CHAVE_HASH` | não | Segredo do hash de CPF e nome; vazio = SHA-256 puro |

A `CHAVE_CRIPTOGRAFIA` é gerada uma única vez e compartilhada com o time fora do Git:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use a mesma `CHAVE_CRIPTOGRAFIA` e a mesma `CHAVE_HASH` em todas as máquinas (ver [seguranca-lgpd.md](seguranca-lgpd.md)).

Os logs de cada execução ficam em `logs/` (fora do Git): `pipeline_AAAAMMDD_HHMMSS.log` com a execução e `rejeitados_AAAAMMDD_HHMMSS.log` com tudo o que não foi importado. Cada execução cria o seu par de arquivos, e as primeiras linhas de cada um (`[cabeçalho]`) dizem qual etapa o criou (ingestão, análise, consulta ou coleta), por quê e o que contém; numa análise ou consulta, o de rejeitados fica só com o cabeçalho, porque nada é importado. A variável de ambiente opcional `PASTA_LOGS` troca essa pasta; os testes a apontam para uma pasta temporária, para que `logs/` guarde só os logs de cargas reais.

Nao use `DB_HOST`, `DB_PORT`, `DB_USER` ou `DB_PASSWORD`: essas variaveis pertencem a uma configuracao PostgreSQL e nao sao lidas pelo codigo atual.

## 4. Criar banco e tabelas

O schema da Parte 2 (modelo 3FN) é mantido **somente** pelos scripts SQL da pasta `sql/`. A aplicação Python não cria nem altera tabelas.

| Script | Uso |
|---|---|
| [sql/ddl_banco_relacional.sql](../sql/ddl_banco_relacional.sql) | Estado **completo e atual** do schema: tabelas, chaves e índices. Usado para criar um banco do zero. **Começa com `DROP TABLE IF EXISTS`: apaga todas as tabelas e dados.** |
| [sql/migrations/](../sql/migrations/) | Alterações incrementais (`VNNN__descricao.sql`) para levar um banco **já existente** ao estado do DDL, sem perder dados. |
| [sql/dml_populacao.sql](../sql/dml_populacao.sql) | Carga inicial de estados e parâmetros (fase 3 do [TODO](todo-idempotencia.md); idempotente, com `MERGE`). |

### Banco novo (vazio)

Execute o DDL e depois o DML. As migrations não são necessárias, porque o DDL já contém todas elas; se forem executadas, não alteram nada, por serem idempotentes.

```bash
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/ddl_banco_relacional.sql
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/dml_populacao.sql
```

### Banco existente (com dados)

**Não execute o DDL.** Aplique apenas as migrations que ainda não foram aplicadas, em ordem de número:

```bash
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/migrations/V001__leituras_codigo_registro.sql
sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario> -P <senha> -f 65001 -i sql/migrations/V002__operadores_email_criptografado.sql
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

### Usuário só de leitura do agente analítico

O agente analítico ([agente/README.md](agente/README.md)) lê o banco com um usuário próprio, `agente_leitura`, que não grava nada e, da tabela `Operadores`, lê só o código do operador (políticas POL-01 e POL-02 de [agente/guardrails-e-owasp.md § 9](agente/guardrails-e-owasp.md#9-políticas-de-segurança-do-agente)). O script [sql/seguranca/agente_usuario_leitura.sql](../sql/seguranca/agente_usuario_leitura.sql) **não é uma migration**: ele muda permissões, não a estrutura, por isso fica fora de `sql/migrations/` e não altera o DDL. É idempotente.

1. Quem administra o banco cria o usuário uma vez, com uma senha forte que **não vai para o Git**:

   ```sql
   CREATE USER agente_leitura WITH PASSWORD = '<senha forte>';
   ```

2. Aplica as permissões:

   ```bash
   sqlcmd -S <servidor>.database.windows.net -d <banco> -U <usuario-admin> -P <senha> -f 65001 -i sql/seguranca/agente_usuario_leitura.sql
   ```

   O script dá `SELECT` só em `Estados`, `Municipios`, `Estacoes`, `Parametros`, `Leituras` e `Leitura_Itens`; em `Operadores`, dá `SELECT` só em `id_operador` e `codigo_operador` e nega nome, CPF, e-mail e município por coluna; e nega `INSERT`, `UPDATE`, `DELETE` e `ALTER` no schema `dbo`. Não use o papel `db_datareader`: ele daria leitura de `Operadores`.

3. No `.env`, `AGENTE_SQL_CONNECTIONSTRING` com `UID=agente_leitura` e a senha. A variável é obrigatória quando `AGENTE_LLM_FORNECEDOR` é `openai` ou `anthropic`, e o agente nunca usa a `AZURE_SQL_CONNECTIONSTRING` da ingestão.

O teste `tests/integration/test_agente_somente_leitura.py` aplica o script num banco descartável e confere que o usuário lê as tabelas das ferramentas, não grava, não altera a estrutura, lê de `Operadores` só o código e não lê as colunas com dados pessoais.

**Atualização de 23/10/2026:** o agente passou a informar o código do operador de cada estação. Num banco que já tinha o script aplicado, **rode o script de novo** (ele é idempotente): ele tira o `DENY` da tabela `Operadores` inteira e aplica as permissões por coluna. Sem isso, a `panorama_dados` falha por falta de permissão.

#### Banco local para testar o agente (`agente_local`)

Enquanto o `agente_leitura` não existe no Azure, os testes com o LLM real usam o banco `agente_local` no SQL Server Express (`localhost\SQLEXPRESS`), criado em 21/10/2026:

1. **Banco contido:** `contained database authentication` ligado na instância e `CREATE DATABASE agente_local CONTAINMENT = PARTIAL`. Um banco contido aceita usuário com senha **sem login no servidor**, como no Azure SQL;
2. **Estrutura e dados:** o DDL e as migrations do projeto, e as tabelas copiadas do banco local `Data Science` (9.806 leituras). O `Data Science` não é alterado;
3. **Usuário:** `CREATE USER agente_leitura WITH PASSWORD = '...'` e o script `sql/seguranca/agente_usuario_leitura.sql`.

O login com senha exige o SQL Express em **modo misto** (Windows e SQL). A configuração `LoginMode = 2` já foi gravada, mas só vale depois de reiniciar o serviço `MSSQL$SQLEXPRESS`, o que precisa de administrador (`services.msc` ou o reinício do computador). Até lá, o `.env` usa **temporariamente** a autenticação do Windows no `agente_local`, marcada com um comentário. Depois do reinício:

```sql
-- no banco agente_local, como administrador
ALTER USER agente_leitura WITH PASSWORD = '<senha forte, fora do Git>';
```

e, no `.env`, `AGENTE_SQL_CONNECTIONSTRING="Server=localhost\SQLEXPRESS;Database=agente_local;UID=agente_leitura;PWD=<senha>;Encrypt=no"`.

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

### API para o Power BI (camada Gold)

O mesmo servidor expõe, em `/api/v1/bi`, as tabelas Parquet da camada Gold (`data_lake/gold/`, ou a pasta definida em `DIRETORIO_GOLD`). A API só lê os arquivos: a Gold continua sendo gerada pelo pipeline. Cada tabela fica em memória e é relida automaticamente quando o arquivo muda no disco. Se a Gold ainda não existir, as rotas respondem `503`.

| Rota | Conteúdo |
|---|---|
| `GET /api/v1/bi/estacoes` | Dimensão estação (`estacao_sk`, código, nome, município, latitude, longitude). |
| `GET /api/v1/bi/parametros` | Dimensão parâmetro (`parametro_sk`, código, campo, unidade). |
| `GET /api/v1/bi/tempo` | Dimensão tempo (`tempo_sk` no formato AAAAMMDD, data, ano, mês, dia, trimestre, dia da semana, dia útil). |
| `GET /api/v1/bi/medicoes` | Fato medições, paginada, em ordem cronológica: `{pagina, por_pagina, total, total_paginas, tem_proxima, dados}`. |
| `GET /api/v1/bi/medicoes/diarias` | Fato agregada por dia, estação e parâmetro: quantidade, média, mínimo, máximo e outliers. |

Filtros de `/medicoes` e `/medicoes/diarias` (todos opcionais): `inicio` e `fim` (`AAAA-MM-DD`, inclusivos), `estacao_sk`, `parametro_sk` e `apenas_outliers=true`. Em `/medicoes`, `pagina` (a partir de 1) e `por_pagina` (padrão 5000, máximo 50000). Parâmetro inválido ou `inicio` maior que `fim` responde `422`.

**Chave de acesso:** com `CHAVE_API_BI` preenchida no `.env`, toda chamada a `/api/v1/bi` precisa do header `X-API-Key` com o mesmo valor; sem ele, a resposta é `401`. Com a variável vazia, as rotas ficam abertas (uso local).

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/bi/medicoes?inicio=2026-06-01&fim=2026-06-30&por_pagina=10" -Headers @{ "X-API-Key" = "<chave>" }
```

**No Power BI:** em *Obter dados → Consulta em branco → Editor avançado*, as dimensões e o agregado diário são uma chamada só (troque a rota). Use autenticação *Anônima* e passe a chave pelo header:

```powerquery
let
    Base = "http://127.0.0.1:8000",
    Fonte = Json.Document(Web.Contents(Base, [RelativePath = "api/v1/bi/estacoes", Headers = [#"X-API-Key" = "<chave>"]])),
    Tabela = Table.FromRecords(Fonte)
in
    Tabela
```

A fato de medições é paginada; esta consulta percorre todas as páginas:

```powerquery
let
    Base = "http://127.0.0.1:8000",
    Pagina = (n as number) => Json.Document(Web.Contents(Base, [
        RelativePath = "api/v1/bi/medicoes",
        Query = [pagina = Number.ToText(n), por_pagina = "50000"],
        Headers = [#"X-API-Key" = "<chave>"]
    ])),
    Primeira = Pagina(1),
    Paginas = List.Generate(
        () => [n = 1, r = Primeira],
        each [n] <= Primeira[total_paginas],
        each [n = [n] + 1, r = Pagina([n] + 1)],
        each [r][dados]
    ),
    Tabela = Table.FromRecords(List.Combine(Paginas))
in
    Tabela
```

No modelo, relacione a fato às dimensões por `estacao_sk`, `parametro_sk` e `tempo_sk`. `RelativePath` e `Query` mantêm a URL base fixa, o que permite agendar a atualização no serviço do Power BI; para isso, a API precisa estar acessível pela rede ou por um gateway.

**Teste pelo dashboard:** a página `http://127.0.0.1:5000/api-bi` (link "Testar API do BI" no menu lateral do dashboard, seção 6) mostra, ao abrir, se a API está no ar, se a camada Gold tem dados (com a orientação do que fazer quando estiver vazia), quantas rotas respondem e o total de medições, além do status, tempo e total de linhas de cada rota; com a Gold disponível, já exibe uma amostra das medições. Também executa uma consulta com os filtros acima, mostrando a URL chamada, o total, a paginação e uma amostra das primeiras 20 linhas. O Flask chama a API do lado do servidor no endereço de `FONTE_DADOS`, enviando `CHAVE_API_BI` quando configurada; a chave não é enviada ao navegador.

## 6. Executar a aplicação

### Interface gráfica (dashboard web)

O dashboard também tem a página **Agente analítico** (`http://127.0.0.1:5000/agente`, link "Abrir o agente" no menu). Ela usa as mesmas variáveis do agente da seção [Agente analítico](#agente-analítico-perguntas-em-linguagem-natural), limita as perguntas por IP (`AGENTE_LIMITE_WEB`) e, com `AGENTE_CHAVE_WEB` preenchida, exige o header `X-API-Key`, que a página pede num campo. **Preencha a chave antes de expor o servidor além do `127.0.0.1`**: cada pergunta custa tokens.

Na raiz de `Data-Science-Ia`, com o ambiente virtual ativado e as variáveis de ambiente configuradas, inicie o servidor Flask:

```bash
python -m flask --app src.ui.app run --host 127.0.0.1 --port 5000
```

Abra <http://127.0.0.1:5000> no navegador. O dashboard permite:

- filtrar as medições por estado, cidade, estação, parâmetro e período (com atalhos de 7, 30 e 90 dias até a última medição). Os filtros de local são encadeados: o estado limita as cidades, a cidade limita as estações, e escolher uma estação preenche a cidade e o estado dela. O cabeçalho da página mostra o filtro aplicado: com uma estação, o título passa a "Leituras da estação", com o código, o nome, a cidade e o estado dela; sem estação, mostra "Todas as estações" e, se houver, a cidade e o estado filtrados. Se a cidade e o estado das estações não puderem ser lidos, a lateral mostra só o filtro de estação (WARNING no log);
- ver a série temporal por **semana, mês, ano ou tudo**, navegando entre períodos (botões ‹ › ou setas do teclado), com média, faixa mín.–máx., anomalias marcadas, comparação com o período anterior e o perfil médio por hora do dia (média de cada hora no período exibido, com o período e o número de dias no título, por exemplo "Perfil médio por hora · 19 a 25/10 (7 dias)"). Clicar em um ponto abre o mês ou a semana correspondente; na visão Semana, o clique compara o dia com a média: as barras continuam com a média da semana e o dia aparece como uma linha por cima (título "Seg., 20/10 × média de 19 a 25/10"), até clicar em "Voltar à média". A "escala ajustada" impede que picos isolados achatem a série; "Escala completa" mostra o eixo inteiro;
- navegar pelas tabelas de resumo estatístico, alertas e medições **paginadas** (10, 25, 50 ou 100 linhas por página);
- exportar **todo** o recorte filtrado em CSV (separador `;`, decimal com vírgula), não só a página exibida;
- alternar entre tema claro e escuro;
- testar a API do Power BI em **Testar API do BI** (`/api-bi`): status da API e da camada Gold, verificação de todas as rotas e consulta com filtros e amostra da resposta (detalhes na seção 5). Requer a API da seção 5 rodando.

As medições ficam em memória por até 2 minutos (ou até a próxima ingestão pelo dashboard), então a troca de página e de período não repete a consulta ao banco. O gráfico consome `GET /api/serie?codigo=<parâmetro>` com os mesmos filtros da página, que devolve baldes horários já agregados.

Para executar a ingestão pelo dashboard, mantenha também a API de ingestão da seção 5 ativa em outro terminal. O dashboard consulta os dados existentes no Azure SQL; portanto, configure `AZURE_SQL_CONNECTIONSTRING` e prepare o banco conforme a seção 4. A ingestão também precisa de `FONTE_DADOS` e `CHAVE_CRIPTOGRAFIA` válidos.

Para encerrar o servidor web, pressione `Ctrl+C` no terminal em que o Flask está rodando.

### Interface de consulta no terminal

```bash
python main.py
```

Ao iniciar, `iniciar_aplicacao()` executa, nesta ordem:

1. `configurar_logs(etapa)`: cria `logs/pipeline_AAAAMMDD_HHMMSS.log` e `logs/rejeitados_AAAAMMDD_HHMMSS.log`, cada um com o cabeçalho da etapa (`ingestao`, `analise` ou `consulta`, conforme o argumento);
2. `load_config()`: exige `AZURE_SQL_CONNECTIONSTRING`, `FONTE_DADOS` e `CHAVE_CRIPTOGRAFIA`;
3. `configurar_seguranca()`: valida a chave Fernet e a chave de hash.

Se qualquer passo falhar, a aplicação registra a causa com nível `CRITICAL` e termina com código `1`, sem mostrar senhas nem chaves. Esse comando abre a interface de consulta no terminal (`src/cli`), que lê o banco. Para iniciar a interface gráfica web, use o comando Flask descrito acima.

### Ingestão (carga no banco)

Com a API da seção 5 em execução:

```bash
python main.py --ingestao
```

A ingestão:

1. coleta o lote;
2. parte A, data lake: grava na Bronze o que atende o contrato; na Silver, remove repetidos, normaliza, anonimiza, cadastra parâmetros novos e valida; gera a Gold (arquivos em `data_lake/`);
3. parte B, banco: registra as rejeições no log e grava só os registros válidos, numa única transação.

A carga é **idempotente**: reexecutar o mesmo período substitui as leituras de cada estação + dia, sem duplicar. Ao final, o log registra uma linha `Resumo da ingestão` com recebidos, válidos, inválidos, itens descartados, leituras gravadas e substituídas e itens gravados.

O pipeline consulta exclusivamente a API configurada em `FONTE_DADOS`.

### Análise estatística

Depois de uma carga, sem precisar da API:

```bash
python main.py --analise                                      # todas as estações, todo o período
python main.py --analise --estacao EST-RJ-001                 # uma estação
python main.py --analise --inicio 2026-06-01 --fim 2026-06-30 # intervalo (só --inicio = um dia)
```

O relatório (métricas por estação e parâmetro) vai para o log da execução em `INFO`, e cada medição anômala vai numa linha `WARNING` com o indicador de alerta (`IQR`, `ZSCORE` ou `IQR+ZSCORE`). Estação inexistente encerra com `CRITICAL` e código `1`. As mesmas métricas podem ser conferidas direto no banco com [sql/queries_analiticas.sql](../sql/queries_analiticas.sql). Regras em [analise-estatistica.md](analise-estatistica.md).

### Agente analítico (perguntas em linguagem natural)

O agente responde perguntas como "qual o pH médio em junho?" com um LLM (Claude Haiku 5.5, decisão DA9) que escolhe ferramentas Python só de leitura. Documentação completa em [agente/README.md](agente/README.md).

**Antes do primeiro uso:**

1. Chave do LLM, com um **limite de gasto mensal** configurado no painel do fornecedor: OpenAI (`OPENAI_API_KEY`, modelo `gpt-4.1-mini`, decisão DA11) ou Anthropic (`ANTHROPIC_API_KEY`, `claude-haiku-5-5`). Na rodada de 21/10/2026, cada pergunta usou em média ~11 mil tokens de entrada e ~150 de saída no `gpt-4.1-mini`.
2. Usuário só de leitura `agente_leitura` criado no banco (seção 4, [Usuário só de leitura do agente analítico](#usuário-só-de-leitura-do-agente-analítico)).
3. No `.env`: `AGENTE_LLM_FORNECEDOR=openai`, `AGENTE_LLM_MODELO=gpt-4.1-mini`, `OPENAI_API_KEY` e `AGENTE_SQL_CONNECTIONSTRING` (ou `anthropic`, `claude-haiku-5-5` e `ANTHROPIC_API_KEY`). As variáveis opcionais e os padrões estão no `.env.example` e em [agente/arquitetura.md § 9](agente/arquitetura.md#9-configuração).

**Uso:**

```bash
python main.py --indexar                                       # (re)indexa a documentação (RAG); idempotente
python main.py --indexar-dias                                  # (re)indexa os resumos diários (ferramenta dias_semelhantes)
python main.py --treinar-previsao                              # treina e avalia o modelo de previsão (ferramenta prever)
python main.py --laudo --inicio 2026-06-01 --fim 2026-06-30    # laudos das anomalias do período (LLM)
python main.py --pergunta "Qual o pH médio em junho de 2026?"   # uma pergunta, resposta no terminal
python main.py --agente                                         # chat; "sair" ou Ctrl+C encerram
```

**Base do agente pela interface:** a página `/agente` tem, na barra lateral, o painel **Base do agente**. Ele mostra a situação do índice da documentação, do índice dos dias e do modelo de previsão (Em dia, Desatualizado, Ausente ou Indisponível). Cada linha tem o botão **Atualizar** (ou **Treinar**, para a previsão), e há também o **Atualizar tudo**. Os botões **só habilitam quando algo está desatualizado ou ausente**: a documentação mudou desde a última indexação, ou os dados do banco mudaram desde a última indexação dos dias ou o último treino. Reingerir os mesmos dados não deixa nada desatualizado. A atualização roda em segundo plano, uma por vez, e o painel mostra o andamento (o treino da previsão leva cerca de 1 minuto). Ao terminar, a próxima pergunta já usa o índice e o modelo novos, sem reiniciar o servidor. Os dias e a previsão precisam da `AGENTE_SQL_CONNECTIONSTRING`; sem ela, aparecem como **Indisponível**. Os comandos abaixo fazem a mesma coisa pelo terminal e gravam o mesmo registro de atualização.

**Fluxo depois de uma ingestão:** rode a ingestão (botão "Executar ingestão" no dashboard ou `python main.py --ingestao`), abra `/agente` e clique em **Atualizar tudo** se o painel acusar algo desatualizado.

**Índice da documentação:** para o agente explicar regras e decisões citando os documentos (ferramenta `buscar_documentacao`), rode `python main.py --indexar` uma vez e **de novo sempre que a documentação mudar**. A primeira vez baixa o modelo de embeddings (~0,24 GB) para `data/agente/modelos/` e leva cerca de 30 s. As seguintes só vetorizam os trechos que mudaram, e sem mudança registram `inseridos=0 removidos=0`. Sem índice, o agente responde números normalmente, só sem citar a documentação, e registra um aviso no log. O banco vetorial padrão é em memória (`data/agente/indice_docs.*`). Com `AGENTE_VETORES=chroma` no `.env`, o índice vai para o ChromaDB (`data/agente/chroma`); ao trocar, rode `--indexar` de novo.

A resposta mostra as **fontes** (ferramentas executadas, com os argumentos) e os tokens consumidos. O log da execução (etapa `agente`, em `logs/`) tem uma linha por pergunta, com CPF, e-mail e telefone mascarados, uma por ferramenta e uma por resposta. Também registra uma linha `WARNING guardrail=POL-xx` sempre que uma política de segurança age. Variável ausente ou inválida encerra com `CRITICAL` e código `1`, sem mostrar valores.

**Estudo sem custo e sem chave:** `python -m src.agente.exemplos.e05_tool_use_passo_a_passo`, `e06_agente_offline` e `e11_guardrails` usam o LLM roteirizado e dados de exemplo em memória.

**Índice dos dias:** `python main.py --indexar-dias` lê as medições com `AGENTE_SQL_CONNECTIONSTRING` (usuário só de leitura), gera um resumo por estação e dia e o indexa em `data/agente/dias/`. Rode depois de cada ingestão que mudar os dados (ou use o painel da página `/agente`): só os dias cujo resumo mudou são vetorizados de novo. Sem esse índice, o agente funciona sem a ferramenta `dias_semelhantes` ("que dias foram parecidos com 15/06?").

**Modelo de previsão:** `python main.py --treinar-previsao` lê as medições com `AGENTE_SQL_CONNECTIONSTRING` e avalia temperatura do ar, umidade, temperatura da água e radiação em 1, 3, 6, 12 e 24 h, com validação temporal contra dois baselines (leva cerca de 1 minuto). Grava o modelo e o `metadados.json` em `data/agente/modelos/previsao/` e o relatório em `relatorios/previsao_<data>.md`. Só os horizontes em que o modelo vence os dois baselines ficam disponíveis para a ferramenta `prever`. **Treine de novo depois de atualizar o scikit-learn**: o agente recusa um modelo de outra versão (POL-12) e segue sem a `prever`, com um aviso no log.

**Laudos de anomalias:** `python main.py --laudo --inicio AAAA-MM-DD [--fim AAAA-MM-DD] [--estacao CODIGO] [--limite N]` pede ao LLM a causa provável de cada anomalia (falha de sensor, evento real ou inconclusivo) e a severidade, com o contexto vizinho. Exige as mesmas variáveis do agente (chave da Anthropic e `AGENTE_SQL_CONNECTIONSTRING`). Por padrão, faz no máximo 50 laudos, das anomalias mais extremas (`--limite 0` = todas; cerca de US$ 0,002 por laudo no Haiku). Grava `relatorios/laudos_<inicio>_<fim>.csv` e `.md`, marcados como gerados por IA. Resposta fora do formato é descartada e aparece no log (`guardrail=POL-06`) e na lista de descartados do Markdown. O laudo não altera o banco nem o indicador de alerta.

**Avaliação do agente (golden set):** mede a qualidade com 53 perguntas de referência ([agente/avaliacao.md](agente/avaliacao.md)). O relatório vai para `relatorios/` (fora do Git), e o log, para a etapa `avaliacao`.

```bash
python -m src.agente.avaliacao --so-recuperacao   # grátis: só a busca na documentação (precisa do índice)
python -m src.agente.avaliacao                    # completa: ~53 perguntas ao LLM (~US$ 0,50 a 1,00 no Haiku)
python -m src.agente.avaliacao --lote             # só a seleção de ferramentas, pela Batch API (metade do preço)
```

### Interface de consulta no terminal

`python main.py` sem argumentos abre a CLI: escolha o município, a estação e o período (datas em `dd/mm/aaaa`). A tela mostra as métricas de todos os parâmetros e as anomalias; a opção `0` salva `estatisticas.csv` e `anomalias.csv` em `relatorios/` (fora do Git).

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

Sem configuração adicional, os testes unitários são executados e os de integração são ignorados (os totais atuais, e as falhas que já existiam, estão na seção 4 de [plano-testes.md](plano-testes.md)). Os testes usam chaves próprias definidas em `tests/conftest.py`, então não dependem da `CHAVE_CRIPTOGRAFIA` do `.env`. O guia completo (testes de integração em SQL Server de teste, cobertura, execução de testes específicos e problemas comuns) está na seção 4 de [plano-testes.md](plano-testes.md).

## Estrutura executada

A execução segue a seguinte ordem lógica:

```text
logs -> configuração -> segurança -> ingestão -> normalização e anonimização -> validação -> persistência -> análise -> relatório
```

## Dicas

- mantenha `.env` fora do controle de versão
- sempre atualize o `.env.example` quando novas variáveis forem adicionadas
- teste cada módulo separadamente antes de rodar o pipeline completo
