# TODO — Idempotência, campos nulos e Analytics

Fases para que a ingestão grave no novo banco 3FN sem duplicar dados, trate campos nulos e registre em log **tudo o que não foi importado**.

- O que muda e por quê: [analise-implementacao.md](analise-implementacao.md)
- Schema de referência: [sql/ddl_banco_relacional.sql](../sql/ddl_banco_relacional.sql)
- Anonimização e log centralizados: [seguranca-lgpd.md](seguranca-lgpd.md) (`src/security.py` e `src/logger.py`)
- Exemplos de referência: `avanade-ds-ia/modulo-1/projeto-pratico/src/security.py`, `.../src/transform.py` e `avanade-ds-ia/modulo-2/ED_PYTHON/01_ingestao_api.py`
- Ao concluir cada fase, registrar o relatório na seção 11 de [analise-implementacao.md](analise-implementacao.md).

---

## Fase 0 — Validar o banco contra o DDL

- [x] Conectar no banco `impacta` (somente leitura)
- [x] Conferir tabelas, colunas, tipos e nulabilidade
- [x] Conferir PK, FK, UNIQUE, CHECK e índices
- [x] Resultado: **idêntico ao DDL**, tabelas vazias (05/10/2026)
- [ ] Rodar de novo sempre que o DDL mudar (ex.: após a decisão D1), usando a consulta abaixo

```sql
-- Colunas (comparar com o DDL)
SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH,
       c.NUMERIC_PRECISION, c.NUMERIC_SCALE, c.IS_NULLABLE, c.COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME IN ('Estados','Municipios','Estacoes','Operadores','Parametros','Leituras','Leitura_Itens')
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION;

-- Constraints
SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE,
       STRING_AGG(k.COLUMN_NAME, ',') WITHIN GROUP (ORDER BY k.ORDINAL_POSITION) AS colunas
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
GROUP BY tc.TABLE_NAME, tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE
ORDER BY tc.TABLE_NAME;

-- Índices
SELECT OBJECT_NAME(i.object_id) AS tabela, i.name, i.is_unique,
       STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal) AS colunas
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1 AND i.name LIKE 'IX[_]%'
GROUP BY i.object_id, i.name, i.is_unique;
```

---

## Fase 1 — Decisões (D1 e D7 bloqueiam a fase 8; as demais têm recomendação aplicável)

Detalhes e recomendações na seção 10 da análise.

- [x] **D1** Chave natural de `Leituras`: `codigo_registro` + `UNIQUE` (aprovada em 05/10/2026)
- [x] **D2** Leitura sem operador: rejeitar e logar (06/10/2026)
- [x] **D3** `Leituras.fonte` = `FONTE_DADOS` (URL da API), variável única que substitui `MOCK_API` (05/10/2026)
- [x] **D4** Mudança do `ValidationService` para rejeição por registro e por item (aprovada em 05/10/2026)
- [x] **D5** Campos do payload sem coluna no DDL: descartar (06/10/2026)
- [x] **D6** Faixas mínima e máxima dos parâmetros: proposta da fase 3 aprovada (06/10/2026)
- [x] **D7** E-mail criptografado: `email_hash` trocado por `email_criptografado VARCHAR(255) NULL` (aprovada em 05/10/2026)
- [x] **D8** Hash com pepper: configurável (`PEPPER_HASH` preenchido = HMAC-SHA256; vazio = SHA-256 puro), fase 2
- [x] D1 = (a) e D7 = (a): migrations `V001` e `V002` criadas em `sql/migrations/`, DDL atualizado, aplicadas no banco `impacta` (duas vezes, para provar a idempotência) e Fase 0 repetida. Ações originais:
- [x] Criar as migrations abaixo, atualizar o `ddl_banco_relacional.sql` para o estado final, aplicar as migrations no banco e repetir a Fase 0 (regras na seção 4 de [manual-execucao.md](manual-execucao.md))

