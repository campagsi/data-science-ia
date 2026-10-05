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
| `Operadores (codigo, nome, tipo, cidade_id)` | `Operadores (codigo_operador, nome_hash, cpf_hash, email_hash, municipio_id)` | Nome e CPF como hash SHA-256; o e-mail precisa de criptografia reversível (D7). `tipo` deixa de existir. Regras em [seguranca-lgpd.md](seguranca-lgpd.md). |
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
| `operador_email` | `email_hash` → `email_criptografado` (D7) | `criptografar_email` de `src/security.py` (Fernet, reversível). |
| — | — | Os três campos originais são removidos do registro logo após a anonimização (minimização); depois disso nada os grava nem loga. Ver [seguranca-lgpd.md](seguranca-lgpd.md). |
| `operador_ativo` | — | Sem coluna no DDL (D5). |
| `registro_codigo` | `Leituras` (chave natural) | **Sem coluna no DDL**, mas é o identificador natural da leitura (D1). |
| `data_hora_ciclo` | `Leituras.data_hora` | |
| — | `Leituras.fonte` | **Não existe no payload** e a coluna é `NOT NULL` (D3). |
| `<param>` | `Leitura_Itens.valor` | Valor nulo → não grava o item e registra no log de rejeitados. |
| `<param>_tipo_codigo` (ex.: `TIP-PH`) | `Parametros.codigo_parametro` | Base da descoberta de parâmetros novos. |
| `<param>_unidade_medida` | `Parametros.unidade_medida` | Exceções no payload: `oxigenio_dissolvido_medida` e `velocidade_unidade_medida`. |
| `<param>_codigo` (ex.: `PH-RJ001-00001`), `data_hora_leitura_<param>` | — | Sem coluna no DDL (D5). |

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

Sem unidade, não há como cadastrar (`unidade_medida NOT NULL`): o parâmetro é registrado como rejeitado com nível ERROR e os itens dele não são gravados.

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
| Data Lake | Silver (fase futura) recebe só `valido=True`. A Bronze guarda o bruto do lote, como o enunciado pede (item 3.1), e pode gravar junto o resultado (`valido`, `campos_nulos`) como metadado de controle. |
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

A mesma regra vale para `data_lake/bronze`: arquivos particionados por data de ciclo (`data_lake/bronze/dt=AAAA-MM-DD/...json`), e a reexecução sobrescreve a partição em vez de acrescentar.

### Critério de aceite

Executar o pipeline duas vezes com o mesmo dataset deve deixar **exatamente as mesmas contagens** em todas as tabelas e nenhum `GROUP BY ... HAVING COUNT(*) > 1` nas chaves naturais.

---

## 6. Logs (módulo central `src/logger.py`)

O log é configurado em **um único módulo**, `src/logger.py`, seguindo `avanade-ds-ia/modulo-1/projeto-pratico/src/transform.py` e `avanade-ds-ia/modulo-2/ED_PYTHON/01_ingestao_api.py`. A estrutura do módulo e as regras de dados pessoais em log estão em [seguranca-lgpd.md](seguranca-lgpd.md). Aqui fica o que é específico desta implementação:

- `configurar_logs()` chamado **uma vez** no início do `main.py`, com `logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s', handlers=[...])` (formato do `transform.py`);
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
| [main.py](../main.py) | Chamada `criar_tabelas()` removida; `iniciar_aplicacao()` chama `configurar_logs()` uma vez; `print` trocado por log (fases 2 e 3). |
| `src/logger.py` (novo) | Configuração única de log: `configurar_logs()`, loggers `DataScienceIA_Logger` e `DataScienceIA_Rejeitados`, `registrar_rejeicao(...)`. |
| `src/security.py` (novo) | Único ponto de anonimização e criptografia: `anonimizar_cpf`, `anonimizar_nome`, `criptografar_email`, `descriptografar_email` ([seguranca-lgpd.md](seguranca-lgpd.md)). |
| [src/config.py](../src/config.py) | Ler `CHAVE_CRIPTOGRAFIA` (e `PEPPER_HASH`, se D8 aprovada) e falhar se ausente, sem expor o valor. |
| [.env.example](../.env.example) | Incluir `CHAVE_CRIPTOGRAFIA`, `PEPPER_HASH` e `FONTE_DADOS` (só os nomes). |
| `src/database/criar_tabelas.py` | **Removido** (criava o modelo antigo). O schema vem do DDL e das migrations. |
| `sql/migrations/` (novo) | Uma migration idempotente `VNNN__descricao.sql` por mudança de estrutura; o DDL é atualizado na mesma entrega. |
| [src/ingestion/data_client.py](../src/ingestion/data_client.py) | Adicionar tratamento de queda de conexão, resposta vazia e rate limit, com logs (padrão de `extrair_dados_api`). |
| [src/ingestion/importar_dados.py](../src/ingestion/importar_dados.py) | Reescrita para a nova ordem: Estados (busca) → Municípios → Operadores → Estações → Parâmetros → Leituras/Itens (por partição). Os caches `__cidades`, `__operadores` e `__estacoes` passam a ser municípios, operadores, estações e parâmetros. |
| [src/services/normalization_service.py](../src/services/normalization_service.py) | **Reescrito na fase 4:** payload novo, cabeçalho + itens, descoberta de parâmetros, anonimização e minimização, rejeição por item ou leitura sem derrubar o lote. |
| [src/services/validation_service.py](../src/services/validation_service.py) | **Reescrito nas fases 5 e 6:** um resultado por registro (`valido`, `campos_nulos`, `itens_invalidos`, `motivos`, `registro`; contrato na seção 4), sem abortar o lote. Faixas e siglas recebidas no construtor; a leitura delas no banco entra na fase 8. |
| [src/models/](../src/models/) | `CidadeModel` → `MunicipioModel`; `EstadoModel` já existe; novos `ParametroModel` e `LeituraItemModel`; `LeituraModel` vira cabeçalho (`operador_id`, `estacao_id`, `data_hora`, `fonte`); `OperadorModel` e `EstacaoModel` seguem as colunas do DDL. |
| [src/repository/](../src/repository/) | `CidadeRepository` → `MunicipioRepository`; `EstadoRepository` já existe; novos `ParametroRepository` e itens de leitura; todos os `create_many` passam a ser idempotentes (`MERGE`/partição). Há métodos com SQL montado por f-string (`create` em `leitura_repository.py` e `operador_repository.py`) que precisam sair. |
| [src/services/analytics_service.py](../src/services/analytics_service.py), [src/cli/](../src/cli/), [src/services/report_service.py](../src/services/report_service.py) | Consultam `Cidades` e as colunas largas de `Leituras` e **vão quebrar**. Precisam ler `Leitura_Itens` + `Parametros` e pivotar no pandas. Fica fora do TODO de idempotência e entra na fase de analytics. |
| [requirements.txt](../requirements.txt) | Adicionar `cryptography` (Fernet). O `src/cli` também usa `rich`, que não está listado. |
| [sql/dml_populacao.sql](../sql/dml_populacao.sql) | Carga inicial: 27 estados e os 11 parâmetros conhecidos, com faixas. |
| [.gitignore](../.gitignore) | Adicionar `logs/` e os arquivos de dados de `data_lake/` (mantendo os `.gitkeep`), porque a Bronze guarda dado pessoal em claro. |

---

## 8. Impacto nos testes

