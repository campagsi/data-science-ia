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
| **CT-01** | `validation` | Leitura com pH igual a $16.5$ (fora da escala físico-química). | Descarte controlado e gravação de log de anomalia sintática. | Atendido: só a medição é descartada (`etapa=acuracia`) e a leitura segue com as demais (`test_valor_fora_da_faixa_descarta_so_o_item`, `test_resultados_da_validacao_viram_linhas_e_contagens`). |
| **CT-02** | `validation` | Leitura contendo data e hora futura em relação a `now()`. | Rejeição imediata por violação da regra temporal. | Não implementado: a validação não possui regra temporal. |
| **CT-03** | `persistence` | Inserção simultânea de 2 registros idênticos (mesma estação, data e métrica). | Sem falha catastrófica; o registro existente deve ser atualizado (`upsert`). | Atendido: `UNIQUE (codigo_registro)` (V001) e substituição de partição; registro repetido no lote é rejeitado na validação. Conferido no banco `impacta` com duas cargas (relatório da fase 8) e testado na integração (`test_reprocessar_o_lote_substitui_sem_duplicar`). |
| **CT-04** | `analysis` | Amostra uniforme onde todos os valores de condutividade são iguais. | $IQR = 0$, desvio padrão $0$, nenhum registro marcado como outlier. | Atendido (`test_ct04_amostra_uniforme_nao_gera_outlier`). |
| **CT-05** | `analysis` | Amostra de oxigênio dissolvido com 99 pontos normais e 1 ponto com $0.05 \text{ mg/L}$. | O ponto destoante deve ser sinalizado com o indicador de alerta de qualidade. | Atendido: o ponto aparece nas anomalias com alerta `IQR+ZSCORE`, abaixo do limite inferior e com Z < −3 (`test_ct05_ponto_destoante_e_sinalizado_por_iqr_e_zscore`). |
| **CT-06** | `security` | O mesmo CPF escrito com e sem pontuação; o mesmo nome com espaços extras e maiúsculas. | Mesmo hash de 64 caracteres; CPFs diferentes geram hashes diferentes. | Atendido (`test_anonimizar_cpf_e_deterministico_e_ignora_pontuacao`, `test_anonimizar_nome_ignora_espacos_extras_e_maiusculas`, `test_cpfs_diferentes_geram_hashes_diferentes`). |
| **CT-07** | `security` | E-mail criptografado e lido com a mesma chave e com outra chave. | Mesma chave recupera o e-mail; outra chave falha sem expor o token. | Atendido (`test_criptografia_do_email_e_reversivel`, `test_descriptografar_com_outra_chave_falha_sem_expor_token`). |
| **CT-08** | `logger` | Rejeição informada com o valor de um campo pessoal (CPF, nome, e-mail ou seus hashes). | A linha do log cita o campo, mas nunca o valor. | Atendido (`test_valor_de_campo_pessoal_nunca_vai_para_o_log`). |
| **CT-09** | `main` | Aplicação iniciada sem `CHAVE_CRIPTOGRAFIA` ou com chave inválida. | Encerra com código `1`, mensagem `[CRITICAL]` e sem expor a chave. | Atendido (`test_aplicacao_nao_inicia_sem_chave_de_criptografia_valida`). |
| **CT-10** | `ingestion` | Mesmo dataset carregado duas vezes; backfill de uma data histórica. | Contagens idênticas nas tabelas e nenhuma duplicidade. | Atendido com o dataset completo: `test_duas_execucoes_seguidas_geram_o_mesmo_banco` e `test_backfill_de_um_dia_altera_so_aquela_particao`. |
| **CT-12** | `parametro` | Campo novo no payload (`salinidade` com unidade e `*_tipo_codigo`); o mesmo lote de novo; parâmetro sem unidade. | Cadastrado uma única vez, sem faixa, com as medições importadas; sem unidade, rejeitado com ERROR e só as medições dele descartadas. | Atendido (`test_parametro_novo_e_cadastrado_sem_faixa`, `test_aceite_fase_7_segunda_execucao_nao_cadastra_de_novo`, `test_medicoes_de_parametro_rejeitado_sao_descartadas_na_validacao`). |
| **CT-11** | `quality` | Leitura sem estação ou operador; medição nula; pH fora de 0–14. | Leitura ou item rejeitado e registrado no log de rejeitados; o resto do lote é gravado. | Atendido na validação e no log (`tests/test_quality_stat.py`, `unit/test_validation_service.py`); a gravação do restante do lote e o fechamento banco + log de rejeitados = recebidos estão em `test_banco_mais_rejeitados_fecha_com_o_recebido`. |
| **CT-14** | `analysis` | Medição fora do IQR, medição só com \|Z\| > 3, grupo com menos de 4 valores, grupo com um único valor. | Alerta `IQR`, `ZSCORE` ou `IQR+ZSCORE` conforme a regra; sem IQR abaixo de 4 valores; Z-Score indefinido com desvio zero ou um valor. | Atendido (`test_outlier_so_pelo_iqr`, `test_outlier_so_pelo_zscore`, `test_ct05_ponto_destoante_e_sinalizado_por_iqr_e_zscore`, `test_amostra_pequena_nao_aplica_iqr_e_um_valor_nao_tem_zscore`). |
| **CT-16** | `ingestion` | API fora do ar, instável (5xx), limitando requisições (429) ou devolvendo resposta vazia. | Novas tentativas com espera crescente, respeito ao `Retry-After` e ao limite por minuto; resposta vazia vira lote vazio com `WARNING`; falha definitiva com `ERROR`. | Atendido (`unit/test_data_client.py`, `test_lote_vazio_encerra_sem_tocar_no_banco`). |
| **CT-15** | `analysis` | Métricas e anomalias calculadas em Python e em SQL (`queries_analiticas.sql`) sobre o mesmo banco. | Mesmos valores de quantidade, média, desvio, variância, quartis, limites e mesma lista de anomalias. | Atendido (`integration/test_analytics.py`). |
| **CT-13** | `persistence` | Falha no meio da carga, depois de gravar leituras e itens, na primeira carga e num reprocessamento. | Rollback completo: nada do lote fica gravado e a carga anterior permanece intacta. | Atendido (`test_falha_na_primeira_carga_nao_deixa_nada_gravado`, `test_falha_no_reprocessamento_preserva_a_carga_anterior`). |