```sql
-- sql/migrations/V001__leituras_codigo_registro.sql  (D1 = a; somente se aprovado)
-- NOT NULL direto só funciona porque Leituras está vazia.
IF COL_LENGTH('dbo.Leituras', 'codigo_registro') IS NULL
    ALTER TABLE dbo.Leituras ADD codigo_registro VARCHAR(50) NOT NULL;
GO
IF OBJECT_ID('dbo.UQ_Leituras_CodigoRegistro', 'UQ') IS NULL
    ALTER TABLE dbo.Leituras ADD CONSTRAINT UQ_Leituras_CodigoRegistro UNIQUE (codigo_registro);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Leituras_Estacao_DataHora')
    CREATE INDEX IX_Leituras_Estacao_DataHora ON dbo.Leituras (estacao_id, data_hora);
GO

-- sql/migrations/V002__operadores_email_criptografado.sql  (D7 = a; somente se aprovado)
IF COL_LENGTH('dbo.Operadores', 'email_hash') IS NOT NULL
    ALTER TABLE dbo.Operadores DROP COLUMN email_hash;
GO
IF COL_LENGTH('dbo.Operadores', 'email_criptografado') IS NULL
    ALTER TABLE dbo.Operadores ADD email_criptografado VARCHAR(255) NULL;
GO
```

---

## Fase 2 — Módulos centrais de log e segurança

Desenho em [seguranca-lgpd.md](seguranca-lgpd.md) e na seção 6 da análise.

**`src/logger.py`** (padrão `transform.py` / `01_ingestao_api.py`)

- [x] `configurar_logs()`, chamado uma vez no `main.py` (em `iniciar_aplicacao()`): `logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s', handlers=[...])`
  - `StreamHandler()` (console) + `FileHandler('logs/pipeline_AAAAMMDD_HHMMSS.log')`
- [x] Logger `DataScienceIA_Logger` (execução) e logger `DataScienceIA_Rejeitados` com `FileHandler('logs/rejeitados_AAAAMMDD_HHMMSS.log')`, só em arquivo (não polui o console)
- [x] `registrar_rejeicao(etapa, nivel, campo, motivo, registro=None, valor=None, severidade=WARNING)`, que omite o valor de campos pessoais
- [x] Níveis: INFO para progresso, WARNING para descarte ou tratamento, ERROR para falha de etapa, CRITICAL para falha de conexão
- [x] Nenhum outro módulo chama `basicConfig` ou `print`; `print` removido de `main.py` e `importar_dados.py` (a CLI `rich` continua com `console.print`, que é interface, não log)
- [x] `registrar_resumo(**contagens)` e `contar_rejeicoes()` disponíveis
- [x] Chamar o resumo com as contagens reais → feito na fase 8 (`run_pipeline()` → `registrar_resumo()`; testado em `integration/test_pipeline_e2e.py`)

**`src/security.py`** (padrão `security.py`)

- [x] `anonimizar_cpf` (ignora pontuação), `anonimizar_nome` (ignora espaços extras e maiúsculas): 64 caracteres hexadecimais, `None` para vazio
- [x] Com `PEPPER_HASH` preenchido usa HMAC-SHA256; vazio usa SHA-256 puro (atende as duas opções da D8)
- [x] `criptografar_email`, `descriptografar_email`: Fernet, `None` para vazio; erro de chave não expõe o token
- [x] Chave em `CHAVE_CRIPTOGRAFIA` no `.env`, lida pelo `src/config.py` e entregue por `configurar_seguranca()` (nunca fixa no código, ao contrário do exemplo); a aplicação não inicia sem ela ou com chave inválida
- [x] `cryptography` (e `rich`, usado pela CLI e que faltava) no `requirements.txt`
- [x] `CHAVE_CRIPTOGRAFIA` e `PEPPER_HASH` no `.env.example` (só os nomes); `MOCK_API` renomeada para `FONTE_DADOS`
- [ ] **Time:** gerar **uma** `CHAVE_CRIPTOGRAFIA` e **um** `PEPPER_HASH` e compartilhar com todos fora do Git (chaves diferentes geram hashes diferentes e e-mails ilegíveis entre máquinas)

**Git**

- [x] `.gitignore`: `logs/` e os arquivos de dados de `data_lake/` (mantendo os `.gitkeep`)

**Aceite:**

- [x] Uma execução gera os dois arquivos de log no formato definido (testado)
- [x] Valores de campos pessoais nunca entram no log de rejeitados (testado)
- [x] Leituras importadas + rejeitadas = total recebido (testado na integração, fase 9)
- [x] Busca por CPF, nome ou e-mail em `logs/` após uma carga real: nenhum encontrado (06/10/2026)

---

## Fase 3 — Schema fora do pipeline e carga inicial (DML)

