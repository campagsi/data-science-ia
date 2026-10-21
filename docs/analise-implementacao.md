# Análise de implementação — Parte 2 (novo banco relacional, idempotência e campos nulos)

Este documento descreve **o que muda** no projeto com a nova estrutura do banco de dados definida em [sql/ddl_banco_relacional.sql](../sql/ddl_banco_relacional.sql) e registra, fase a fase, o relatório do que for implementado (regra 12 do COPILOT.md).

O passo a passo de execução está em [todo-idempotencia.md](todo-idempotencia.md). O modelo do banco não é repetido aqui: a fonte é o DDL e a explicação fica em [modelagem-banco.md](modelagem-banco.md).

Referências do enunciado ([projeto_final.pdf](projeto_final.pdf)):

- **3.2 Qualidade:** completude (campos vitais nulos), unicidade (retransmissões), acurácia (pH fora de 0–14, temperaturas inviáveis) e ordenação temporal.
- **3.3 Modelagem 3FN:** Estacoes, Operadores (anonimizados), Parametros (domínio), Leituras (cabeçalho) e Leitura_Itens (N:M com PK composta).
- **3.7 Orquestração:** reexecução para uma data histórica (backfill) deve **sobrescrever a partição afetada sem duplicar linhas**; logs estruturados com data/hora, severidade (INFO, WARNING, ERROR) e mensagem, sem exibições simples de tela.

---

## 1. Validação do banco contra o DDL (05/10/2026)

Conexão feita no banco `impacta` (Azure SQL) com consultas somente de leitura em `INFORMATION_SCHEMA` e `sys.*`.

| Item | Resultado |
|---|---|
| Tabelas | `Estados`, `Municipios`, `Estacoes`, `Operadores`, `Parametros`, `Leituras`, `Leitura_Itens`: todas presentes |
| Colunas, tipos e nulabilidade | Idênticos ao DDL (inclui `DECIMAL(10,7)` em latitude/longitude e `DEFAULT getdate()` em `data_ingestao`) |
| PK, FK, UNIQUE, CHECK | Idênticos ao DDL (7 FKs, 2 CHECKs de latitude/longitude) |
| Índices | Os 7 índices `IX_*` do DDL estão criados |
| Dados | Todas as tabelas vazias |
| Diferenças | Apenas `dbo.sysdiagrams` a mais, criada pelo SSMS; não interfere |
| Tabelas antigas | `Cidades` e a `Leituras` larga não existem mais |

**Conclusão:** o banco está igual ao DDL. A partir daqui, o schema é mantido pelo script SQL e **o pipeline não cria mais tabelas**.

---

## 2. Modelo antigo → modelo novo

| Antes (Parte 1) | Depois (Parte 2) | Mudança |
|---|---|---|
| `Cidades (nome, estado CHAR 2)` | `Estados` + `Municipios` | Estado vira tabela própria (3FN). `Estados.nome` é obrigatório e o payload só traz a sigla, por isso os estados precisam vir de carga inicial (DML). |
| `Operadores (codigo, nome, tipo, cidade_id)` | `Operadores (codigo_operador, nome_hash, cpf_hash, municipio_id, email_criptografado)` | Nome e CPF como hash SHA-256; e-mail criptografado (D7, migration V002). `tipo` deixa de existir. Regras em [seguranca-lgpd.md](seguranca-lgpd.md). |
| `Estacoes (..., operador_id, ativa, tipo)` | `Estacoes (codigo_estacao, nome, municipio_id, latitude, longitude)` | Estação deixa de apontar para operador; o operador passa a ficar na leitura. `ativa` e `tipo` deixam de existir. |
| `Leituras` larga (uma coluna por medição) | `Leituras` (cabeçalho) + `Leitura_Itens` (um item por parâmetro) + `Parametros` (domínio) | Medição vira linha, e parâmetro novo não exige mais `ALTER TABLE`. |
| — | `Leituras.operador_id NOT NULL` | Toda leitura exige operador. |
| — | `Leitura_Itens.valor NOT NULL` | Medição nula **não vira item**. |
| Schema criado pelo Python (`criar_tabelas.py`) | Schema mantido pelo `ddl_banco_relacional.sql` (estado final) + `sql/migrations/` (mudanças incrementais) | `criar_tabelas.py` foi removido em 05/10/2026. |

---

## 3. Mapeamento do payload novo para as tabelas

Payload atual da API (`src/api/data_set.json`): **9.888 registros**, um registro por ciclo de estação.

| Campo(s) do payload | Destino | Observação |
|---|---|---|
| `cidade_estado` | `Estados.sigla` (busca) | Precisa existir na carga de Estados; sigla desconhecida → rejeita. |
| `cidade_nome` / `municipio` | `Municipios.nome` | Os dois campos têm o mesmo valor no dataset; usar `municipio` e cair para `cidade_nome` se vier nulo. |
| `cidade_codigo` (IBGE) | — | Sem coluna no DDL (ver decisão D5). |
| `estacao_codigo`, `estacao_nome`, `estacao_latitude`, `estacao_longitude` | `Estacoes` | |
| `estacao_ativa`, `estacao_tipo` | — | Sem coluna no DDL (D5). |
| `operador_codigo` | `Operadores.codigo_operador` | |
| `operador_nome_completo`, `operador_cpf` | `nome_hash`, `cpf_hash` | `anonimizar_nome` / `anonimizar_cpf` de `src/security.py` (SHA-256, 64 caracteres). |
| `operador_email` | `Operadores.email_criptografado` (D7, migration V002) | `criptografar_email` de `src/security.py` (Fernet, reversível). |
| — | — | Os três campos originais são removidos do registro logo após a anonimização (minimização); depois disso nada os grava nem loga. Ver [seguranca-lgpd.md](seguranca-lgpd.md). |
| `operador_ativo` | — | Sem coluna no DDL (D5). |
| `registro_codigo` | `Leituras.codigo_registro` (chave natural, `UNIQUE`) | Coluna criada pela migration V001 (D1). |
| `data_hora_ciclo` | `Leituras.data_hora` | |
| — | `Leituras.fonte` | **Não existe no payload** e a coluna é `NOT NULL` (D3). |
| `<param>` | `Leitura_Itens.valor` | Valor nulo → não grava o item e registra no log de rejeitados. |
| `<param>_tipo_codigo` (ex.: `TIP-PH`) | `Parametros.codigo_parametro` | Base da descoberta de parâmetros novos. |
| `<param>_unidade_medida` | `Parametros.unidade_medida` | Exceções no payload: `oxigenio_dissolvido_medida` e `velocidade_unidade_medida`. |
| `<param>_codigo` (ex.: `PH-RJ001-00001`), `data_hora_leitura_<param>` | — | Sem coluna no DDL (D5). |

> **Referência vigente:** o contrato do payload, do registro normalizado e do resultado da validação passou a ficar em [contrato-dados.md](contrato-dados.md). As subseções abaixo registram como o desenho foi decidido.

### Formato do registro normalizado (fase 4)

Saída de `NormalizationService.normalize()`: um dicionário por registro, ordenado por `data_hora_ciclo`. Os nomes de campo são os do payload, para o log de rejeitados citar exatamente o campo de origem.

```python
{
    "registro_codigo": "REG-RJ-001-00001",
    "data_hora_ciclo": datetime(2026, 4, 1, 0, 0),
    "cidade_estado": "RJ",
    "municipio": "Rio de Janeiro",            # cai para cidade_nome se vier nulo
    "estacao_codigo": "EST-RJ-001",
    "estacao_nome": "Estação Integrada Guanabara Norte",
    "estacao_latitude": -22.8768,
    "estacao_longitude": -43.1929,
    "operador_codigo": "OP-RJ-001",
    "cpf_hash": "<64 hex>",                   # originais não são copiados
    "nome_hash": "<64 hex>",
    "email_criptografado": "<token Fernet>",
    "itens": [
        {"campo": "ph", "codigo_parametro": "TIP-PH", "unidade_medida": "pH",
         "valor": 7.53, "data_hora_leitura": datetime(2026, 4, 1, 0, 2, 10)},
        ...                                   # valor None = medição nula (fase 5)
    ],
}
```

Na normalização, um texto vazio vira `None`. O que não pode ser convertido não derruba o lote:

- medição não numérica ou sem `*_tipo_codigo`: rejeita só o item;
- `data_hora_ciclo` ou coordenada inválida: rejeita só a leitura.

Campo vital nulo não é rejeitado aqui; isso fica para a completude (fase 5).

### Parâmetros presentes hoje no payload (11)

`temperatura_agua` (TIP-TAG, °C), `ph` (TIP-PH, pH), `temperatura` (TIP-TMP, °C), `umidade` (TIP-UMI, %), `pressao` (TIP-PRE, hPa), `precipitacao` (TIP-CHU, mm), `velocidade_vento` (TIP-VEN, km/h), `radiacao_solar` (TIP-RAD, W/m²), `oxigenio_dissolvido` (TIP-OXI, mg/L), `condutividade` (TIP-CON, µS/cm), `turbidez` (TIP-TUR, NTU).

`direcao_vento`, usado pela Parte 1, **não vem mais** no payload.

### Regra de descoberta de parâmetro novo

Todo campo `X_tipo_codigo` define um parâmetro `X`. Se `codigo_parametro` ainda não existe em `Parametros`, ele é cadastrado com:

- `codigo_parametro` = valor de `X_tipo_codigo`;
- `nome` = nome legível conhecido, ou o próprio `X`;
- `unidade_medida` = primeiro valor encontrado entre `X_unidade_medida`, `X_medida` e `<primeiro termo de X>_unidade_medida`;
- `valor_minimo` / `valor_maximo` = `NULL`, porque parâmetro novo não tem faixa até alguém definir.

Sem unidade, não há como cadastrar (`unidade_medida NOT NULL`): o parâmetro é registrado como rejeitado com nível ERROR e os itens dele não são gravados. O mesmo vale para um nome que já pertence a outro código e para uma unidade diferente da cadastrada. Implementado em `src/services/parametro_service.py` (fase 7); o nome legível inicial vem do campo (`salinidade_total` → `Salinidade total`).

---

## 4. Perfil de qualidade do dataset atual

| Dimensão | Achado | Tratamento proposto |
|---|---|---|
| Completude: estação nula | 50 registros sem nenhum campo `estacao_*` (nos 50, o operador também é nulo) | Rejeitar a leitura inteira e logar |
| Completude: operador nulo | 82 registros (32 têm estação) | Rejeitar a leitura inteira e logar (D2) |
| Completude: medição nula | De 214 (`temperatura`) a 273 (`condutividade`) por parâmetro | Não gravar o item e logar com WARNING; o restante da leitura segue |
| Completude: leitura sem nenhuma medição | 0 | Rejeitar o cabeçalho (evita `Leituras` órfã de itens) |
| Completude: `data_hora_ciclo` nula | 0 | Rejeitar |
| Unicidade | `registro_codigo` único em 9.888; nenhum par (estação, ciclo) repetido | Unicidade garantida no banco pela chave natural (D1) |
| Acurácia | Com as faixas do DML, 603 medições fora da faixa nos registros válidos (pH 72, umidade 69, radiação 81, pressão 75, vento 73, OD 68, temperatura da água 60, condutividade 40, precipitação 37, turbidez 28) | Rejeitar **o item**, comparando com `Parametros.valor_minimo/maximo` |
| Tempestividade | Ciclos de 01/04/2026 a 23/10/2026; nenhuma `data_hora_leitura_*` anterior ao ciclo | Ordenar por `data_hora_ciclo` antes de gravar |

### Resultado da validação por registro (requisito do time, 05/10/2026)

A verificação dos campos acontece **antes de gravar** em qualquer destino. Ela **não grava nem loga**: devolve um resultado por registro, e as etapas seguintes decidem o que fazer com ele.

`validate_data(normalizados)` devolve uma lista (array) com **um resultado por registro recebido**, na mesma ordem:

```python
{
    "registro_codigo": "REG-RJ-001-00042",
    "valido": False,                        # o registro pode ou não ser ingerido
    "campos_nulos": ["operador_codigo", "cpf_hash"],   # campos que faltaram ou vieram nulos
    "itens_invalidos": [                    # medições descartadas de um registro que segue válido
        {"campo": "ph", "motivo": "fora da faixa 0–14", "valor": 17.0},
        {"campo": "umidade", "motivo": "medição nula", "valor": None},
    ],
    "motivos": ["campo vital nulo"],        # por que valido=False (vazio se válido)
    "registro": {...},                      # registro normalizado só com os itens válidos
}
```

Regras:

- `valido=True` exige todos os campos vitais presentes e ao menos um item válido; os itens inválidos não invalidam o registro, só saem de `registro["itens"]`.
- `campos_nulos` lista **todos** os campos ausentes ou nulos de uma vez, não só o primeiro.
- Dados pessoais aparecem só pelo **nome** do campo; o `valor` de campo pessoal nunca é preenchido.

Quem usa o resultado:

| Consumidor | Uso |
|---|---|
| Log (`src/logger.py`) | Uma única função percorre os resultados e grava no `rejeitados_*.log`: uma linha por registro inválido (com todos os `campos_nulos`) e uma por item inválido. Assim o formato do log fica igual para todas as regras. |
| Data Lake | Não será implementado neste projeto (decisão de 06/10/2026). |
| Entidades (banco) | A persistência (fase 8) recebe só `registro` dos resultados com `valido=True`. |
| Resumo | Recebidos = válidos + inválidos; itens gravados e itens rejeitados saem dos mesmos resultados. |

As rejeições que acontecem **antes** da validação, na normalização (valor que não pode ser convertido, fase 4), já são registradas no log pela própria normalização. Esses registros não chegam à validação, e o resumo da execução soma as duas origens.

Ponto de atenção: pelo enunciado (3.4), **outlier estatístico não é descartado**, só sinalizado. Só o valor fisicamente impossível (fora de `valor_minimo/maximo`) é rejeitado na ingestão.

---

## 5. Idempotência

### No banco

| Tabela | Estratégia | Chave usada |
|---|---|---|
| `Estados` | Carga inicial pelo DML (`MERGE` ou `IF NOT EXISTS`) | `sigla` |
| `Municipios` | Upsert (`MERGE`) | `(nome, estado_id)` |
| `Estacoes` | Upsert (`MERGE`, atualiza nome e coordenadas) | `codigo_estacao` |
| `Operadores` | Upsert (`MERGE`, atualiza hashes, e-mail criptografado e município) | `codigo_operador`. O e-mail criptografado muda a cada execução (Fernet não é determinístico), mas a contagem de linhas não. |
| `Parametros` | Inserir se não existir | `codigo_parametro` |
| `Leituras` + `Leitura_Itens` | **Substituição da partição**: dentro de uma transação, apagar os itens e cabeçalhos das estações do lote nos dias presentes no lote e regravar | partição = (`estacao_id`, `CAST(data_hora AS DATE)`) + chave natural da leitura (D1) |

A substituição por partição atende o "sobrescrever a partição afetada" do enunciado e também resolve um registro que foi corrigido ou removido na origem, coisa que um upsert puro não resolve. Tudo roda numa única transação (`DatabaseConnection.transaction()`): se falhar, nada do lote fica gravado.

O `transform.py` do exemplo usa outro mecanismo, uma marca `status_pipeline = 'CONCLUIDO'` no DataFrame para não reprocessar. Aqui ele não basta sozinho, porque o enunciado exige que o backfill **regrave** a partição, e não que a pule. A marca pode ser usada como complemento no log de resumo.

### No Data Lake

O Data Lake não será implementado neste projeto (decisão de 06/10/2026).

### Critério de aceite

Executar o pipeline duas vezes com o mesmo dataset deve deixar **exatamente as mesmas contagens** em todas as tabelas e nenhum `GROUP BY ... HAVING COUNT(*) > 1` nas chaves naturais.

---

## 6. Logs (módulo central `src/logger.py`)

O log é configurado em **um único módulo**, `src/logger.py`, seguindo `avanade-ds-ia/modulo-1/projeto-pratico/src/transform.py` e `avanade-ds-ia/modulo-2/ED_PYTHON/01_ingestao_api.py`. A estrutura do módulo e as regras de dados pessoais em log estão em [seguranca-lgpd.md](seguranca-lgpd.md). Aqui fica o que é específico desta implementação:

- `configurar_logs(etapa)` chamado **uma vez** no início da execução, com `logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s', handlers=[...])` (formato do `transform.py`);
- dois loggers nomeados: `DataScienceIA_Logger` (execução) e `DataScienceIA_Rejeitados` (o que não foi importado);
- os demais módulos só obtêm o logger com `logging.getLogger(...)`: nenhum chama `basicConfig` nem `print` (o enunciado, item 3.7, também exige isso);
- uma única função `registrar_rejeicao(etapa, nivel, campo, motivo, registro=None, valor=None, severidade=WARNING)` monta a linha de rejeitado, para que o formato seja igual em todas as etapas; o valor de campos pessoais é sempre omitido;
- o logger de rejeitados escreve **só no próprio arquivo** (sem console), porque um lote gera milhares de linhas; o total vai para o resumo via `contar_rejeicoes()` e `registrar_resumo(...)`;
- `INFO` para progresso, `WARNING` para dado tratado ou descartado, `ERROR` para falha de etapa, `CRITICAL` para falha de conexão.

Além do console, dois arquivos em `logs/` (fora do Git):

| Arquivo | Logger | Conteúdo |
|---|---|---|
| `logs/pipeline_AAAAMMDD_HHMMSS.log` | `DataScienceIA_Logger` | Execução completa (mesmo formato do console) |
| `logs/rejeitados_AAAAMMDD_HHMMSS.log` | `DataScienceIA_Rejeitados` | **Tudo o que não foi importado**, uma linha por ocorrência |

Cada execução cria o seu par de arquivos, com a data/hora de início no nome. As primeiras linhas de cada arquivo são um **cabeçalho** (`INFO`, marcado com `[cabeçalho]`, só no arquivo) que diz qual etapa o criou, por quê e o que ele contém. As etapas estão em `ETAPAS` no `src/logger.py`: `ingestao` (`--ingestao`), `analise` (`--analise`), `consulta` (CLI) e `coleta` (`importar_dados` avulso). Nas três últimas, que não importam dados, o arquivo de rejeitados tem só o cabeçalho, e é ele que explica por que o arquivo está vazio:

```text
2026-10-06 16:18:00,698 - [INFO] - [cabeçalho] Etapa: Ingestão (python main.py --ingestao).
2026-10-06 16:18:00,698 - [INFO] - [cabeçalho] Por que existe: cada execução cria um par de arquivos (pipeline e rejeitados) com a data/hora de início no nome; esta execução coleta o lote na API, normaliza, anonimiza, valida e grava no banco 3FN.
2026-10-06 16:18:00,698 - [INFO] - [cabeçalho] Conteúdo: uma linha por leitura recusada (nivel=leitura) ou medição descartada (nivel=item), com etapa, campo e motivo; valores pessoais nunca aparecem.
```

Formato de cada linha de rejeitado:

```text
2026-10-05 10:15:02,431 - [WARNING] - etapa=completude nivel=leitura registro=REG-RJ-001-00042 campo=operador_codigo motivo="campo vital nulo"
2026-10-05 10:15:02,433 - [WARNING] - etapa=completude nivel=item registro=REG-RJ-001-00043 campo=ph motivo="medição nula"
2026-10-05 10:15:02,440 - [WARNING] - etapa=acuracia nivel=item registro=REG-RJ-001-00051 campo=ph valor=17.0 motivo="fora da faixa 0–14"
2026-10-05 10:15:03,002 - [ERROR] - etapa=parametro nivel=parametro campo=salinidade motivo="unidade de medida ausente"
```

Como a anonimização e a minimização acontecem antes da validação, o registro rejeitado já não carrega nome, CPF nem e-mail em claro, e o campo nulo de operador é identificado só pelo nome do campo. Ao final, uma linha `INFO` traz o resumo: recebidos, importados, leituras rejeitadas, itens rejeitados e parâmetros novos.

---

## 7. Impacto por módulo

| Arquivo | O que muda |
|---|---|
| [main.py](../main.py) | Chamada `criar_tabelas()` removida; `iniciar_aplicacao()` chama `configurar_logs()` uma vez; `print` trocado por log (fases 2 e 3). Na fase 8, `run_pipeline()` passou a fazer só a ingestão (com resumo), a análise foi para `gerar_relatorio()` e foi criado o comando `python main.py --ingestao`. Na fase 15, `gerar_relatorio()` passou a analisar o modelo 3FN e foi criado `--analise` (com `--estacao`, `--inicio`, `--fim`, via `argparse`). |
| `src/ingestion/bronze_writer.py` | Criado na fase 8 e **removido em 05/10/2026**: o Data Lake não será implementado neste projeto (decisão de 06/10/2026). |
| `src/services/parametro_service.py` (novo, fase 7) | `sincronizar()`: cadastra parâmetros novos sem faixa e rejeita, com ERROR, os que não podem ser usados; `faixas()` para a validação. |
| `src/logger.py` (novo) | Configuração única de log: `configurar_logs(etapa)` (com cabeçalho por arquivo desde 06/10/2026), loggers `DataScienceIA_Logger` e `DataScienceIA_Rejeitados`, `registrar_rejeicao(...)`. Fase 9: pasta trocável por `PASTA_LOGS`. Fase 15: `registrar_anomalias()` (uma linha `WARNING` por anomalia da análise). |
| `src/security.py` (novo) | Único ponto de anonimização e criptografia: `anonimizar_cpf`, `anonimizar_nome`, `criptografar_email`, `descriptografar_email` ([seguranca-lgpd.md](seguranca-lgpd.md)). |
| [src/config.py](../src/config.py) | Ler `CHAVE_CRIPTOGRAFIA` (e `CHAVE_HASH`, se D8 aprovada) e falhar se ausente, sem expor o valor. |
| [.env.example](../.env.example) | Incluir `CHAVE_CRIPTOGRAFIA` e `CHAVE_HASH` (só os nomes). `MOCK_API` foi renomeada para `FONTE_DADOS` (D3). |
| `src/database/criar_tabelas.py` | **Removido** (criava o modelo antigo). O schema vem do DDL e das migrations. |
| `sql/migrations/` (novo) | Uma migration idempotente `VNNN__descricao.sql` por mudança de estrutura; o DDL é atualizado na mesma entrega. Aplicadas: `V001__leituras_codigo_registro.sql` (D1) e `V002__operadores_email_criptografado.sql` (D7). |
| [src/database/connection.py](../src/database/connection.py) | `insert_em_lotes()` (fase 8): `INSERT` de várias linhas por comando, respeitando o limite de parâmetros do SQL Server. |
| [src/ingestion/data_client.py](../src/ingestion/data_client.py) | **Fase 18:** tratamento de queda de conexão, resposta vazia e rate limit, com logs (padrão de `extrair_dados_api`). |
| [src/ingestion/importar_dados.py](../src/ingestion/importar_dados.py) | **Reescrito na fase 8:** `importar_municipios`, `importar_operadores`, `importar_estacoes` e `importar_leituras`, cada uma idempotente e devolvendo o mapa chave → id. Plano original: reescrita para a nova ordem: Estados (busca) → Municípios → Operadores → Estações → Parâmetros → Leituras/Itens (por partição). Os caches `__cidades`, `__operadores` e `__estacoes` passam a ser municípios, operadores, estações e parâmetros. |
| [src/services/normalization_service.py](../src/services/normalization_service.py) | **Reescrito na fase 4:** payload novo, cabeçalho + itens, descoberta de parâmetros, anonimização e minimização, rejeição por item ou leitura sem derrubar o lote. |
| [src/services/validation_service.py](../src/services/validation_service.py) | **Reescrito nas fases 5 e 6:** um resultado por registro (`valido`, `campos_nulos`, `itens_invalidos`, `motivos`, `registro`; contrato na seção 4), sem abortar o lote. Faixas, siglas e parâmetros aceitos recebidos no construtor; a `run_pipeline()` os lê do banco desde a fase 7. |
| [src/models/](../src/models/) | **Fase 8:** `MunicipioModel` e `LeituraItemModel` novos; `EstacaoModel`, `OperadorModel` e `LeituraModel` no formato do DDL; `CidadeModel` removido na fase 13. Plano original: `CidadeModel` → `MunicipioModel`; `EstadoModel` já existe; `ParametroModel` criado na fase 7; novo `LeituraItemModel`; `LeituraModel` vira cabeçalho (`operador_id`, `estacao_id`, `data_hora`, `fonte`); `OperadorModel` e `EstacaoModel` seguem as colunas do DDL. |
| [src/repository/](../src/repository/) | **Fase 8:** `MunicipioRepository` novo; `OperadorRepository` reescrito (`MERGE`); `EstacaoRepository.merge_many`; `LeituraRepository.substituir_leituras` e `save_readings` novos; métodos com f-string e consultas quebradas removidos; **Fase 13:** `CidadeRepository` e as consultas legadas removidos; `LeituraRepository.get_medicoes()`, `MunicipioRepository.get_com_estacoes()`, `EstacaoRepository.get_by_municipio()` e `get_by_codigo()` novos. Plano original: `CidadeRepository` → `MunicipioRepository`; `EstadoRepository` já existe; `ParametroRepository` criado na fase 7; novo repositório de itens de leitura; todos os `create_many` passam a ser idempotentes (`MERGE`/partição). Há métodos com SQL montado por f-string (`create` em `leitura_repository.py` e `operador_repository.py`) que precisam sair. |
| [src/services/analytics_service.py](../src/services/analytics_service.py), [src/cli/](../src/cli/), [src/services/report_service.py](../src/services/report_service.py) | **Reescritos nas fases 14 a 16** sobre `Leitura_Itens` + `Parametros`: análise por estação + parâmetro (sem pivotar: uma linha por medição), anomalias por IQR ou Z-Score com indicador de alerta, relatório com CSV e CLI município → estação → período ([analise-estatistica.md](analise-estatistica.md)). |
| [requirements.txt](../requirements.txt) | Adicionar `cryptography` (Fernet). O `src/cli` também usa `rich`, que não está listado. |
| [sql/dml_populacao.sql](../sql/dml_populacao.sql) | Carga inicial: 27 estados e os 11 parâmetros conhecidos, com faixas. |
| [.gitignore](../.gitignore) | Adicionar `logs/` e os arquivos de dados de `data_lake/` (mantendo os `.gitkeep`), porque a Bronze guarda dado pessoal em claro. |

---

## 8. Impacto nos testes

- `tests/integration/conftest.py` monta o banco de teste com o DDL + migrations + DML. `test_persistencia.py` e `test_pipeline_e2e.py` foram reescritos para o modelo 3FN na fase 10.
- `test_normalization_service.py` (fase 4), `test_validation_service.py` (fases 5 e 6) e `tests/test_quality_stat.py` usam o payload novo. A fixture `registro_legado` (formato antigo) foi removida na fase 10.
- `test_analytics_service.py` e `test_report_service.py` dependem das colunas largas.
- Novo `tests/test_quality_stat.py`: completude, acurácia, descoberta de parâmetros, idempotência (rodar duas vezes e conferir contagens) e conteúdo do log de rejeitados.
- Novos testes de `src/security.py` (hash determinístico com 64 caracteres, `None` para vazio, ida e volta da criptografia do e-mail) e de `src/logger.py` (formato da linha e ausência de dado pessoal no arquivo de rejeitados).

---

## 9. Impacto na documentação

Atualizar junto com cada fase (regras 9 a 11 do COPILOT.md):