---

## 4. Execução Automatizada e Cobertura

A meta de cobertura da lógica de negócio e da validação é de **no mínimo 80%**.

### 4.1 Estrutura dos testes

```text
tests/
├── conftest.py            # fixtures (dataset, registro_bruto, seguranca, logs_temporarios), isolamento do .env e chaves de teste
├── unit/                  # sem banco e sem rede
├── integration/           # SQL Server descartável; ignorados sem configuração
└── test_quality_stat.py   # qualidade e estatística com o dataset completo (aceite das fases 5, 6 e 14)
```

O `conftest.py` da raiz define valores de teste antes de importar o código: `AZURE_SQL_CONNECTIONSTRING` e `FONTE_DADOS` (para que nenhum teste acesse o banco real ou a API configurados no `.env`) e `CHAVE_CRIPTOGRAFIA` e `PEPPER_HASH` (chave Fernet e segredo usados só nos testes). Por isso os testes rodam mesmo que o `.env` local ainda não tenha as chaves.

| Fixture | Uso |
|---|---|
| `dataset` | Dataset completo de `src/api/data_set.json` (sessão; não alterar) |
| `registro_bruto` | Cópia do 1º registro do dataset, no formato do payload |
| `seguranca` | Configura `src/security.py` com as chaves de teste |
| `logs_temporarios` | Configura os logs numa pasta temporária; `ler("pipeline")` e `ler("rejeitados")` devolvem as linhas |