- [x] Remover `criar_tabelas()` do `run_pipeline` em [main.py](../main.py)
- [x] Remover `src/database/criar_tabelas.py` e ajustar os imports e testes que o usavam (`test_main.py`, `tests/integration/conftest.py`)
- [x] Criar `sql/migrations/` e a regra "DDL sempre no estado final + migration idempotente por mudança" (seção 4 de [manual-execucao.md](manual-execucao.md))
- [x] Corrigir a ordem dos `DROP` no DDL (filhas antes das mães), para o script poder ser reexecutado
- [x] Testes de integração passam a montar o banco com o DDL + migrations
- [x] Escrever [sql/dml_populacao.sql](../sql/dml_populacao.sql) **idempotente** (`MERGE` pela chave natural, que insere o que falta e atualiza o que mudou):
  - [x] 27 estados (`sigla`, `nome`)
  - [x] 11 parâmetros conhecidos com faixas (D6, **proposta aprovada em 06/10/2026**):

| codigo_parametro | nome | unidade | mín. | máx. | origem da faixa |
|---|---|---|---|---|---|
| TIP-TAG | Temperatura da água | °C | 0 | 45 | proposta |
| TIP-PH | pH | pH | 0 | 14 | enunciado / código atual |
| TIP-TMP | Temperatura do ar | °C | -40 | 60 | proposta |
| TIP-UMI | Umidade relativa do ar | % | 0 | 100 | código atual |
| TIP-PRE | Pressão atmosférica | hPa | 870 | 1085 | proposta (recordes mundiais) |
| TIP-CHU | Precipitação | mm | 0 | NULL | código atual (não negativo) |
| TIP-VEN | Velocidade do vento | km/h | 0 | 200 | proposta |
| TIP-RAD | Radiação solar | W/m² | 0 | 1500 | proposta |
| TIP-OXI | Oxigênio dissolvido | mg/L | 0 | 20 | proposta |
| TIP-CON | Condutividade elétrica a 25 °C | µS/cm | 0 | NULL | código atual (não negativo) |
| TIP-TUR | Turbidez | NTU | 0 | NULL | código atual (não negativo) |

- [x] Executar o DML duas vezes e conferir que as contagens não mudam (validado no banco `impacta` dentro de uma transação com rollback: 27/11 nas duas execuções, 0/0 após o rollback)
- [x] **Aplicar o DML no banco `impacta`** (05/10/2026: `Estados` = 27, `Parametros` = 11; demais tabelas vazias)
- [x] Ajustar [manual-execucao.md](manual-execucao.md): banco novo = DDL → DML; banco existente = migrations
- [x] Testes de integração aplicam o `dml_populacao.sql` na criação do banco e a cada teste
- [x] `tests/unit/test_sql_scripts.py`: DML coerente com o dataset (estados, códigos e unidades dos parâmetros) e ordem dos `DROP` do DDL

**Aceite:** o pipeline roda sem criar nem alterar tabelas; `Estados` = 27 e `Parametros` = 11 após o DML.

---

## Fase 4 — Normalização e anonimização do payload novo

- [x] Campos do payload novo (`registro_codigo`, `data_hora_ciclo`, `municipio`, `operador_cpf`, `operador_nome_completo`, `operador_email` etc.); formato de saída na seção 3 da análise
- [x] Converter `data_hora_ciclo` (e `data_hora_leitura_*`) para `datetime`
- [x] Separar cada registro em **cabeçalho** + **lista de itens** (`campo`, `codigo_parametro`, `unidade_medida`, `valor`, `data_hora_leitura`)
- [x] Descobrir os parâmetros pelos campos `*_tipo_codigo`, sem lista fixa no código (`NormalizationService.descobrir_parametros`)
- [x] Resolver os nomes de unidade fora do padrão (`oxigenio_dissolvido_medida`, `velocidade_unidade_medida`)
- [x] Texto vazio (`""`, `"   "`) → `None`; `municipio` nulo usa `cidade_nome`
- [x] Valor não numérico numa medição → item rejeitado e logado, **sem derrubar o lote**; data/hora ou coordenada inválida → só aquela leitura rejeitada
- [x] Ordenar os registros por `data_hora_ciclo` (sem data ao final)
- [x] Logo após a limpeza, aplicar `src/security.py`: gerar `cpf_hash`, `nome_hash` e `email_criptografado`
- [x] **Minimização** (passo 4 do `transform.py`): os campos pessoais originais não são copiados para o registro normalizado
- [x] Campos sem coluna no banco (D5) listados uma vez por lote em INFO, sem valores

**Aceite:**

- [x] Os 9.888 registros normalizados sem exceção e sem nenhuma rejeição (testado)
- [x] 11 parâmetros descobertos (testado)
- [x] Nenhum registro normalizado contém os três campos pessoais originais (testado)

