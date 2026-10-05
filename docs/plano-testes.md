# Estratégia e Plano de Testes

Este plano contém cenários do enunciado original e melhorias adicionadas durante a evolução do projeto. Idempotência/upsert, rejeição de data futura e descarte individual com log são extensões, não requisitos expressos no enunciado. Os testes previstos para a Parte 2 estão na seção 8 de [analise-implementacao.md](analise-implementacao.md).

## 1. Visão Geral
Este documento formaliza as práticas de garantia da qualidade de software adotadas no pipeline, detalhando a separação de testes unitários, testes de integração e validação de contratos sintéticos.

---

## 2. Níveis de Teste

### 2.1 Testes Unitários
Focam no isolamento total da camada de lógica e regras puras de negócio:
* **Entidades e Domínio:** Garantir que entidades rejeitem estados inválidos na instanciação.
* **Validação Sintática:** Testar sanitizadores de campos nulos, formatos inválidos de datas e caracteres corrompidos.
* **Cálculo Estatístico:** Alimentar os algoritmos de média, mediana, desvio padrão e limites IQR com matrizes numéricas determinísticas contendo anomalias conhecidas e validar a classificação.
* **Segurança (LGPD):** Hash determinístico de CPF e nome, criptografia reversível do e-mail, rejeição de chave inválida e nenhuma chave ou token em mensagem de erro ([seguranca-lgpd.md](seguranca-lgpd.md)).
* **Logs:** Formato `data - [NÍVEL] - mensagem`, separação entre log de execução e log de rejeitados e ausência de dado pessoal nos arquivos.

### 2.2 Testes de Integração
Validam a interoperabilidade segura com componentes de infraestrutura:
* **Persistência Relacional:** Validação de transações em banco SQL Server isolado (ex: banco descartável em uma instância local do SQL Server Express).
* **Idempotência do Banco:** Tentativa de persistir leituras duplicadas e verificar que nenhuma duplicidade é criada (depende das restrições de unicidade ainda não implementadas no schema).
* **Rollback Transacional:** Forçar inconsistência no meio de um lote de leituras e validar a integridade transacional garantindo que nenhum item parcial seja gravado.

### 2.3 Testes de Contrato e Ingestão
* **Mock de API REST:** Utilização de interceptores HTTP para emular timeouts, payloads quebrados, respostas `404` e `500`.
* **Cenários de Fronteira no JSON:** Execução contra arquivos de teste contendo estruturas vazias (`[]`), chaves ausentes e strings em locais de valores numéricos.

---

## 3. Matriz de Cenários e Casos Críticos

| Identificador | Módulo | Cenário Avaliado | Resultado Esperado | Situação atual |
|---|---|---|---|---|
| **CT-01** | `validation` | Leitura com pH igual a $16.5$ (fora da escala físico-química). | Descarte controlado e gravação de log de anomalia sintática. | Parcial: a validação rejeita o lote inteiro e informa o índice do registro (`test_validate_data_rejeita_valor_fora_do_contrato`, `test_validate_data_rejeita_lote_inteiro`); descarte individual e log não implementados. |
| **CT-02** | `validation` | Leitura contendo data e hora futura em relação a `now()`. | Rejeição imediata por violação da regra temporal. | Não implementado: a validação não possui regra temporal. |
| **CT-03** | `persistence` | Inserção simultânea de 2 registros idênticos (mesma estação, data e métrica). | Sem falha catastrófica; o registro existente deve ser atualizado (`upsert`). | Não implementado: o schema não possui `UNIQUE` e o reprocessamento duplica as leituras (`test_reprocessar_o_lote_nao_duplica_leituras`, marcado como `xfail`). |
| **CT-04** | `analysis` | Amostra uniforme onde todos os valores de condutividade são iguais. | $IQR = 0$, desvio padrão $0$, nenhum registro marcado como outlier. | Atendido (`test_ct04_amostra_uniforme_nao_gera_outlier`). |
| **CT-05** | `analysis` | Amostra de oxigênio dissolvido com 99 pontos normais e 1 ponto com $0.05 \text{ mg/L}$. | O ponto destoante deve ser rotulado com `is_outlier = true`. | Atendido com o formato atual: o ponto aparece na lista de outliers, abaixo do limite inferior (`test_ct05_ponto_destoante_e_identificado_como_outlier`). |
| **CT-06** | `security` | O mesmo CPF escrito com e sem pontuação; o mesmo nome com espaços extras e maiúsculas. | Mesmo hash de 64 caracteres; CPFs diferentes geram hashes diferentes. | Atendido (`test_anonimizar_cpf_e_deterministico_e_ignora_pontuacao`, `test_anonimizar_nome_ignora_espacos_extras_e_maiusculas`, `test_cpfs_diferentes_geram_hashes_diferentes`). |
| **CT-07** | `security` | E-mail criptografado e lido com a mesma chave e com outra chave. | Mesma chave recupera o e-mail; outra chave falha sem expor o token. | Atendido (`test_criptografia_do_email_e_reversivel`, `test_descriptografar_com_outra_chave_falha_sem_expor_token`). |
| **CT-08** | `logger` | Rejeição informada com o valor de um campo pessoal (CPF, nome, e-mail ou seus hashes). | A linha do log cita o campo, mas nunca o valor. | Atendido (`test_valor_de_campo_pessoal_nunca_vai_para_o_log`). |
| **CT-09** | `main` | Aplicação iniciada sem `CHAVE_CRIPTOGRAFIA` ou com chave inválida. | Encerra com código `1`, mensagem `[CRITICAL]` e sem expor a chave. | Atendido (`test_aplicacao_nao_inicia_sem_chave_de_criptografia_valida`). |
| **CT-10** | `ingestion` | Mesmo dataset carregado duas vezes; backfill de uma data histórica. | Contagens idênticas nas tabelas e nenhuma duplicidade. | Planejado: fases 8 a 10 de [todo-idempotencia.md](todo-idempotencia.md). |
| **CT-11** | `quality` | Leitura sem estação ou operador; medição nula; pH fora de 0–14. | Leitura ou item rejeitado e registrado no log de rejeitados; o resto do lote é gravado. | Planejado: fases 5, 6 e 10 de [todo-idempotencia.md](todo-idempotencia.md) (`tests/test_quality_stat.py`). |