| Arquivo | O que verifica |
|---|---|
| `unit/test_config.py` | `load_config()`: valores válidos, `AZURE_SQL_CONNECTIONSTRING`, `FONTE_DADOS` e `CHAVE_CRIPTOGRAFIA` obrigatórias, `FONTE_DADOS` com no máximo 100 caracteres, `PEPPER_HASH` opcional e ausência de segredos na mensagem |
| `unit/test_security.py` | `src/security.py`: hash com 64 caracteres, determinístico e sem o valor original, CPF com pontuação, nome com espaços e maiúsculas, efeito do pepper, `None` para vazio, ida e volta da criptografia do e-mail, token diferente a cada chamada, chave errada ou inválida sem expor segredos e erro quando a segurança não foi configurada (CT-06, CT-07) |
| `unit/test_sql_scripts.py` | scripts SQL sem banco: 27 UFs no DML, estados e parâmetros do dataset cobertos (código `*_tipo_codigo` e unidade iguais ao payload), nomes de parâmetro únicos, faixas coerentes, pH 0–14, DML só com `MERGE` e ordem dos `DROP` do DDL |
| `unit/test_parametro_service.py` | `ParametroService` com repositório em memória: parâmetros já cadastrados não são reinseridos, parâmetro novo cadastrado sem faixa com log INFO, segunda execução não cadastra de novo (aceite da fase 7), rejeição com ERROR (sem unidade, nome de outro código, unidade diferente da cadastrada, tamanho acima do DDL), unidade sem diferenciar maiúsculas, dois códigos novos com o mesmo nome, `faixas()`, descarte na validação das medições de parâmetro rejeitado e `INSERT ... WHERE NOT EXISTS` do repositório |
| `unit/test_logger.py` | `src/logger.py`: criação dos dois arquivos, formato da linha, rejeitados só no arquivo próprio, severidade `ERROR` para parâmetro, valor de campo pessoal omitido (CT-08), contagem por nível, `registrar_resultados_validacao()` (linhas e contagens a partir dos resultados) e linha de resumo |
| `unit/test_data_client.py` | `fetch_data()` com relógio simulado: endpoint, nova tentativa com espera crescente para queda de conexão, timeout, 500 e 503, tentativas esgotadas (`FonteIndisponivelError` e `ERROR`), `Retry-After` do 429, espaçamento pelo limite por minuto, 4xx sem nova tentativa, corpo vazio e `[]` como lote vazio (`WARNING`), JSON inválido, resposta que não é lista e registro que não é objeto (CT-16) |
| `unit/test_normalization_service.py` | `normalize()` com o payload novo: cabeçalho e tipos, `municipio` com fallback, 11 itens com código e unidade (inclusive nomes fora do padrão), anonimização e minimização, payload original preservado, texto vazio como `None`, medição nula mantida como item, rejeição só do item (medição não numérica, parâmetro sem código) ou só da leitura (data ou coordenada inválida), ordenação, parâmetro novo descoberto, campos descartados no log e aceite da fase 4 com o dataset completo |
| `unit/test_validation_service.py` | `validate_data()` com o contrato novo: um resultado por registro e na mesma ordem, `campos_nulos` com todos os campos vitais nulos, medição nula ou fora da faixa descartada só como item (inclusive limites e faixa aberta), parâmetro sem faixa, leitura sem medições válidas, coordenada fora da faixa, estado não cadastrado, sigla inválida, `registro_codigo` repetido, código de estação ou operador com dados diferentes, `registros_validos()`, registro normalizado preservado e nenhum dado pessoal em claro |
| `test_quality_stat.py` | aceite das fases 5, 6 e 14 com o dataset completo e as faixas do DML: 9.888 resultados, 82 inválidos (50 + 32), 2.681 medições nulas e 603 fora da faixa nos válidos, nenhum item gravável fora da faixa, log de rejeitados com 3.366 linhas sem dado pessoal; análise dos 11 parâmetros com 1.824 anomalias (1.528 `IQR`, 296 `IQR+ZSCORE`) e a limitação do IQR na precipitação |
| `unit/test_analytics_service.py` | `analisar_medicoes()` com dados determinísticos: métricas exigidas (média, mediana, desvio, variância, quartis, IQR, limites), CT-04, CT-05, outlier só por IQR e só por Z-Score (CT-14), amostra pequena e valor único, agrupamento por estação + parâmetro, contagem de leituras e filtros repassados por `calculate_metrics()` |
| `unit/test_report_service.py` | `generate_report()`, `format_report()` (métricas e anomalias arredondadas, sem anomalias, sem leituras) e `salvar_csv()` (cria a pasta, mantém o cabeçalho sem anomalias) |
| `unit/test_console_app.py` | CLI com entradas simuladas: consulta completa com datas convertidas, salvar CSV, opções e datas inválidas, voltar e período sem dados |
| `unit/test_metodos_ponte.py` | `connect()`, `transaction()` (conexão única, commit, rollback, aninhamento), `insert_estacao()` → `merge_many()`, `insert_leituras()` → `substituir_leituras()`, ordem de `save_readings()` (estados → municípios → operadores → estações → leituras, na mesma transação) e interrupção na primeira falha |
| `unit/test_main.py` | ordem das etapas de `run_pipeline()` (sincronização de parâmetros, leitura de estados, validação e gravação), resumo devolvido, análise legada fora da ingestão (`gerar_relatorio()`), propagação do erro, interrupção das etapas seguintes, ordem de `iniciar_aplicacao()` (logs → configuração → segurança) e código de saída `1` com mensagem `[CRITICAL]` sem expor segredos, inclusive sem chave ou com chave inválida (CT-09) |
| `integration/conftest.py` | cria um banco descartável e monta o schema aplicando `sql/ddl_banco_relacional.sql`, `sql/migrations/V*.sql` (o que também verifica que as migrations são idempotentes) e `sql/dml_populacao.sql`; a cada teste, esvazia as tabelas e reaplica o DML |
| `integration/conftest.py` (fixtures) | `normalizados` (dataset normalizado com as chaves de teste, por sessão) e `lote` (parâmetros sincronizados com o banco de teste e validação com faixas e siglas do banco, como na `run_pipeline()`) |
| `integration/test_persistencia.py` | `save_readings()` no modelo 3FN com o dataset completo: 9.806 leituras e 104.582 itens nas 7 tabelas, reprocessamento sem duplicar (consultas da fase 9 vazias), operador sem dado pessoal em claro e e-mail recuperável, backfill de um dia mudando só aquela partição e rollback de uma falha no meio da carga (primeira carga e reprocessamento) |
| `integration/test_analytics.py` | com o dataset gravado uma vez por módulo (`banco_carregado`): `get_medicoes()` e filtros, municípios e estações da CLI, análise dos 11 parâmetros, `queries_analiticas.sql` igual ao serviço (CT-15) e `gerar_relatorio()` com uma linha `WARNING` por anomalia |
| `integration/test_pipeline_e2e.py` | `run_pipeline()` de ponta a ponta duas vezes (resumo e contagens iguais), leituras no banco + leituras no log de rejeitados = recebidos, itens gravados + rejeitados por parâmetro = leituras gravadas e nenhum CPF, nome ou e-mail nos logs |

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