> Entre as fases 4 e 6, a `run_pipeline()` não funciona de ponta a ponta: o `ValidationService` ainda espera o formato antigo. Ela não é chamada pelo `main.py` neste período.

---

## Fase 5 — Campos nulos (completude)

Regras por nível:

| Nível | Campo nulo | Ação | Log |
|---|---|---|---|
| Leitura | `registro_codigo`, `data_hora_ciclo` | Rejeitar a leitura | WARNING `etapa=completude nivel=leitura` |
| Leitura | qualquer `estacao_*` obrigatório (código, nome, latitude, longitude) | Rejeitar a leitura | idem |
| Leitura | `operador_codigo`, `cpf_hash`, `nome_hash`, `email_criptografado` (já anonimizados na fase 4; `None` = original vazio) | Rejeitar a leitura (D2) | idem; o log cita só o nome do campo |
| Leitura | `cidade_estado`, `municipio` e `cidade_nome` | Rejeitar a leitura | idem |
| Item | `<param>` nulo | Não gravar o item; a leitura segue | WARNING `etapa=completude nivel=item` |
| Leitura | todos os itens nulos ou rejeitados | Rejeitar a leitura (sem cabeçalho órfão) | WARNING `motivo="leitura sem medições válidas"` |
| Parâmetro | unidade de medida ausente | Não cadastrar o parâmetro; itens dele rejeitados | ERROR `etapa=parametro` |

**Resultado da verificação (requisito do time):** contrato completo na seção 4 de [analise-implementacao.md](analise-implementacao.md).

- [x] A verificação dos campos roda **antes de gravar** em qualquer tabela ou no Data Lake e **não grava nem loga**: só devolve o resultado
- [x] `validate_data()` devolve uma lista (array) com **um resultado por registro**, contendo:
  - `valido` (bool): se o registro pode ou não ser ingerido
  - `campos_nulos` (lista): **todos** os campos que faltaram ou vieram nulos
  - `itens_invalidos` (lista): medições descartadas (`campo`, `motivo`, `valor`), sem invalidar o registro
  - `motivos` (lista): por que `valido=False`
  - `registro`: o registro normalizado só com os itens válidos
- [x] Uma função de `src/logger.py` (`registrar_resultados_validacao`) grava o log de rejeitados **a partir dos resultados**: uma linha por registro inválido (com todos os `campos_nulos`, ex.: `campo=estacao_codigo,operador_codigo`) e uma por item inválido
- [x] `ValidationService.registros_validos(resultados)` entrega só os registros com `valido=True`, usado pela `run_pipeline()` antes da persistência
- [x] ~~Destino no Data Lake pelos resultados~~ → Data Lake em outra frente do projeto; o critério é o `valido` do resultado
- [x] Implementar as regras da tabela acima preenchendo esse resultado (a regra de parâmetro sem unidade fica na fase 7)

**Aceite com o dataset atual** (testado em `tests/test_quality_stat.py`):

- [x] 82 leituras rejeitadas por estação ou operador nulo (50 + 32)
- [x] As 2.681 medições nulas dos registros válidos aparecem no log de rejeitados com `nivel=item`

---

## Fase 6 — Acurácia e validação por registro

- [x] `validate_data` deixa de abortar o lote: as regras de acurácia e unicidade preenchem o mesmo resultado por registro da fase 5 (`valido`, `campos_nulos`, `itens_invalidos`, `motivos`)
- [x] Faixas recebidas no construtor (`ValidationService(faixas=..., siglas_estados=...)`), sem dicionário fixo no código (`NULL` = sem limite; parâmetro sem faixa = sem conferência)
- [x] Ler as faixas de `Parametros` e as siglas de `Estados` no banco e passá-las ao `ValidationService` (feito junto com a fase 7)
- [x] Valor fora da faixa → rejeitar **só o item** (`etapa=acuracia`, com o valor e a faixa)
- [x] Latitude e longitude fora da faixa → rejeitar a leitura (o CHECK do banco também barra)
- [x] `cidade_estado` inexistente em `Estados` → rejeitar a leitura (`etapa=referencia`); sigla fora do formato → `etapa=validade`
- [x] Mesmo `operador_codigo` ou `estacao_codigo` com dados cadastrais diferentes no lote → rejeitar a leitura (`etapa=unicidade`)
- [x] Mesmo `registro_codigo` repetido no lote (retransmissão) → manter o primeiro (`etapa=unicidade`)

**Aceite com o dataset atual** (testado em `tests/test_quality_stat.py`, com as faixas do DML):