---

## 4. Execução Automatizada e Cobertura

A meta de cobertura da lógica de negócio e da validação é de **no mínimo 80%**.

### 4.1 Estrutura dos testes

```text
tests/
├── conftest.py            # registro de exemplo, isolamento do .env e chaves de teste
├── unit/                  # sem banco e sem rede
├── integration/           # SQL Server descartável; ignorados sem configuração
└── test_quality_stat.py   # qualidade e estatística da Parte 2 (ainda sem testes; fase 10 do TODO)
```

O `conftest.py` da raiz define valores de teste antes de importar o código: `AZURE_SQL_CONNECTIONSTRING` e `MOCK_API` (para que nenhum teste acesse o banco real configurado no `.env`) e `CHAVE_CRIPTOGRAFIA` e `PEPPER_HASH` (chave Fernet e segredo usados só nos testes). Por isso os testes rodam mesmo que o `.env` local ainda não tenha as chaves.

| Arquivo | O que verifica |
|---|---|
| `unit/test_config.py` | `load_config()`: valores válidos, `CHAVE_CRIPTOGRAFIA` obrigatória, leitura de `PEPPER_HASH` e `FONTE_DADOS`, padrões das variáveis opcionais e ausência de segredos na mensagem |
| `unit/test_security.py` | `src/security.py`: hash com 64 caracteres, determinístico e sem o valor original, CPF com pontuação, nome com espaços e maiúsculas, efeito do pepper, `None` para vazio, ida e volta da criptografia do e-mail, token diferente a cada chamada, chave errada ou inválida sem expor segredos e erro quando a segurança não foi configurada (CT-06, CT-07) |
| `unit/test_sql_scripts.py` | scripts SQL sem banco: 27 UFs no DML, estados e parâmetros do dataset cobertos (código `*_tipo_codigo` e unidade iguais ao payload), nomes de parâmetro únicos, faixas coerentes, pH 0–14, DML só com `MERGE` e ordem dos `DROP` do DDL |
| `unit/test_logger.py` | `src/logger.py`: criação dos dois arquivos, formato da linha, rejeitados só no arquivo próprio, severidade `ERROR` para parâmetro, valor de campo pessoal omitido (CT-08), contagem por nível e linha de resumo |
| `unit/test_data_client.py` | `fetch_data()`: endpoint, resposta que não é lista, registro que não é objeto e erro HTTP |
| `unit/test_normalization_service.py` | `normalize()`: conversões, payload original preservado, número vazio como `None` e valores inválidos |
| `unit/test_validation_service.py` | `validate_data()`, `validar_estacao()` e `validar_leitura()`: obrigatórios, medição nula ou sem chave aceita, intervalos, conflito de códigos e rejeição do lote |
| `unit/test_analytics_service.py` | média, mediana, desvio padrão e outliers IQR com dados determinísticos (CT-04 e CT-05), consolidação e escopo de `calculate_metrics()` |
| `unit/test_report_service.py` | `generate_report()` e `format_report()` |
| `unit/test_metodos_ponte.py` | `connect()`, `transaction()` (conexão única, commit, rollback, aninhamento), `insert_estacao()`, `insert_leituras()` e ordem de `save_readings()` |
| `unit/test_main.py` | ordem das etapas de `run_pipeline()`, propagação do erro, interrupção das etapas seguintes, ordem de `iniciar_aplicacao()` (logs → configuração → segurança) e código de saída `1` com mensagem `[CRITICAL]` sem expor segredos, inclusive sem chave ou com chave inválida (CT-09) |
| `integration/conftest.py` | cria um banco descartável e monta o schema aplicando `sql/ddl_banco_relacional.sql`, `sql/migrations/V*.sql` (o que também verifica que as migrations são idempotentes) e `sql/dml_populacao.sql`; a cada teste, esvazia as tabelas e reaplica o DML |
| `integration/test_persistencia.py` | **pulado** (`pytest.mark.skip`): ainda usa o modelo antigo (`Cidades`); será reescrito nas fases 8 e 10 do [TODO](todo-idempotencia.md) |
| `integration/test_pipeline_e2e.py` | **pulado** (`pytest.mark.skip`): mesmo motivo; será reescrito nas fases 8 e 10 |