# normalização do payload novo
python -m pytest tests/unit/test_normalization_service.py

# cadastro automático de parâmetros
python -m pytest tests/unit/test_parametro_service.py

# gravação (métodos-ponte, ordem e transação)
python -m pytest tests/unit/test_metodos_ponte.py

# validação (completude, acurácia, unicidade) e aceite com o dataset completo
python -m pytest tests/unit/test_validation_service.py tests/test_quality_stat.py

# coerência dos scripts SQL com o dataset
python -m pytest tests/unit/test_sql_scripts.py
python -m pytest tests/unit/test_main.py -k chave

# motivo dos testes ignorados
python -m pytest tests -rs
```

Resultado esperado em 06/10/2026: sem banco de teste, **196 passed, 18 skipped**; com o banco de teste, **214 passed** (pouco mais de 1 minuto).

Nenhum teste grava em `logs/`: o `conftest.py` aponta a variável `PASTA_LOGS` para uma pasta temporária, inclusive para os testes de `test_main.py` que executam `python main.py` em um subprocesso. Assim, `logs/` guarda só os logs de cargas reais.

### 4.4 Testes de integração

Os testes de integração precisam de uma instância SQL Server de teste (por exemplo, SQL Server Express local) e da variável `TEST_SQL_MASTER_CONNECTIONSTRING` apontando para o banco `master`. Cada execução cria um banco descartável, aplica o `sql/ddl_banco_relacional.sql`, as migrations de `sql/migrations/` e o `sql/dml_populacao.sql`, e remove o banco ao final. Sem a variável, os 18 testes de integração aparecem como `skipped`; o motivo aparece com `python -m pytest tests -rs`.

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