- [x] 603 medições fora da faixa descartadas só como item, entre elas pH fora de 0–14 (72; a 73ª está num registro já rejeitado por completude) e umidade fora de 0–100 (69)
- [x] As leituras dessas medições continuam válidas com os demais itens
- [x] Nenhum item gravável fica fora da faixa
- [x] Log de rejeitados com 3.366 linhas (82 leituras + 2.681 nulas + 603 fora da faixa), sem CPF nem e-mail

---

## Fase 7 — Cadastro automático de parâmetros

- [x] Antes de validar, comparar os parâmetros descobertos (fase 4) com `Parametros` (`ParametroService.sincronizar`)
- [x] Inserir os que não existem (`codigo_parametro`, `nome` legível a partir do campo, `unidade_medida`, faixas `NULL`), sem duplicar (`INSERT ... WHERE NOT EXISTS`)
- [x] Logar INFO `Novo parâmetro cadastrado: <codigo> (<nome>, <unidade>), sem faixa de valores.`
- [x] Parâmetro novo sem unidade → ERROR (`etapa=parametro`), não cadastrado
- [x] Conflito de `nome` com outro código (`UQ_Parametros_Nome`), inclusive entre dois códigos novos do mesmo lote → ERROR, parâmetro rejeitado
- [x] Unidade do payload diferente da cadastrada (ex.: °F × °C) → ERROR, parâmetro rejeitado no lote (decisão na seção 11 da análise)
- [x] Medições de parâmetro rejeitado são descartadas na validação (`etapa=parametro`), sem invalidar a leitura
- [x] Criar `ParametroModel` e `ParametroRepository` (`get_all`, `get_by_codigo`, `create_many`)
- [x] `run_pipeline()`: sincroniza os parâmetros e lê as siglas de `Estados` antes de validar, passando faixas, siglas e parâmetros aceitos ao `ValidationService` (pendência da fase 6)

**Aceite:**

- [x] Um campo novo (`salinidade`, `salinidade_unidade_medida`, `salinidade_tipo_codigo`) cadastra 1 parâmetro e as medições dele seguem válidas; uma segunda execução não cadastra de novo (testado)
- [x] Com o dataset atual e o banco `impacta`: nenhum parâmetro inserido (11 antes e depois), 11 aceitos, 27 siglas lidas, mesmos números da validação das fases 5 e 6

---

## Fase 8 — Persistência idempotente

Ordem, tudo dentro de **uma** transação (`LeituraRepository.save_readings` → `DatabaseConnection.transaction()`):

- [x] Estados: só leitura (vem do DML) → `sigla → id_estado`
- [x] Municípios: `MERGE` por `(nome, estado_id)` → `(municipio, sigla) → id_municipio` (`importar_municipios`)
- [x] Operadores: grava os valores já protegidos na fase 4 (`nome_hash`, `cpf_hash`, `email_criptografado`); `MERGE` por `codigo_operador` → `codigo → id` (`importar_operadores`)
- [x] Estações: `MERGE` por `codigo_estacao` (atualiza nome, município e coordenadas) → `codigo → id` (`importar_estacoes`)
- [x] Parâmetros: fase 7; o retorno de `ParametroService.sincronizar()` já traz `codigo_parametro → ParametroModel` com `id_parametro`
- [x] Leituras e itens, **substituição de partição** (`LeituraRepository.substituir_leituras`), em operações de conjunto:
  1. carregar o lote em tabelas temporárias da sessão (`#lote`, `#itens`) com `INSERT` de várias linhas (`DatabaseConnection.insert_em_lotes`)
  2. marcar as leituras já gravadas na mesma estação + dia, ou com o mesmo `codigo_registro`
  3. `DELETE Leitura_Itens` e depois `DELETE Leituras` dessas leituras
  4. `INSERT` das leituras do lote e, com `JOIN` por `codigo_registro`, dos itens
- [x] Renomear e adaptar models e repositories: `MunicipioModel` e `MunicipioRepository` novos; `EstacaoModel`, `OperadorModel` e `LeituraModel` (cabeçalho) no formato do DDL; `LeituraItemModel` novo
- [x] Remover os métodos `create` com SQL em f-string de `leitura_repository.py` e `operador_repository.py` (e os `get_by_id`/`get_by_name` quebrados)
- [x] Adaptar `save_readings(registros, parametros, fonte)` e `importar_dados.py` à nova ordem (caches viram valores de retorno, não globais)
- [x] ~~Data Lake: gravar a Bronze~~ — implementada em `src/ingestion/bronze_writer.py` e **removida em 05/10/2026**: o Data Lake é tratado em outra frente do projeto
- [x] `run_pipeline()` passa a fazer só a ingestão e devolve o resumo (também registrado em INFO); a análise legada vai para `gerar_relatorio()`; comando `python main.py --ingestao`
- [x] Adaptar `CidadeRepository`, as consultas legadas de `EstacaoRepository`/`LeituraRepository`, a análise e a CLI ao modelo 3FN → fases 13 a 16