| Documento | Ajuste |
|---|---|
| [modelagem-banco.md](modelagem-banco.md) | Ainda descreve `Cidades` e a `Leituras` larga. Reescrever para o modelo 3FN (já vigente no banco). |
| [contrato-dados.md](contrato-dados.md), [dicionario-dados.md](dicionario-dados.md) | Payload novo, regra de parâmetros, campos obrigatórios e opcionais. |
| [manual-execucao.md](manual-execucao.md) | A seção "4. Criar banco e tabelas" passa a ser: executar o DDL e depois o DML. |
| [diagramas/diagrama-sequencia.md](diagramas/diagrama-sequencia.md), [diagramas/diagrama-atividade.md](diagramas/diagrama-atividade.md), [arquitetura.md](arquitetura.md) | Nova ordem de persistência, log de rejeitados, sem criação de tabelas. |
| [seguranca-lgpd.md](seguranca-lgpd.md) | **Atualizado em 05/10/2026** como referência central de anonimização (`src/security.py`) e log (`src/logger.py`). Revisar ao implementar as fases 2 e 4. |
| [plano-testes.md](plano-testes.md) | Novos cenários de idempotência e nulos. |
| [README.md](../README.md) | Resumo do novo fluxo e da pasta `logs/`. |

---

## 10. Decisões pendentes

Precisam de resposta antes da fase correspondente do TODO.

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| D1 | Chave natural de `Leituras` (o DDL não tem nenhuma) | (a) nova coluna `codigo_registro VARCHAR(50) NOT NULL` + `UNIQUE`; (b) `UNIQUE (estacao_id, data_hora)` | **Aprovada (a) em 05/10/2026; migration V001.** é o identificador do enunciado ("Identificador do Pedido/Leitura") e vem pronto no payload. Exige alterar o DDL e o banco. |
| D2 | Leitura com estação mas **sem operador** (32 registros) | (a) rejeitar; (b) `operador_id` passa a aceitar `NULL`; (c) operador "NÃO INFORMADO" | **Aprovada (a) em 06/10/2026**: mantém o DDL; os 32 vão para o log de rejeitados. |
| D3 | `Leituras.fonte` é `NOT NULL` e o payload não traz fonte | (a) constante, ex.: `API_MOCK`; (b) URL da API; (c) campo no `.env` | **Definida em 05/10/2026: uma variável só, `FONTE_DADOS`, com a URL da API.** Ela substitui a antiga `MOCK_API`: é usada na coleta e gravada em `Leituras.fonte` (máximo de 100 caracteres, conferido no `load_config()`). |
| D4 | `ValidationService.validate_data` aborta o lote inteiro | Alterar para rejeição por registro e por item | **Aprovada em 05/10/2026**: o CLAUDE.md passou a permitir alteração de lógica na Parte 2. Necessária para "salvar log de tudo que não foi importado". |
| D5 | Campos do payload sem coluna no DDL: `cidade_codigo`, `estacao_ativa`, `estacao_tipo`, `operador_ativo`, `<param>_codigo`, `data_hora_leitura_<param>` | (a) descartar; (b) adicionar colunas | **Aprovada (a) em 06/10/2026**: listados uma vez por lote em `INFO`, sem gravar. |
| D6 | Faixas de `valor_minimo`/`valor_maximo` dos 11 parâmetros | Proposta no TODO (fase 3) | **Aprovada em 06/10/2026 a proposta aplicada no `dml_populacao.sql`.** pH 0–14 e umidade 0–100 vêm do enunciado e do código atual. Para mudar, basta editar o DML e reexecutá-lo (`MERGE` atualiza as faixas). |
| D7 | Onde gravar o e-mail criptografado: `email_hash VARCHAR(64)` não comporta um token Fernet (cerca de 140 caracteres para um e-mail comum) | (a) trocar `email_hash` por `email_criptografado VARCHAR(255) NULL`; (b) manter `email_hash` e adicionar `email_criptografado`; (c) só hash, sem recuperação | **Aprovada (a) em 05/10/2026; migration V002.** segue o exemplo `security.py` e o item 3.2 do enunciado (reversível para dado que exige recuperação). Exige alterar o DDL e o banco, junto com a D1. |
| D9 | Indicador de alerta de qualidade das leituras anômalas (PDF 3.4) | (a) só no resultado da análise, no relatório/CSV e em WARNING no log; (b) coluna `alerta_qualidade` em `Leitura_Itens`, atualizada pela análise (migration) | **Aprovada (a) em 06/10/2026.** O outlier depende do recorte analisado (estação, período); gravado no banco ficaria desatualizado a cada carga. A Gold, onde caberia, não será implementada. |
| D10 | Regra do Z-Score | (a) anômala se fora do IQR **ou** com \|Z\| > 3, indicador informando o(s) método(s) (`IQR`, `ZSCORE`, `IQR+ZSCORE`); (b) anômala só se fora do IQR **e** \|Z\| > 3 (Z-Score confirma o IQR); (c) limite \|Z\| > 2 | **Aprovada (a) em 06/10/2026**, com \|Z\| > 3: mostra o resultado de cada método sem esconder nenhum; o indicador diz qual sinalizou. |
| D12 | Precipitação com IQR = 0 (maioria 0 mm): toda chuva acima de zero vira anomalia `IQR` (1.210 dos 1.824 alertas) | (a) manter a regra e documentar; (b) IQR só sobre os valores positivos quando IQR = 0; (c) só Z-Score quando IQR = 0 | **Aprovada (a) em 06/10/2026**: mesma regra para todos os parâmetros; a limitação fica documentada em `analise-estatistica.md`. |
| D11 | Agrupamento dos parâmetros na CLI (`Parametros` não tem grupo) | (a) mostrar todos os parâmetros da estação juntos (sem o menu de tipo); (b) grupo fixo no código por código de parâmetro; (c) coluna `grupo` em `Parametros` (migration + DML) | **Aprovada (a) em 06/10/2026**: não exige schema nem lista fixa e funciona para parâmetros novos. |
| D8 | Hash de CPF e nome com chave secreta | (a) SHA-256 puro, como no exemplo; (b) SHA-256 de `CHAVE_HASH` + valor | **Implementada configurável na fase 2** (`CHAVE_HASH` preenchida = HMAC-SHA256). Recomendação mantida: (b). o CPF tem só 10¹¹ combinações e o SHA-256 puro pode ser revertido por força bruta. Mantém os 64 caracteres. |

---

## 11. Relatório das fases

Cada fase do [TODO](todo-idempotencia.md) registra aqui: alterações realizadas, arquivos envolvidos, decisões relevantes e validações executadas.

### Fase 0 — Validação do banco contra o DDL

- **Status:** concluída em 05/10/2026.
- **Alterações:** nenhuma no banco; somente leitura.
- **Validação:** comparação de tabelas, colunas, constraints e índices (seção 1). Banco idêntico ao DDL e vazio.

### Fase 1 — Decisões

- **Status:** concluída em 05/10/2026.
- **Decisões:**
  - D1 = (a) `codigo_registro`;
  - D2 = rejeitar e logar;
  - D3 = `FONTE_DADOS` no `.env`, com a URL da API, que substitui `MOCK_API` e é gravada em `Leituras.fonte`;
  - D4 = aprovada;
  - D5 = descartar;
  - D6 = proposta aplicada no DML (aprovada pelo time em 06/10/2026);
  - D7 = (a) `email_criptografado`;
  - D8 = configurável.
- **Alterações no banco:** migrations `V001` e `V002` criadas, `ddl_banco_relacional.sql` atualizado para o estado final, as duas aplicadas no banco `impacta` (com `Leituras` e `Operadores` vazias; cada uma executada duas vezes) e Fase 0 repetida. O banco ficou igual ao DDL. A coluna `email_criptografado` foi posta no fim de `Operadores` também no DDL, para que um banco criado do zero tenha a mesma ordem do banco migrado.

### Fase 2 — Módulos centrais de log e segurança

- **Status:** concluída em 05/10/2026. Ficam para a fase 8 a chamada do resumo com as contagens reais e, para a fase 9, as conferências com carga real.
- **Alterações:**
  - `src/logger.py` (novo): `configurar_logs()`, loggers `DataScienceIA_Logger` e `DataScienceIA_Rejeitados`, `registrar_rejeicao()`, `contar_rejeicoes()`, `registrar_resumo()`.
  - `src/security.py` (novo): `configurar_seguranca()`, `anonimizar_cpf()`, `anonimizar_nome()`, `criptografar_email()`, `descriptografar_email()`.
  - `src/config.py`: `Settings` ganhou `chave_criptografia` e `chave_hash`; `CHAVE_CRIPTOGRAFIA` passou a ser obrigatória. Depois, `mock_api` foi substituído por `fonte_dados` (ver D3).
  - `main.py`: nova `iniciar_aplicacao()` (logs → configuração → segurança), chamada antes da CLI; `print` trocado por `logger`.
  - `src/ingestion/importar_dados.py`: `print` do bloco `__main__` trocado por log.
  - `requirements.txt`: `cryptography` e `rich` (a CLI já usava `rich`, mas ele não estava listado e os testes nem chegavam a rodar).
  - `.env.example`, `.gitignore` (`logs/` e dados de `data_lake/`), `docs/seguranca-lgpd.md`, `docs/manual-execucao.md`.
- **Decisões:**
  - A D8 ficou configurável: `CHAVE_HASH` preenchida usa HMAC-SHA256, vazia usa SHA-256 puro.
  - O CPF é anonimizado só com os dígitos, e o nome sem espaços extras e sem diferença de maiúsculas, para que a mesma pessoa gere sempre o mesmo hash.
  - Rejeitados só em arquivo, sem console.
  - O formato de log é o do `transform.py` (`' - '` entre as partes).
  - A pasta do Data Lake é `data_lake/`, como o time renomeou no commit `875a1eb`; a documentação foi ajustada.
