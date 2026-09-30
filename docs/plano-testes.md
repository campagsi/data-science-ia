# Estratégia e Plano de Testes

## 1. Visão Geral
Este documento formaliza as práticas de garantia da qualidade de software adotadas no pipeline, detalhando a separação de testes unitários, testes de integração e validação de contratos sintéticos.

---

## 2. Níveis de Teste

### 2.1 Testes Unitários
Focam no isolamento total da camada de lógica e regras puras de negócio:
* **Entidades e Domínio:** Garantir que entidades rejeitem estados inválidos na instanciação.
* **Validação Sintática:** Testar sanitizadores de campos nulos, formatos inválidos de datas e caracteres corrompidos.
* **Cálculo Estatístico:** Alimentar os algoritmos de média, mediana, desvio padrão e limites IQR com matrizes numéricas determinísticas contendo anomalias conhecidas e validar a classificação.

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

---

## 4. Execução Automatizada e Cobertura

A meta de cobertura da lógica de negócio e da validação é de **no mínimo 80%**.

### 4.1 Estrutura dos testes

```text
tests/
├── conftest.py            # registro de exemplo e isolamento do .env
├── unit/                  # sem banco e sem rede
└── integration/           # SQL Server descartável; ignorados sem configuração
```

O `conftest.py` da raiz substitui `AZURE_SQL_CONNECTIONSTRING` e `MOCK_API` por valores de teste antes de importar o código, para que nenhum teste acesse o banco real configurado no `.env`.

| Arquivo | O que verifica |
|---|---|
| `unit/test_config.py` | `load_config()`: valores válidos, variáveis obrigatórias e ausência de segredos na mensagem |
| `unit/test_data_client.py` | `fetch_data()`: endpoint, resposta que não é lista, registro que não é objeto e erro HTTP |
| `unit/test_normalization_service.py` | `normalize()`: conversões, payload original preservado, número vazio como `None` e valores inválidos |
| `unit/test_validation_service.py` | `validate_data()`, `validar_estacao()` e `validar_leitura()`: obrigatórios, medição nula ou sem chave aceita, intervalos, conflito de códigos e rejeição do lote |
| `unit/test_analytics_service.py` | média, mediana, desvio padrão e outliers IQR com dados determinísticos (CT-04 e CT-05), consolidação e escopo de `calculate_metrics()` |
| `unit/test_report_service.py` | `generate_report()` e `format_report()` |
| `unit/test_metodos_ponte.py` | `connect()`, `transaction()` (conexão única, commit, rollback, aninhamento), `insert_estacao()`, `insert_leituras()` e ordem de `save_readings()` |
| `unit/test_main.py` | ordem das etapas de `run_pipeline()`, propagação do erro, interrupção das etapas seguintes e código de saída `1` sem expor segredos |
| `integration/test_persistencia.py` | gravação relacionada, rollback do lote, consulta por período, consulta sem leituras e idempotência (`xfail`, CT-03) |
| `integration/test_pipeline_e2e.py` | `run_pipeline()` de ponta a ponta com registros completos e com o dataset completo atual, que grava as medições ausentes como `NULL` |

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

# motivo dos testes ignorados
python -m pytest tests -rs
```

### 4.4 Testes de integração

Os testes de integração precisam de uma instância SQL Server de teste (por exemplo, SQL Server Express local) e da variável `TEST_SQL_MASTER_CONNECTIONSTRING` apontando para o banco `master`. Cada execução cria um banco descartável e o remove ao final.

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
| `ModuleNotFoundError: No module named 'src'` | Execução fora da pasta `Data-Science-Ia`; rode os comandos a partir dela. |
| Todos os testes de integração ignorados | `TEST_SQL_MASTER_CONNECTIONSTRING` não definida na sessão atual do terminal. |
| Falha de login ou conexão nos testes de integração | Instância parada, nome da instância incorreto ou autenticação diferente da informada na string de conexão. |