**Aceite** (banco `impacta`, dataset completo, dentro de uma transação desfeita com rollback ao final):

- [x] 1ª execução: 9.806 leituras e 104.582 itens gravados; 1 município, 1 operador, 1 estação (≈19 s)
- [x] 2ª execução: 9.806 leituras substituídas e regravadas, contagens idênticas (≈29 s)
- [x] Nenhuma duplicidade por `codigo_registro` nem por estação + data/hora, nenhuma leitura sem item, nenhum item fora da faixa, nenhum hash fora do padrão nem e-mail em claro
- [x] Rollback: todas as tabelas voltaram a zero
- [x] ~~Bronze com o dataset real~~ (removida; ver acima)

---

## Fase 9 — Validar o banco após a carga

Rodar após **duas** execuções seguidas do pipeline com o mesmo dataset. Todas as consultas de duplicidade e órfãos devem voltar **vazias**, e as contagens iguais nas duas execuções.

```sql
-- Contagens (comparar entre a 1ª e a 2ª execução)
SELECT 'Estados' t, COUNT(*) n FROM Estados UNION ALL
SELECT 'Municipios', COUNT(*) FROM Municipios UNION ALL
SELECT 'Estacoes', COUNT(*) FROM Estacoes UNION ALL
SELECT 'Operadores', COUNT(*) FROM Operadores UNION ALL
SELECT 'Parametros', COUNT(*) FROM Parametros UNION ALL
SELECT 'Leituras', COUNT(*) FROM Leituras UNION ALL
SELECT 'Leitura_Itens', COUNT(*) FROM Leitura_Itens;

-- Duplicidade de leitura por estação e horário (deve ser vazio)
SELECT estacao_id, data_hora, COUNT(*) FROM Leituras
GROUP BY estacao_id, data_hora HAVING COUNT(*) > 1;

-- Duplicidade pela chave natural (se D1 = a; deve ser vazio)
SELECT codigo_registro, COUNT(*) FROM Leituras
GROUP BY codigo_registro HAVING COUNT(*) > 1;

-- Leitura sem nenhum item (deve ser vazio)
SELECT L.id_leitura FROM Leituras L
WHERE NOT EXISTS (SELECT 1 FROM Leitura_Itens I WHERE I.leitura_id = L.id_leitura);

-- Valores fora da faixa do parâmetro (deve ser vazio)
SELECT P.codigo_parametro, I.valor, P.valor_minimo, P.valor_maximo
FROM Leitura_Itens I JOIN Parametros P ON P.id_parametro = I.parametro_id
WHERE (P.valor_minimo IS NOT NULL AND I.valor < P.valor_minimo)
   OR (P.valor_maximo IS NOT NULL AND I.valor > P.valor_maximo);

-- Hashes no formato esperado e e-mail nunca em claro (deve ser vazio)
SELECT id_operador FROM Operadores
WHERE LEN(nome_hash) <> 64 OR LEN(cpf_hash) <> 64
   OR email_criptografado LIKE '%@%';  -- se D7 = (a)

-- Itens por parâmetro (conferir com o resumo do log)
SELECT P.codigo_parametro, COUNT(*) FROM Leitura_Itens I
JOIN Parametros P ON P.id_parametro = I.parametro_id
GROUP BY P.codigo_parametro ORDER BY 1;
```

- [x] Conferências automatizadas no banco de teste (`tests/integration/`, 06/10/2026): todas as consultas acima vazias e contagens iguais nas duas execuções
- [x] Conferir: `Leituras` no banco + leituras no log de rejeitados = registros recebidos (9.806 + 82 = 9.888, testado)
- [x] Conferir: itens por parâmetro no banco + itens rejeitados do parâmetro = leituras gravadas (testado)
- [x] Backfill: rodar só uma data histórica e confirmar que só aquela partição muda (testado)
- [x] Logs de testes isolados de `logs/` (`PASTA_LOGS`), para a pasta guardar só a carga real
- [x] **Carga real no banco `impacta`** (06/10/2026): duas execuções de `python main.py --ingestao` com contagens idênticas, consultas acima vazias, 9.806 + 82 = 9.888, itens + rejeitados = 9.806 por parâmetro, nenhum CPF, nome ou e-mail em `logs/` e backfill de 10/07/2026 mudando só aquela partição