- **Validações:**
  - Antes da fase, a suíte nem rodava (faltava `rich`). Depois de instalar, ficou em 57 testes passando e 1 falhando: a CLI tentava acessar o banco antes de validar a configuração.
  - Depois da fase: **96 passaram e 7 foram pulados** (integração, sem banco de teste).
  - Novos testes: `tests/unit/test_security.py`, `tests/unit/test_logger.py`, dois casos novos de inicialização em `test_main.py` e dois em `test_config.py`.
  - Confirmado com `git check-ignore` que os arquivos de dados em `data_lake/` são ignorados e os `.gitkeep`, não.

### Fase 3 — Schema fora do pipeline e carga inicial (DML)

- **Status:** concluída em 05/10/2026.
- **Alterações:**
  - `src/database/criar_tabelas.py` removido, a pedido do time; a chamada e o import saíram de `main.py`.
  - `sql/migrations/` criada (com `.gitkeep`) e regra de evolução do schema documentada na seção 4 de `manual-execucao.md` e na regra 4 do `CLAUDE.md`: o DDL fica sempre no estado final e cada mudança gera uma migration idempotente.
  - `sql/ddl_banco_relacional.sql`: só a ordem dos `DROP` mudou (`Leitura_Itens` → `Leituras` → `Parametros` → `Estacoes` → `Operadores` → `Municipios` → `Estados` → `Cidades` antiga). Antes, o script apagava `Leituras` primeiro e falhava ao ser reexecutado sobre o banco atual, por causa da FK de `Leitura_Itens`. Nenhuma tabela, coluna ou constraint mudou.
  - `tests/unit/test_main.py`: sem a etapa `schema` na ordem esperada de `run_pipeline()`.
  - `tests/integration/conftest.py`: monta o banco aplicando o DDL (separado nos lotes `GO`) e depois as migrations `V*.sql` em ordem; a limpeza entre testes segue as 7 tabelas novas.
  - `tests/integration/test_persistencia.py` e `test_pipeline_e2e.py`: pulados com motivo explícito até a reescrita (fases 8 e 10).
  - `sql/dml_populacao.sql`: carga idempotente com `MERGE` de 27 estados (chave `sigla`) e 11 parâmetros (chave `codigo_parametro` = `*_tipo_codigo` do payload), com nome legível, unidade igual à do payload e faixas da D6 (proposta). Reexecutar atualiza nome, unidade e faixa.
  - `tests/integration/conftest.py`: aplica o DML ao criar o banco e reaplica a cada teste, depois de esvaziar as tabelas.
  - `tests/unit/test_sql_scripts.py` (novo): DML coerente com o dataset e ordem dos `DROP` do DDL.
  - Documentação: `manual-execucao.md` (seção 4, com `sqlcmd -f 65001`), `plano-testes.md`, `arquitetura.md`, `modelagem-banco.md`, `diagrama-sequencia.md`, `README.md`.
- **Validações:**
  - `pytest`: **103 passaram e 7 foram pulados**, com o motivo do skip na saída (`-rs`).
  - DML executado duas vezes no banco `impacta` dentro de uma transação e desfeito com `ROLLBACK`: 27 estados e 11 parâmetros nas duas execuções, acentos e símbolos (`°`, `µ`, `²`) gravados corretamente, banco vazio de novo após o rollback.
  - DML aplicado no banco `impacta` com autorização do time (commit): `Estados` = 27 e `Parametros` = 11; `Municipios`, `Estacoes`, `Operadores`, `Leituras` e `Leitura_Itens` continuam vazias. Acentos e unidades (`°C`, `µS/cm`, `W/m²`) conferidos após a gravação.
  - O DDL é separado em 9 lotes pelo `conftest` de integração.
  - Ainda não houve execução contra um banco de teste (`TEST_SQL_MASTER_CONNECTIONSTRING` não configurada nesta máquina).

### Fase 4 — Normalização e anonimização do payload novo

- **Status:** concluída em 05/10/2026.
- **Alterações:**
  - `src/services/normalization_service.py` reescrito: formato de saída na seção 3; `descobrir_parametros()` para a fase 7; usa `src/security.py` e `src/logger.py`. O antigo `__normalize_bool` saiu: `estacao_ativa` e `operador_ativo` são descartados (D5).
  - `tests/conftest.py`:
    - `registro_bruto` passa a ser o 1º registro real do `data_set.json`;
    - novas fixtures `dataset`, `seguranca` e `logs_temporarios`;
    - `registro_legado` (formato antigo, literal) atende os testes do `ValidationService` até as fases 5 e 6.
  - `tests/unit/test_normalization_service.py` reescrito (21 testes, incluindo o aceite com o dataset completo); `test_validation_service.py` e `integration/test_persistencia.py` passam a usar `registro_legado`.
  - `tests/unit/test_sql_scripts.py`: a conferência dos parâmetros percorre todos os registros do dataset, não só o primeiro.
- **Decisões:**
  - Os nomes do cabeçalho seguem os do payload (`estacao_codigo`, `cidade_estado`...), para o log de rejeitados apontar o campo de origem.
  - A medição nula continua como item com `valor=None`; quem a rejeita é a completude (fase 5), e não a normalização.
  - `data_hora_leitura_<param>` é guardada no item, mas não é persistida (D5).
  - Parâmetro novo sem unidade fica com `unidade_medida=None`; a decisão de cadastrar ou não é da fase 7.
- **Validações:**
  - `pytest`: **115 passaram e 7 foram pulados**.
  - O dataset completo foi normalizado com zero rejeições, 11 parâmetros e datas em ordem.
  - Os campos descartados aparecem no log em INFO, só pelo nome.
- **Pendência conhecida:** entre as fases 4 e 6, a `run_pipeline()` não funciona de ponta a ponta, porque a validação ainda espera o formato antigo. O `main.py` não a chama neste período.

### Fase 5 — Campos nulos (completude)

- **Status:** concluída em 05/10/2026, junto com a fase 6 (mesma função). O destino no Data Lake fica para a fase 8.
- **Alterações:**
  - `src/services/validation_service.py` reescrito com o contrato da seção 4:
    - `CAMPOS_VITAIS` com os 12 campos do cabeçalho;
    - todos os nulos reunidos em `campos_nulos` e num só motivo `completude`;
    - medição nula vai para `itens_invalidos`;
    - leitura sem medições válidas é inválida;
    - `registros_validos()` para a persistência.
  - `src/logger.py`: `registrar_resultados_validacao(resultados)` grava as linhas de rejeitados a partir dos resultados e devolve as contagens. As medições de um registro inválido não são listadas, porque ele não é gravado.
  - `main.py`: `run_pipeline()` valida, registra o log pelos resultados e envia só `registros_validos()` à persistência.
  - `validar_estacao()` e `validar_leitura()` removidos (usavam os modelos antigos).
- **Decisões:**
  - A validação não consulta o banco: faixas e siglas chegam pelo construtor, o que deixa a regra testável sem banco.
  - Os erros de conversão da normalização (fase 4) continuam sendo logados pela própria normalização (recomendação aceita pelo time).
- **Validações:** ver fase 6.

### Fase 6 — Acurácia e validação por registro

- **Status:** concluída em 05/10/2026. A leitura das faixas e das siglas no banco fica para a fase 8.
- **Alterações:**
  - Regras de acurácia: faixa por `codigo_parametro`, com `None` = sem limite e limites inclusivos; latitude e longitude invalidam a leitura.
  - Regras de referência e validade: estado não cadastrado e sigla fora do formato.
  - Regras de unicidade: `registro_codigo` repetido (fica o primeiro); `estacao_codigo` ou `operador_codigo` com dados cadastrais diferentes. O e-mail criptografado fica fora da comparação, porque o token muda a cada execução.
  - `tests/unit/test_validation_service.py` reescrito (27 casos) e `tests/unit/test_logger.py` com o teste de `registrar_resultados_validacao`.
  - `tests/test_quality_stat.py` com o aceite das fases 5 e 6 usando o dataset completo e as faixas do `dml_populacao.sql`.
  - `tests/unit/test_main.py` com o resultado da validação no formato novo.
- **Validações:**
  - **Conferência independente:** um cálculo feito direto sobre o JSON bruto, sem usar o `ValidationService`, deu os mesmos números:
    - **82** registros inválidos (50 sem estação nem operador; 32 só sem operador) e **9.806** válidos;
    - **2.681** medições nulas e **603** fora da faixa nos registros válidos.
  - Log de rejeitados com 3.366 linhas de rejeição (sem contar o cabeçalho, acrescentado depois) e sem CPF nem e-mail.
  - `pytest`: **136 passaram e 7 foram pulados**.
- **Correção de um número da análise:** o pH fora de 0–14 nos registros **válidos** é 72, e não 73. A 73ª ocorrência está num registro já rejeitado por completude.

### Fase 7 — Cadastro automático de parâmetros