- `tests/integration/conftest.py` já monta o banco de teste com o DDL + migrations. `test_persistencia.py` e `test_pipeline_e2e.py` ainda usam o modelo antigo e estão pulados (`pytest.mark.skip`) até serem reescritos nas fases 8 e 10.
- `test_normalization_service.py` (fase 4), `test_validation_service.py` (fases 5 e 6) e `tests/test_quality_stat.py` já usam o payload novo. A fixture `registro_legado` (formato antigo) sobra só para `integration/test_persistencia.py`, que está pulado.
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
| D1 | Chave natural de `Leituras` (o DDL não tem nenhuma) | (a) nova coluna `codigo_registro VARCHAR(50) NOT NULL` + `UNIQUE`; (b) `UNIQUE (estacao_id, data_hora)` | **(a)**: é o identificador do enunciado ("Identificador do Pedido/Leitura") e vem pronto no payload. Exige alterar o DDL e o banco. |
| D2 | Leitura com estação mas **sem operador** (32 registros) | (a) rejeitar; (b) `operador_id` passa a aceitar `NULL`; (c) operador "NÃO INFORMADO" | **(a)**, que mantém o DDL; os 32 vão para o log de rejeitados. |
| D3 | `Leituras.fonte` é `NOT NULL` e o payload não traz fonte | (a) constante, ex.: `API_MOCK`; (b) host da `MOCK_API`; (c) campo no `.env` | **(c)** `FONTE_DADOS` no `.env`, com padrão `API_MOCK`. |
| D4 | `ValidationService.validate_data` aborta o lote inteiro | Alterar para rejeição por registro e por item | **Aprovada em 05/10/2026**: o CLAUDE.md passou a permitir alteração de lógica na Parte 2. Necessária para "salvar log de tudo que não foi importado". |
| D5 | Campos do payload sem coluna no DDL: `cidade_codigo`, `estacao_ativa`, `estacao_tipo`, `operador_ativo`, `<param>_codigo`, `data_hora_leitura_<param>` | (a) descartar; (b) adicionar colunas | **(a)** por ora, registrando no `INFO` de resumo. Reavaliar `data_hora_leitura_<param>` (hora exata de cada medição) para a Gold. |
| D6 | Faixas de `valor_minimo`/`valor_maximo` dos 11 parâmetros | Proposta no TODO (fase 3) | **Proposta aplicada no `dml_populacao.sql` em 05/10/2026, aguardando validação do time.** pH 0–14 e umidade 0–100 vêm do enunciado e do código atual. Para mudar, basta editar o DML e reexecutá-lo (`MERGE` atualiza as faixas). |
| D7 | Onde gravar o e-mail criptografado: `email_hash VARCHAR(64)` não comporta um token Fernet (cerca de 140 caracteres para um e-mail comum) | (a) trocar `email_hash` por `email_criptografado VARCHAR(255) NULL`; (b) manter `email_hash` e adicionar `email_criptografado`; (c) só hash, sem recuperação | **(a)**: segue o exemplo `security.py` e o item 3.2 do enunciado (reversível para dado que exige recuperação). Exige alterar o DDL e o banco, junto com a D1. |
| D8 | Hash de CPF e nome com pepper | (a) SHA-256 puro, como no exemplo; (b) SHA-256 de `PEPPER_HASH` + valor | **(b)**: o CPF tem só 10¹¹ combinações e o SHA-256 puro pode ser revertido por força bruta. Mantém os 64 caracteres. |

---

## 11. Relatório das fases

Cada fase do [TODO](todo-idempotencia.md) registra aqui: alterações realizadas, arquivos envolvidos, decisões relevantes e validações executadas.

### Fase 0 — Validação do banco contra o DDL

- **Status:** concluída em 05/10/2026.
- **Alterações:** nenhuma no banco; somente leitura.
- **Validação:** comparação de tabelas, colunas, constraints e índices (seção 1). Banco idêntico ao DDL e vazio.

### Fase 1 — Decisões

- **Status:** pendente.

### Fase 2 — Módulos centrais de log e segurança

- **Status:** concluída em 05/10/2026. Ficam para a fase 8 a chamada do resumo com as contagens reais e, para a fase 9, as conferências com carga real.
- **Alterações:**
  - `src/logger.py` (novo): `configurar_logs()`, loggers `DataScienceIA_Logger` e `DataScienceIA_Rejeitados`, `registrar_rejeicao()`, `contar_rejeicoes()`, `registrar_resumo()`.
  - `src/security.py` (novo): `configurar_seguranca()`, `anonimizar_cpf()`, `anonimizar_nome()`, `criptografar_email()`, `descriptografar_email()`.
  - `src/config.py`: `Settings` ganhou `chave_criptografia`, `pepper_hash` e `fonte_dados` (com padrão, então as chamadas antigas continuam válidas); `CHAVE_CRIPTOGRAFIA` passou a ser obrigatória.
  - `main.py`: nova `iniciar_aplicacao()` (logs → configuração → segurança), chamada antes da CLI; `print` trocado por `logger`.
  - `src/ingestion/importar_dados.py`: `print` do bloco `__main__` trocado por log.
  - `requirements.txt`: `cryptography` e `rich` (a CLI já usava `rich`, mas ele não estava listado e os testes nem chegavam a rodar).
  - `.env.example`, `.gitignore` (`logs/` e dados de `data_lake/`), `docs/seguranca-lgpd.md`, `docs/manual-execucao.md`.
- **Decisões:**
  - A D8 ficou configurável: `PEPPER_HASH` preenchido usa HMAC-SHA256, vazio usa SHA-256 puro.
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
  - Log de rejeitados com 3.366 linhas e sem CPF nem e-mail.
  - `pytest`: **136 passaram e 7 foram pulados**.
- **Correção de um número da análise:** o pH fora de 0–14 nos registros **válidos** é 72, e não 73. A 73ª ocorrência está num registro já rejeitado por completude.

### Fase 7 — Cadastro automático de parâmetros

- **Status:** pendente.

### Fase 8 — Persistência idempotente

- **Status:** pendente.

### Fase 9 — Validação do banco após a carga

- **Status:** pendente.

### Fase 10 — Testes

- **Status:** pendente.

### Fase 11 — Documentação

- **Status:** pendente.