---

## Fase 10 — Testes

- [x] [tests/test_quality_stat.py](../tests/test_quality_stat.py): completude, acurácia e log de rejeitados com o dataset completo (aceite das fases 5 e 6)
- [x] `tests/test_quality_stat.py`: estatística e outliers (fase 14)
- [x] Testes unitários: normalização do payload novo (fase 4)
- [x] Testes unitários: `validate_data` devolvendo um resultado por registro (`valido`, `campos_nulos` com todos os nulos, `itens_invalidos`, `motivos`, `registro` só com itens válidos) e o log gerado a partir desses resultados
- [x] `src/security.py`: hash determinístico com 64 caracteres, `None` para vazio, ida e volta de `criptografar_email` / `descriptografar_email`
- [x] `src/logger.py`: formato da linha de rejeitado e ausência de CPF, nome e e-mail nos arquivos de `logs/`
- [x] Integração: reescrever `test_persistencia.py` e `test_pipeline_e2e.py` para o modelo 3FN, rodar o pipeline duas vezes e comparar as contagens (06/10/2026, SQL Server Express local)
- [x] Integração: forçar erro no meio da carga e conferir o rollback (primeira carga e reprocessamento)
- [x] Atualizar os testes existentes que usam o payload ou as tabelas antigas (seção 8 da análise); `registro_legado` removida. Analytics e relatório usam dados em memória e acompanham a fase de analytics

**Aceite:** `pytest` sem falhas; integração ignorada sem banco de teste configurado, como hoje.

- [x] 06/10/2026: `162 passed` com banco de teste; `153 passed, 9 skipped` sem ele

---

## Fase 11 — Documentação

- [x] Atualizar os documentos listados na seção 9 da análise (reescritos para a Parte 2: `modelagem-banco.md`, `contrato-dados.md`, `dicionario-dados.md`, `arquitetura.md`, os três diagramas e `README.md`; ajustados: `requisitos.md`, `analise-estatistica.md`)
- [x] Preencher o relatório de cada fase na seção 11 da análise (fases 0 a 8 e 11)
- [x] Revisão cruzada: README, arquitetura, diagramas, banco e manual (regras 9 a 11 do COPILOT.md)
- [x] Revisado depois da fase 10 e do Analytics (06/10/2026)
- [x] Revisado depois da primeira carga real (06/10/2026)

---

## Fase 12 — Decisões de Analytics (D9 a D11 bloqueiam as fases 14 e 16)

Detalhes e recomendações na seção 10 da análise. Requisito: item 3.4 do [projeto_final.pdf](projeto_final.pdf) e critério 4 da seção 6 (logs comprovando a detecção de outliers).

- [x] **D9** Indicador de alerta de qualidade só na análise (resultado, relatório/CSV e WARNING no log), sem mudança de schema (06/10/2026)
- [x] **D10** Anômala se fora do IQR **ou** com |Z| > 3; o indicador informa `IQR`, `ZSCORE` ou `IQR+ZSCORE` (06/10/2026)
- [x] **D11** CLI mostra todos os parâmetros da estação juntos, sem o menu de tipo (06/10/2026)
- [x] **D12** Precipitação com IQR = 0: manter a regra e documentar a limitação (06/10/2026)

---

## Fase 13 — Leitura dos dados no modelo 3FN

- [x] `LeituraRepository.get_medicoes(estacao_id=None, municipio_id=None, data_inicio=None, data_fim=None, codigos_parametro=None)`: uma linha por medição (`Leituras` + `Leitura_Itens` + `Parametros` + `Estacoes`), com estação, código e nome do parâmetro, unidade, data/hora, `codigo_registro` e valor; filtro por dia ou intervalo como hoje
- [x] `MunicipioRepository`/`EstacaoRepository`: listar municípios com estação e estações por município (substituem `CidadeRepository.get_all` e `EstacaoRepository.get_estacao_cidade`)
- [x] Remover as consultas legadas `get_leituras_*` de `LeituraRepository`, `get_estacao_cidade`, `CidadeRepository` e `CidadeModel`, atualizando usos e testes
- [x] Testes unitários das consultas (SQL e parâmetros) e de integração com o dataset completo

**Aceite:** nenhuma referência às tabelas `Cidades` ou às colunas largas de `Leituras` no código.