- **Status:** concluída em 05/10/2026.
- **Alterações:**
  - `src/models/parametro_model.py` e `src/repository/parametro_repository.py` (novos). O `create_many` usa `INSERT ... WHERE NOT EXISTS`, então não duplica. `EstadoModel`, `ParametroModel`, `EstadoRepository` e `ParametroRepository` passaram a ser exportados nos `__init__.py`.
  - `src/services/parametro_service.py` (novo): `sincronizar()`, `nome_legivel()` e `faixas()`.
  - `src/services/validation_service.py`: novo argumento `parametros_validos`; a medição de um código fora dele vira item inválido com `etapa=parametro`.
  - `main.py`: a `run_pipeline()` abre a conexão antes da validação, sincroniza os parâmetros, lê as siglas de `Estados` e passa faixas, siglas e parâmetros aceitos ao `ValidationService`. Isso fecha a pendência da fase 6.
  - Testes: `tests/unit/test_parametro_service.py` (novo, com repositório em memória) e `tests/unit/test_main.py` (as duas etapas novas na ordem do pipeline e na propagação de erro).
- **Decisões:**
  - **Unidade diferente da cadastrada rejeita o parâmetro no lote** (ERROR), em vez de só avisar: gravar °F numa série em °C distorce médias e outliers sem ninguém perceber. A comparação ignora maiúsculas (`pH` = `PH`).
  - O nome inicial do parâmetro novo vem do campo do payload; o time pode trocá-lo, e definir a faixa, editando o `dml_populacao.sql` e reexecutando-o.
  - O cadastro do parâmetro novo acontece fora da transação da carga das leituras: se a carga falhar depois, o parâmetro continua cadastrado. Como é um dado de domínio e o cadastro não duplica, isso não gera inconsistência.
- **Validações:**
  - `pytest`: **150 passaram e 7 foram pulados**.
  - Contra o banco `impacta`, com o dataset atual:
    - nenhum parâmetro inserido (11 antes e 11 depois) e os 11 aceitos;
    - 27 siglas lidas de `Estados`;
    - a validação com faixas e siglas do banco deu os mesmos números das fases 5 e 6 (9.806 válidos, 82 inválidos, 2.681 nulos, 603 fora da faixa).

### Fase 8 — Persistência idempotente

- **Status:** concluída em 05/10/2026. A adaptação da análise e da CLI ao modelo 3FN fica para a fase de analytics.
- **Alterações:**
  - Modelos no formato do DDL: `MunicipioModel` e `LeituraItemModel` novos; `EstacaoModel`, `OperadorModel` e `LeituraModel` reescritos.
  - Repositórios:
    - `MunicipioRepository` novo e `OperadorRepository` reescrito, ambos com `MERGE`;
    - `EstacaoRepository.merge_many`;
    - `LeituraRepository.substituir_leituras` e `save_readings(registros, parametros, fonte)`;
    - removidos os métodos com SQL em f-string e as consultas quebradas (`get_by_id` e `get_by_name`, que consultavam `operadores`).
  - `DatabaseConnection.insert_em_lotes()`.
  - `src/ingestion/importar_dados.py` reescrito: uma função por entidade, com os mapas como retorno em vez de caches globais.
  - `src/ingestion/bronze_writer.py` (novo).
  - `main.py`:
    - `run_pipeline()` faz só a ingestão e devolve o resumo, que também vai para o log com `registrar_resumo`;
    - `gerar_relatorio()` guarda a análise legada;
    - `python main.py --ingestao` executa a carga.
  - Testes: `test_bronze_writer.py` (novo); `test_metodos_ponte.py` e `test_main.py` adaptados, incluindo "a Bronze não é gravada se o banco falhar".
- **Decisões:**
  - A substituição de partição usa tabelas temporárias e operações de conjunto: um `DELETE` e um `INSERT` para mais de 100 mil itens, em vez de uma ida ao Azure por linha. Além da partição (estação + dia), também apaga a leitura que já tinha o mesmo `codigo_registro` em outro dia, para a `UNIQUE` nunca derrubar a carga.
  - Uma partição em que **todos** os registros do lote são inválidos não é tocada: as leituras antigas dela permanecem.
  - A Bronze guarda só os aprovados (PDF 3.1) e é gravada depois do commit, então o lake não fica à frente do banco. Isso corrige a seção 4, que dizia "bruto do lote inteiro".
  - A análise legada consulta tabelas que não existem mais e quebraria a carga logo depois de gravar. Por isso saiu do `run_pipeline()`. `CidadeRepository` e as consultas antigas continuam no código só para a CLI importar sem erro.
  - O e-mail criptografado é regravado a cada carga, porque o token Fernet muda; a contagem de operadores não muda.
- **Validações:**
  - `pytest`: **159 passaram e 7 foram pulados**.
  - **Banco `impacta`, dataset completo, duas cargas na mesma transação, desfeitas com rollback ao final:**
    - 1ª carga: 9.806 leituras e 104.582 itens, em cerca de 19 s;
    - 2ª carga: 9.806 removidas e regravadas, com as mesmas contagens, em cerca de 29 s;
    - zero duplicidades, leituras sem item, itens fora da faixa ou e-mails em claro;
    - todas as tabelas voltaram a zero depois do rollback.
  - Bronze com o dataset real: 206 partições e 9.806 registros (26 MB). Depois de duas execuções, continuam 9.806. `data_lake/bronze/dt=*/leituras.json` é ignorado pelo Git.
- **Atualização (05/10/2026):** a Bronze (`bronze_writer.py`, `test_bronze_writer.py` e a chamada em `run_pipeline()`) foi removida a pedido do time, porque o Data Lake é tratado em outra frente. A ingestão grava só no banco. Os itens de Bronze acima ficam como histórico. Testes: **152 passaram e 7 foram pulados**.
- **Nada foi gravado de forma definitiva** em `Municipios`, `Operadores`, `Estacoes`, `Leituras` ou `Leitura_Itens`: a primeira carga real é o passo da fase 9.

### Fase 9 — Validação do banco após a carga

- **Status:** concluída em 06/10/2026, no banco de teste e no banco `impacta`.
- **Carga real** (depois da liberação do IP no firewall do Azure SQL; API local em `FONTE_DADOS`):
  - antes: só `Estados` = 27 e `Parametros` = 11;
  - 1ª execução de `python main.py --ingestao` (≈18 s): `recebidos=9888 registros_validos=9806 registros_invalidos=82 itens_descartados=3284 leituras_gravadas=9806 itens_gravados=104582`; 1 município, 1 estação, 1 operador;
  - 2ª execução: `leituras_substituidas=9806`, contagens, itens por parâmetro e partições (206 dias) idênticos; só os `id_leitura` mudaram, como esperado na substituição;
  - consultas de duplicidade, leitura sem item, item fora da faixa e hash/e-mail: todas vazias nas duas execuções;
  - log de rejeitados com 3.366 linhas de rejeição: 9.806 leituras no banco + 82 rejeitadas = 9.888; por parâmetro, itens gravados + rejeitados = 9.806 nos 11;
  - nenhum CPF, nome ou e-mail do dataset em `logs/`;
  - backfill: `run_pipeline()` só com os 48 registros de 10/07/2026 (47 válidos) regravou as 47 leituras daquele dia com ids novos; as outras 9.759 mantiveram os ids, e os 104.582 itens (registro, parâmetro, valor) ficaram idênticos;
  - `python main.py --analise` no banco real: 1.824 linhas `WARNING` de alerta (1.528 `IQR`, 296 `IQR+ZSCORE`), igual ao banco de teste.
- **Observação:** os `id_leitura` começavam em 19.613 porque os testes da fase 8, desfeitos com rollback, consumiram valores do `IDENTITY`.
- **Recarga limpa (06/10/2026, a pedido do time):** `Leitura_Itens`, `Leituras`, `Estacoes`, `Operadores` e `Municipios` esvaziadas numa transação, com `IDENTITY` reiniciado; `Estados` (27) e `Parametros` (11) mantidas. Duas cargas seguidas: 1ª com `leituras_substituidas=0` e ids 1 a 9.806, 2ª com `leituras_substituidas=9806` e ids 9.807 a 19.612; contagens, itens por parâmetro e partições idênticos; todas as consultas de conferência vazias; 9.806 + 82 = 9.888 no log de rejeitados; nenhum dado pessoal em `logs/`; `--analise` com 1.824 alertas; CLI sem erro.
- **Coberto pelos testes de integração** (SQL Server Express local, dataset completo):
  - duas execuções seguidas da `run_pipeline()`: mesmo resumo e mesmas contagens; a 2ª substitui as 9.806 leituras;
  - todas as consultas de duplicidade, órfãos, faixa e hash/e-mail voltam vazias;
  - leituras no banco (9.806) + leituras no log de rejeitados (82) = 9.888 recebidos;
  - por parâmetro, itens gravados + itens rejeitados = 9.806;
  - backfill de um dia: só aquela partição muda (inclusive remoção de um registro ausente no reenvio e correção de um valor);
  - nenhum CPF, nome ou e-mail do dataset nos logs.
- **Isolamento dos logs:** os testes gravavam em `logs/` (subprocessos de `main.py`), o que misturaria arquivos de teste com os da carga real. `configurar_logs()` passou a aceitar a variável `PASTA_LOGS`, que o `tests/conftest.py` aponta para uma pasta temporária; `logs/` foi esvaziada.

### Fase 10 — Testes

