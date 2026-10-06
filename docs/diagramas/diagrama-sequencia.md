# Diagrama de sequência

Fluxo da ingestão (`python main.py --ingestao`), como está implementado.

```mermaid
sequenceDiagram
    autonumber
    actor Usuario as Usuário / Operador
    participant Main as main.py
    participant Log as logger.py
    participant Config as config.py
    participant Sec as security.py
    participant Client as data_client.py
    participant Normalizer as normalization_service.py
    participant Param as parametro_service.py
    participant Validator as validation_service.py
    participant Repository as leitura_repository.py
    participant DB as Azure SQL

    Usuario->>Main: python main.py --ingestao
    Main->>Log: configurar_logs()
    Main->>Config: load_config()
    Config-->>Main: settings (FONTE_DADOS, banco, chaves)
    Main->>Sec: configurar_seguranca(chave, pepper)

    Main->>Client: fetch_data()
    Client-->>Main: raw_data

    Main->>Normalizer: normalize(raw_data)
    Normalizer->>Sec: anonimizar_cpf(), anonimizar_nome(), criptografar_email()
    Normalizer->>Log: registrar_rejeicao() (o que não pode ser convertido)
    Normalizer-->>Main: normalizados (cabeçalho + itens)

    Main->>Param: sincronizar(descobrir_parametros(normalizados))
    Param->>DB: SELECT / INSERT Parametros (novos, sem faixa)
    Param-->>Main: parâmetros aceitos (id e faixa)
    Main->>DB: SELECT Estados (siglas)

    Main->>Validator: validate_data(normalizados)
    Validator-->>Main: um resultado por registro
    Main->>Log: registrar_resultados_validacao(resultados)

    Main->>Repository: save_readings(registros válidos, parâmetros, fonte)
    Repository->>DB: transaction()
    Note over Repository,DB: Uma única conexão e transação para o lote.
    Repository->>DB: MERGE Municipios, Operadores, Estacoes
    Repository->>DB: #lote, #itens → DELETE partições (estação + dia) → INSERT Leituras e Leitura_Itens
    DB-->>Repository: commit
    Note over Repository,DB: Qualquer falha faz rollback do lote inteiro.
    Repository-->>Main: contagens

    Main->>Log: registrar_resumo(...)
    Main-->>Usuario: resumo da ingestão
```

## Explicação das etapas

### 1. Inicialização (`main.py` → `logger.py`, `config.py`, `security.py`)

`iniciar_aplicacao()` executa, nesta ordem, `configurar_logs()`, `load_config()` e `configurar_seguranca()`. A configuração exige `AZURE_SQL_CONNECTIONSTRING`, `FONTE_DADOS` (URL da API, até 100 caracteres) e `CHAVE_CRIPTOGRAFIA`. Uma falha aqui é registrada com nível `CRITICAL` e encerra com código `1`, sem expor segredos. Com `--analise`, executa a análise (seção abaixo); sem argumentos, abre a CLI de consulta.

### 2. Coleta (`data_client.py`)

`fetch_data()` busca `GET {FONTE_DADOS}/api/v1/data-set` e exige uma lista de objetos.

### 3. Normalização e anonimização (`normalization_service.py`)

Limpa os textos, converte números e datas e separa cada registro em cabeçalho mais itens, um por parâmetro (`*_tipo_codigo`). Anonimiza o operador com `src/security.py` e não copia CPF, nome e e-mail originais. O que não pode ser convertido vai para o log de rejeitados sem interromper o lote. Formato completo em [contrato-dados.md](../contrato-dados.md).

### 4. Parâmetros e referências (`parametro_service.py`, `estado_repository.py`)

`ParametroService.sincronizar()` cadastra os parâmetros novos sem faixa e rejeita, com ERROR, os que não podem ser usados (sem unidade, nome de outro código ou unidade diferente da cadastrada). As siglas de `Estados` também são lidas do banco.

### 5. Validação (`validation_service.py`) e log de rejeitados

`ValidationService.validate_data()`, com as faixas, as siglas e os parâmetros aceitos lidos do banco, devolve um resultado por registro com `valido`, `campos_nulos`, `itens_invalidos`, `motivos` e o registro só com as medições válidas. Ela não grava nem loga. `registrar_resultados_validacao()` grava o log de rejeitados a partir desses resultados, e só `ValidationService.registros_validos(resultados)` segue para a gravação.

### 6. Gravação (`leitura_repository.py` → banco)

`save_readings()` abre uma transação (`DatabaseConnection.transaction()`) e chama, na mesma conexão, `importar_municipios`, `importar_operadores` e `importar_estacoes` (`MERGE` pela chave natural) e `importar_leituras` → `substituir_leituras()`. Esta última carrega o lote em tabelas temporárias, apaga as leituras das partições estação + dia do lote (e as de mesmo `codigo_registro`), itens primeiro, e insere leituras e itens com operações de conjunto. O commit ocorre só ao final; qualquer falha desfaz o lote. O schema não é criado pelo pipeline: vem de `sql/ddl_banco_relacional.sql` e `sql/migrations/`.

### 7. Resumo (`logger.py`)

Depois do commit, `registrar_resumo()` grava no log a linha `Resumo da ingestão`, que é também o retorno de `run_pipeline()`. O Data Lake (Bronze, Silver e Gold) não será implementado neste projeto.

## Análise e relatório (`python main.py --analise`)

```mermaid
sequenceDiagram
    autonumber
    actor Usuario as Usuário / Operador
    participant Main as main.py
    participant Analise as analytics_service.py
    participant Repo as leitura_repository.py
    participant Report as report_service.py
    participant Log as logger.py
    participant DB as Azure SQL

    Usuario->>Main: python main.py --analise [--estacao] [--inicio] [--fim]
    Main->>Analise: buscar_estacao_por_codigo(codigo)
    Main->>Analise: calculate_metrics(estacao_id, data_inicio, data_fim)
    Analise->>Repo: get_medicoes(filtros)
    Repo->>DB: SELECT Leitura_Itens + Leituras + Parametros + Estacoes
    DB-->>Repo: uma linha por medição
    Analise->>Analise: analisar_medicoes(): métricas por estação + parâmetro, IQR, Z-Score, alerta
    Analise-->>Main: estatisticas, anomalias
    Main->>Report: generate_report(), format_report()
    Main->>Log: relatório em INFO
    Main->>Log: registrar_anomalias(): uma linha WARNING por anomalia
```

A análise não grava nada no banco: o indicador de alerta fica no resultado, no log e no CSV da CLI (decisão D9). A CLI usa o mesmo `calculate_metrics()`, com a estação e o período escolhidos no menu. Regras: [analise-estatistica.md](../analise-estatistica.md).

## Observação

Este diagrama representa a comunicação entre os módulos da ingestão e deve ser atualizado sempre que o fluxo do código mudar.