- [x] 06/10/2026: conferido por busca no código; `integration/test_analytics.py` passa

---

## Fase 14 — Estatística e outliers por estação e parâmetro

- [x] `AnaliticsService` reescrito sobre as medições da fase 13, agrupando por **estação + parâmetro** (os parâmetros vêm do banco, sem lista fixa no código; uma unidade por parâmetro, então não há mistura de unidades)
- [x] Métricas: quantidade, média, mediana, desvio padrão, **variância**, Q1, Q3, **IQR**, mínimo e máximo
- [x] Outliers pela regra IQR (`[Q1 − 1,5·IQR, Q3 + 1,5·IQR]`, mínimo de 4 valores, como hoje) e pelo **Z-Score** (regra da D10)
- [x] Indicador de alerta de qualidade em cada medição anômala (forma definida na D9), com estação, parâmetro, data/hora, `codigo_registro`, valor, limites e Z-Score
- [x] Outliers só sinalizados, nunca removidos (os fisicamente impossíveis já foram descartados na ingestão)
- [x] Testes unitários: CT-04 e CT-05 adaptados, variância e IQR, Z-Score, amostra pequena, desvio zero (Z-Score indefinido), agrupamento por estação e parâmetro

**Aceite:** com o dataset completo, métricas dos 11 parâmetros da estação e lista de outliers por IQR e Z-Score conferidas em `tests/test_quality_stat.py`.

- [x] 06/10/2026: 1.824 anomalias (1.528 `IQR`, 296 `IQR+ZSCORE`); precipitação com IQR = 0 sinaliza toda chuva (ponto para o time)

---

## Fase 15 — Relatório, logs e consultas SQL

- [x] `ReportService` com o formato novo (uma tabela de métricas por estação e parâmetro + tabela de anomalias com o indicador)
- [x] Comando `python main.py --analise [--estacao CODIGO] [--inicio AAAA-MM-DD] [--fim AAAA-MM-DD]`: `gerar_relatorio()` adaptado, métricas em INFO e cada anomalia em WARNING no log da execução (critério 4 do enunciado: "logs comprovando a detecção de outliers")
- [x] `sql/queries_analiticas.sql` (hoje vazio): agregações por estação e parâmetro com `GROUP BY` (contagem, média, desvio, mínimo, máximo, filtro por período), mediana/quartis com `PERCENTILE_CONT` e contagem por parâmetro
- [x] Testes: formato do relatório, `--analise` no `main.py` e execução das consultas no banco de teste

---

## Fase 16 — CLI no modelo 3FN

- [x] Fluxo Município → Estação → período → parâmetros (agrupamento conforme a D11) → métricas e anomalias
- [x] Salvar CSV: criar a pasta `relatorios/` se não existir (hoje falha) e corrigir a mensagem exibida quando o usuário não salva
- [x] Sem `print` (hoje `print("Saindo...")`); a CLI usa só `console.print`
- [x] Testes do fluxo com entradas simuladas

---

## Fase 17 — Documentação de Analytics

- [x] `analise-estatistica.md`: métricas, regras IQR e Z-Score, indicador de alerta e como executar
- [x] `arquitetura.md`, diagramas, `README.md`, `manual-execucao.md` (comando `--analise`) e `plano-testes.md`
- [x] Relatório das fases 12 a 17 na seção 11 da análise

---

## Fase 18 — Consumo resiliente da API (item 3.1 do enunciado)

Lacuna encontrada na revisão de 06/10/2026: previsto na seção 7 da análise, mas sem fase no TODO.

- [x] `DataClient.fetch_data()`: nova tentativa com espera crescente para queda de conexão, timeout, HTTP 5xx e 429; `Retry-After` respeitado
- [x] Rate limiting: no máximo 30 requisições por minuto, contando as novas tentativas
- [x] Resposta vazia (corpo vazio ou `[]`): `WARNING` e lote vazio; a `run_pipeline()` encerra com resumo zerado, sem abrir conexão com o banco
- [x] Erro 4xx e resposta fora do contrato (JSON inválido, não lista, registro que não é objeto): falha sem nova tentativa
- [x] Tentativas esgotadas: `ERROR` no log e `FonteIndisponivelError` (o `main.py` registra `CRITICAL` e sai com código 1)
- [x] Testes com relógio simulado (sem esperar de verdade) e teste manual com a API local fora e dentro do ar

---

## Fora deste TODO

- **Data Lake (Bronze, Silver e Gold): não será implementado** (decisão de 06/10/2026). A pasta `data_lake/` fica só como estrutura.