- **Status:** concluída em 06/10/2026 para a ingestão (estatística e outliers ficam para a fase de analytics).
- `src/security.py` e `src/logger.py` já tinham os testes pedidos (`test_security.py`, `test_logger.py`); acrescentado o teste de `PASTA_LOGS`.
- `tests/integration/test_persistencia.py` (6 testes) e `test_pipeline_e2e.py` (3 testes) reescritos para o modelo 3FN, sem `skip`. Fixtures novas `normalizados` e `lote` em `tests/integration/conftest.py`; `registros_completos` e `registro_legado` removidas.
- **Rollback:** uma falha simulada logo depois de gravar leituras e itens (dentro da transação) não deixa nada gravado na primeira carga e preserva a carga anterior no reprocessamento (mesmos ids, valores e contagens).
- **Resultado:** `162 passed` com o banco de teste (cerca de 1 min); `153 passed, 9 skipped` sem ele.
- Os testes de `analytics_service` e `report_service` foram reescritos junto com o Analytics (fases 14 e 15).

### Fase 11 — Documentação

- **Status:** concluída em 05/10/2026 para o que foi implementado até a fase 8. Revisar de novo depois das fases 9 e 10.
- **Reescritos para a Parte 2:**
  - `modelagem-banco.md`: modelo 3FN com diagrama, colunas, índices, idempotência e situação do banco;
  - `contrato-dados.md`: payload, regra dos parâmetros, normalização, resultado da validação e saídas;
  - `dicionario-dados.md`: campos, destinos, os 11 parâmetros com faixas e perfil do dataset;
  - `arquitetura.md`: módulos reais por camada;
  - `diagramas/diagrama-sequencia.md`, `diagrama-atividade.md` e `diagrama-contexto.md`: fluxo da ingestão implementada;
  - `README.md`: visão geral, quadro do que está implementado, como executar e status.
- **Ajustados:**
  - `requisitos.md`: situação de RF03, RF04, RF05 e RF10 e regras 1 e 8;
  - `analise-estatistica.md`: análise ainda no modelo antigo e itens novos do PDF 3.4;
  - esta análise: aviso de que o contrato vigente está em `contrato-dados.md`.
- **Decisão:** cada assunto tem um documento de referência, sem repetir o conteúdo (COPILOT.md, regras 2 e 7):
  - banco → `modelagem-banco.md`;
  - payload e regras → `contrato-dados.md`;
  - campos → `dicionario-dados.md`;
  - segurança e logs → `seguranca-lgpd.md`;
  - execução → `manual-execucao.md`.

  Esta análise fica como histórico das mudanças e das decisões.
- **Validações:** nenhum link quebrado nos `.md` de `docs/` e no README; nenhuma referência restante a `Cidades`, `criar_tabelas`, `validar_estacao` ou `MOCK_API` fora dos trechos que explicam a mudança.

### Fase 12 — Decisões de Analytics

- **Status:** concluída em 06/10/2026.
- Requisito levantado do PDF: item 3.4 (média e mediana por parâmetro e estação; desvio padrão, variância e IQR; outliers por IQR e validação por Z-Score; indicador de alerta de qualidade) e critério 4 da seção 6 (logs comprovando a detecção de outliers).
- **Decisões aprovadas** (seção 10): D9 = indicador só na análise, sem schema; D10 = IQR **ou** \|Z\| > 3, com o indicador dizendo qual regra sinalizou; D11 = CLI com todos os parâmetros juntos.
- O Data Lake foi retirado do escopo (não será implementado); os documentos que diziam "outra frente do projeto" foram ajustados.

### Fase 13 — Leitura dos dados no modelo 3FN

- **Status:** concluída em 06/10/2026.
- `LeituraRepository.get_medicoes()`: uma linha por medição (`Leitura_Itens` + `Leituras` + `Parametros` + `Estacoes`), filtros por estação, município, parâmetros e período (só início = um dia), ordenada por estação, parâmetro e data/hora; tudo parametrizado.
- `MunicipioRepository.get_com_estacoes()` (com a sigla do estado), `EstacaoRepository.get_by_municipio()` e `get_by_codigo()`.
- **Removidos:** `CidadeRepository`, `CidadeModel`, `EstacaoRepository.get_estacao_cidade()` e as quatro consultas `get_leituras_*` do modelo antigo. Nenhuma referência a `Cidades` ou às colunas largas restou no código.
- **Validação:** `integration/test_analytics.py` (104.582 medições, filtros por dia, período, estação e parâmetro, municípios e estações).

### Fase 14 — Estatística e outliers

- **Status:** concluída em 06/10/2026.
- `AnaliticsService.analisar_medicoes()` (pandas, sem banco): grupos estação + parâmetro; quantidade, média, mediana, desvio padrão e variância amostrais, Q1, Q3, IQR, mínimo, máximo, limites IQR (com 4 valores ou mais) e quantidade de anomalias; Z-Score com o desvio amostral, indefinido com desvio zero ou um valor.
- Anomalias com estação, parâmetro, unidade, data/hora, `codigo_registro`, valor, limites, Z-Score e alerta (`IQR`, `ZSCORE`, `IQR+ZSCORE`). Nada é removido.
- `calculate_metrics(estacao_id, municipio_id, data_inicio, data_fim)` lê o recorte e devolve escopo, período, estatísticas e anomalias. A lista fixa de colunas e nomes do modelo antigo saiu: os parâmetros vêm do banco.
- **Resultado com o dataset atual:** 1.824 anomalias (1.528 `IQR`, 296 `IQR+ZSCORE`, nenhuma só por Z-Score).
- **Ponto para o time:** na precipitação, IQR = 0 (maioria 0 mm) faz toda chuva acima de zero virar `IQR` (1.210 alertas). Mudar a regra para dados com muitos zeros exige decisão; registrado em [analise-estatistica.md](analise-estatistica.md).
- **Validação:** 10 testes unitários (CT-04, CT-05, CT-14) e 4 de aceite em `tests/test_quality_stat.py`.

### Fase 15 — Relatório, logs e consultas SQL

- **Status:** concluída em 06/10/2026.
- `ReportService`: `generate_report()` no formato novo, `format_report()` (resumo, tabela de métricas e de anomalias, arredondadas) e `salvar_csv()` (cria a pasta).
- `main.py`: `gerar_relatorio(database, codigo_estacao, data_inicio, data_fim)` registra o relatório em `INFO` e cada anomalia em `WARNING` (`logger.registrar_anomalias()`); estação inexistente gera `ValueError` → `CRITICAL` e código `1`. Argumentos com `argparse`: `--ingestao` ou `--analise`, com `--estacao`, `--inicio` e `--fim` (formato ISO, validados; `--fim` exige `--inicio`).
- `sql/queries_analiticas.sql` (estava vazio): métricas por estação e parâmetro (`GROUP BY`, `STDEV`, `VAR`), quartis e limites IQR (`PERCENTILE_CONT`), anomalias com o indicador (funções de janela), volume por dia e medições por parâmetro. Variáveis `@codigo_estacao`, `@data_inicio`, `@data_fim`.
- **Validação:** `integration/test_analytics.py` compara as consultas com o serviço sobre o mesmo banco (mesmas métricas e mesma lista de anomalias, CT-15) e confere uma linha `WARNING` por anomalia; testes unitários de argumentos, do relatório e do log.

### Fase 16 — CLI no modelo 3FN

- **Status:** concluída em 06/10/2026.
- Fluxo município → estação → período → métricas e anomalias de todos os parâmetros (D11). As dependências (análise, relatório, console e pasta) passaram a ser injetáveis, para testar.
- **Correções:** as datas digitadas (`dd/mm/aaaa`) eram passadas como texto para o SQL e agora são convertidas para `date`; salvar CSV falhava sem a pasta `relatorios/` e agora a cria; a mensagem "relatório salvo" aparecia mesmo sem salvar e agora só aparece após salvar; `print` substituído por `console.print`; `input` e `console.input` misturados viraram só `console.input`.
- `relatorios/` incluída no `.gitignore`.
- **Validação:** `unit/test_console_app.py` com entradas simuladas (8 testes).

### Fase 17 — Documentação de Analytics

- **Status:** concluída em 06/10/2026.
- `analise-estatistica.md` reescrito (métricas, regras, indicador, como executar, resultado e limitação da precipitação).
- Ajustados: `README.md`, `arquitetura.md`, `manual-execucao.md` (`--analise` e CLI), `requisitos.md` (RF06 a RF08), `modelagem-banco.md` (consultas analíticas), `contrato-dados.md` e `seguranca-lgpd.md` (Data Lake fora do escopo), os três diagramas (sequência da análise em `diagrama-sequencia.md`) e `plano-testes.md` (CT-14, CT-15, arquivos e contagens).
- **Validação:** `183 passed, 18 skipped` sem banco de teste; `201 passed` com o SQL Server Express local; nenhuma referência restante a `CidadeRepository`, `get_leituras_*`, "fase de analytics" ou "outra frente" fora deste histórico.

### Fase 18 — Consumo resiliente da API

- **Status:** concluída em 06/10/2026.
- **Origem:** o item 3.1 do enunciado ("tratamento de erros para queda de conexão, respostas vazias e controle de limite de requisições por minuto") estava previsto na seção 7, mas não tinha fase no TODO. O `DataClient` fazia um único `GET`, sem nova tentativa nem log.
- **`src/ingestion/data_client.py`:**
  - até 4 tentativas com espera crescente (1 s, 2 s, 4 s) para `ConnectionError`, `Timeout`, HTTP 500, 502, 503, 504 e 429; no 429, espera o maior entre o backoff e o `Retry-After`;
  - limite de 30 requisições por minuto (intervalo mínimo de 2 s entre requisições, contando as novas tentativas);
  - corpo vazio ou lista vazia: `WARNING` e lote vazio; JSON inválido, resposta que não é lista ou registro que não é objeto: `ValueError`; 4xx: `HTTPError`, sem nova tentativa;
  - tentativas esgotadas: `ERROR` no log e `FonteIndisponivelError`;
  - `INFO` com a quantidade de registros recebidos;
  - tentativas, espera, limite, `dormir` e `relogio` injetáveis no construtor (padrões nas constantes do módulo), para testar sem esperar.