### 4.2 Preparar o ambiente

Na pasta `Data-Science-Ia`, com o ambiente virtual ativado, instale as dependências, que incluem `pytest` e `pytest-cov`:

```bash
pip install -r requirements.txt
```

### 4.3 Executar os testes

```bash
# todos os testes (os de integração são ignorados sem banco de teste)
python -m pytest tests

# somente os unitários
python -m pytest tests/unit

# um arquivo, um teste ou os testes cujo nome contém um termo
python -m pytest tests/unit/test_validation_service.py
python -m pytest tests/unit/test_analytics_service.py::test_ct04_amostra_uniforme_nao_gera_outlier
python -m pytest tests -k validate_data

# segurança (LGPD) e logs
python -m pytest tests/unit/test_security.py tests/unit/test_logger.py

# coerência dos scripts SQL com o dataset
python -m pytest tests/unit/test_sql_scripts.py
python -m pytest tests/unit/test_main.py -k chave

# motivo dos testes ignorados
python -m pytest tests -rs
```

Resultado esperado em 05/10/2026, sem banco de teste: **103 passed, 7 skipped**.

Os testes de `test_main.py` que executam `python main.py` em um subprocesso criam arquivos em `logs/`. A pasta está no `.gitignore` e pode ser apagada a qualquer momento. Os testes de `test_logger.py` usam uma pasta temporária e não deixam arquivos.

### 4.4 Testes de integração

Os testes de integração precisam de uma instância SQL Server de teste (por exemplo, SQL Server Express local) e da variável `TEST_SQL_MASTER_CONNECTIONSTRING` apontando para o banco `master`. Cada execução cria um banco descartável, aplica o `sql/ddl_banco_relacional.sql`, as migrations de `sql/migrations/` e o `sql/dml_populacao.sql`, e remove o banco ao final. Enquanto os testes de persistência e de ponta a ponta não forem reescritos para o modelo 3FN, eles aparecem como `skipped` mesmo com a variável configurada; o motivo aparece com `python -m pytest tests -rs`.

```powershell
$env:TEST_SQL_MASTER_CONNECTIONSTRING = "Server=localhost\SQLEXPRESS;Database=master;Trusted_Connection=yes;Encrypt=no"
python -m pytest tests
```

Nunca aponte essa variável para o banco do Azure usado pela aplicação.

### 4.5 Cobertura

```bash
python -m pytest tests --cov=src --cov=main
python -m pytest tests --cov=src --cov=main --cov-report=html   # relatório em htmlcov/index.html
```

`.pytest_cache`, `.coverage` e `htmlcov` estão no `.gitignore`.

### 4.6 Como interpretar o resultado

| Resultado | Significado |
|---|---|
| `passed` | O teste passou. |
| `failed` | O comportamento divergiu do esperado; a mensagem mostra a linha e os valores comparados. |
| `skipped` | Teste ignorado; nos de integração, indica que `TEST_SQL_MASTER_CONNECTIONSTRING` não está configurada. |
| `xfailed` | Falha esperada de uma pendência conhecida (CT-03). |
| `XPASS(strict)` | O teste marcado como falha esperada passou; a pendência foi resolvida e a marcação `xfail` deve ser removida. |

### 4.7 Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `No module named pytest` | Ambiente virtual não ativado ou dependências não instaladas; ative o `.venv` e execute `pip install -r requirements.txt`. |
| `No module named 'rich'` ou `No module named 'cryptography'` | Dependências adicionadas na Parte 2; execute `pip install -r requirements.txt` novamente. |
| `ModuleNotFoundError: No module named 'src'` | Execução fora da pasta `Data-Science-Ia`; rode os comandos a partir dela. |
| Todos os testes de integração ignorados | `TEST_SQL_MASTER_CONNECTIONSTRING` não definida na sessão atual do terminal. |
| Falha de login ou conexão nos testes de integração | Instância parada, nome da instância incorreto ou autenticação diferente da informada na string de conexão. |