- **`main.py`:** lote vazio encerra a `run_pipeline()` logo após a coleta, com o resumo zerado e sem conexão com o banco (`_CAMPOS_RESUMO`).
- **Decisão:** valores fixos no código (4 tentativas, 1 s, 30/min), sem variável de ambiente nova, porque a API atual é local e não informa limite. Se uma API externa exigir outro limite, basta mudar as constantes.
- **Validação:** `unit/test_data_client.py` (18 testes: novas tentativas por tipo de falha, esgotamento, `Retry-After`, espaçamento pelo limite por minuto, 4xx sem nova tentativa, respostas vazias e fora do contrato) e `test_lote_vazio_encerra_sem_tocar_no_banco`; manual: API fora do ar = 4 tentativas e `FonteIndisponivelError` em ≈15 s; API no ar = 9.888 registros em 0,4 s. `196 passed, 18 skipped` sem banco de teste.

### Decisões finais (06/10/2026)

- D2, D5 e D6 aprovadas como recomendadas, sem mudança de código: leitura sem operador é rejeitada e logada; campos sem coluna são descartados; as faixas do `dml_populacao.sql` ficam valendo.
- D12 (nova): a regra IQR é mantida também na precipitação; a limitação está documentada.
- Pendente só a tarefa operacional do time: gerar e compartilhar uma única `CHAVE_CRIPTOGRAFIA` e uma única `CHAVE_HASH`.

### Ajuste — cabeçalho nos arquivos de log (06/10/2026)

- **Motivo:** cada execução cria um par de arquivos, e os de rejeitados da análise e da CLI ficavam vazios, sem nada que explicasse a origem. A pedido do time, todo arquivo passa a começar dizendo qual etapa o criou e por quê.
- **`src/logger.py`:** `configurar_logs(etapa, pasta=None)` exige a etapa (`ingestao`, `analise`, `consulta` ou `coleta`; outra gera `ValueError`) e grava 3 linhas de cabeçalho em cada arquivo: etapa e comando, por que o arquivo existe e o que ele contém. As linhas seguem o formato estruturado (`data - [INFO] - mensagem`), levam o marcador `[cabeçalho]` (`MARCADOR_CABECALHO`) e não vão para o console.
- **`main.py`:** `iniciar_aplicacao(etapa)` e `etapa_da_execucao(argumentos)`; `importar_dados.py` avulso usa `coleta`.
- **Testes:** a fixture `logs_temporarios` e o `_ler` de `test_logger.py` ignoram o cabeçalho (as contagens de rejeitados continuam valendo); testes novos conferem o cabeçalho nas quatro etapas, a ordem (antes das demais linhas), a ausência no console, a etapa desconhecida e a etapa escolhida a partir dos argumentos. `205 passed, 18 skipped` sem banco de teste; `223 passed` com ele.


### Ajuste — `PEPPER_HASH` renomeada para `CHAVE_HASH` (07/10/2026)

- **Motivo:** "pepper" não dizia para que a variável serve. `CHAVE_HASH` fica em paralelo com `CHAVE_CRIPTOGRAFIA`: uma cifra o e-mail, a outra entra no hash de CPF e nome.
- **Alterado:** variável de ambiente (`.env`, `.env.example`), `Settings.chave_hash` em `src/config.py`, parâmetro e variável interna de `src/security.py`, `main.py`, testes e documentação. Comportamento igual: preenchida = HMAC-SHA256, vazia = SHA-256 puro.
- **Atenção:** o valor não muda, só o nome. Em cada máquina, renomear a linha `PEPPER_HASH=` do `.env` para `CHAVE_HASH=` mantendo o valor. Como a variável é opcional, um `.env` com o nome antigo não gera erro: o hash vira SHA-256 puro e os operadores já gravados seriam cadastrados de novo.
- **Validação:** `205 passed, 18 skipped` sem banco de teste; `223 passed` com ele.


### Ajuste — dashboard web: paginação e gráfico por período (17/10/2026)

- **Motivo:** a página renderizava todas as medições do recorte (≈104 mil linhas com a carga real) na tabela e de novo em JSON para o gráfico, o que deixava a página com dezenas de MB e lenta. O gráfico só agrupava por hora, dia ou semana, sem navegação entre períodos.
- **`src/ui/visualizacao.py` (novo):** `paginar` / `Pagina` (fatia, intervalo exibido e números de página com reticências), leitura segura de `pagina` e `por_pagina` (10, 25, 50 ou 100), `agregar_por_hora` (baldes `[hora, quantidade, soma, mín., máx.]`, que se combinam sem perda) e filtros de template em formato pt-BR.
- **`src/ui/app.py`:** tabelas de resumo, alertas e medições paginadas no servidor (medições mais recentes primeiro); `GET /api/serie` devolve a série horária e as anomalias de um parâmetro no recorte; `GET /exportar.csv` exporta o recorte inteiro; cache em memória das medições (2 min) e das análises por recorte, descartado após a ingestão. A página passou a ≈40 KB.
- **`src/ui/static/period-chart.js` (novo):** plugin JavaScript (Chart.js) de visualização por semana, mês, ano ou tudo, com navegação, indicadores do período, variação contra o período anterior, faixa mín.–máx., anomalias, perfil por hora do dia, escala ajustada (Q1/Q3 ± 3×IQR das médias horárias) e tabela do período. Uso: `<div data-period-chart data-source="/api/serie?...">`.
- **Interface:** tema claro/escuro, atalhos de período, indicador de faixa (mín., Q1–Q3, mediana) no resumo estatístico, atalhos "Ver no gráfico" e "Ver semana" nas tabelas, layout de celular revisado.
- **Testes:** `tests/unit/test_ui_visualizacao.py` (novo) e `tests/unit/test_ui_app.py` (paginação, API da série, CSV e cache). `239 passed, 18 skipped` sem banco de teste.

### Ajuste — API do Power BI sobre a camada Gold (19/10/2026)

- **Motivo:** o Power BI precisa consumir os dados por API ou Parquet. A camada Gold já sai em modelo estrela (dimensões estação, parâmetro e tempo; fato de medições com média móvel e indicador de outlier), então a API lê os Parquet diretamente, sem gravar Bronze ou Silver em tabelas.
- **Decisão:** ler o Parquet em vez de carregar a Gold no Azure SQL. A Gold tem poucas centenas de milhares de linhas, que o pandas filtra em memória, e o acesso fica isolado em `GoldRepository`: se um dia a Gold for para o banco, troca-se só o repository, sem mudar o contrato consumido pelo BI. A API não altera a Gold (Data Lake fora do escopo desta parte).
- **`src/api/gold_repository.py` (novo):** leitura das quatro tabelas, com cache por arquivo invalidado pela data de modificação e pelo tamanho; ausência ou falha de leitura vira `GoldIndisponivelError`.
- **`src/api/bi_service.py` (novo):** dimensões completas, fato paginada em ordem cronológica (padrão 5000, máximo 50000 por página), filtros por período (inclusivo), estação, parâmetro e outliers, e agregado diário (quantidade, média, mín., máx., outliers).
- **`src/api/bi_controller.py` (novo):** rotas `GET /api/v1/bi/{estacoes, parametros, tempo, medicoes, medicoes/diarias}`, `422` para parâmetros inválidos, `401` sem `X-API-Key` quando `CHAVE_API_BI` está definida e `503` sem Gold. Registrado em `src/api/app.py`.
- **Configuração:** `CHAVE_API_BI` e `DIRETORIO_GOLD` (opcionais) em `.env.example`; `pyarrow` (leitura de Parquet) e `httpx2` (`TestClient` do FastAPI) em `requirements.txt`.
- **Teste pelo dashboard:** página `/api-bi` no Flask (`src/ui/api_bi.py`, `src/ui/templates/api_bi.html`, `src/ui/static/api-bi.js`, link no menu lateral). `GET /api-bi/status`, chamado ao abrir a página, consulta `/health` e, com a API no ar, todas as rotas (a fato com uma linha), informando se a Gold tem dados e o total de medições; com a Gold vazia, a página orienta a executar a ingestão; `GET /api-bi/consulta` executa uma rota com filtros e devolve status, tempo, total, paginação, colunas e as primeiras 20 linhas. A chamada é feita pelo servidor no endereço de `FONTE_DADOS`, com `CHAVE_API_BI` no header: a chave não chega ao navegador e não há CORS entre as portas 5000 e 8000. API fora do ar, `401`, `422` e `503` aparecem com o detalhe devolvido.
- **Testes:** `tests/unit/test_api_bi.py` (cache, Gold ausente ou corrompida, serialização, paginação, filtros, agregado, chave de API e registro no app): `21 passed`. `tests/unit/test_ui_api_bi.py` (repasse de filtros, header da chave, erros e verificação geral) e rotas da página em `tests/unit/test_ui_app.py`: `33 passed`. Conferido também ponta a ponta, com Uvicorn e Flask rodando e a chave ativa. A suíte completa mantém as falhas já existentes na `main`, vindas do Data Lake (`test_main.py`, `test_extracao_dados.py`, `test_logger.py`), sem nenhuma nova.
