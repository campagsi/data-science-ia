# Contrato de dados

## 1. Objetivo

Define o formato dos dados que entram no sistema, as regras de normalização e validação, o formato entregue a cada etapa e o que é gravado no banco e no log. É a referência para o payload; o detalhe de cada campo está em [dicionario-dados.md](dicionario-dados.md), e o modelo do banco em [modelagem-banco.md](modelagem-banco.md).

## 2. Origem dos dados

O pipeline obtém os dados exclusivamente pela API REST configurada em `FONTE_DADOS`, no endpoint `GET {FONTE_DADOS}/api/v1/data-set`. No ambiente atual, essa API é o serviço FastAPI do projeto (`src/api`), que serve o arquivo `src/api/data_set.json.gz` (JSON compactado em gzip, descompactado pelo `DatasetRepository`). A resposta precisa ser uma lista de objetos JSON; caso contrário, a coleta falha (`DataClient.fetch_data`). Nova tentativa com espera crescente (1 s, 2 s, 4 s; 4 tentativas) para queda de conexão, timeout, HTTP 5xx e 429 (respeitando `Retry-After`), no máximo 30 requisições por minuto, resposta vazia tratada como lote vazio (`WARNING`) e falha definitiva como `FonteIndisponivelError` (`ERROR` e depois `CRITICAL`).

## 3. Estrutura de entrada

Cada objeto é **um ciclo de leitura de uma estação**. Os campos de cadastro vêm repetidos em todo registro, e cada medição chega em cinco campos.

```json
{
  "registro_codigo": "REG-RJ-001-00001",
  "data_hora_ciclo": "2026-04-01T00:00:00",
  "cidade_codigo": "3304557",
  "cidade_nome": "Rio de Janeiro",
  "cidade_estado": "RJ",
  "municipio": "Rio de Janeiro",
  "estacao_codigo": "EST-RJ-001",
  "estacao_nome": "Estação Integrada Guanabara Norte",
  "estacao_latitude": -22.8768,
  "estacao_longitude": -43.1929,
  "estacao_ativa": true,
  "estacao_tipo": "integrada",
  "operador_codigo": "OP-RJ-001",
  "operador_nome_completo": "Nome Completo",
  "operador_cpf": "00000000000",
  "operador_email": "operador@example.invalid",
  "operador_ativo": true,

  "ph": 7.53,
  "ph_unidade_medida": "pH",
  "ph_codigo": "PH-RJ001-00001",
  "ph_tipo_codigo": "TIP-PH",
  "data_hora_leitura_ph": "2026-04-01T00:02:10"
}
```

O exemplo mostra só o parâmetro `ph`. O payload atual traz 11 parâmetros com o mesmo padrão (lista em [dicionario-dados.md](dicionario-dados.md)).

### 3.1 Regra dos parâmetros

Todo campo `X_tipo_codigo` define um parâmetro `X`, sem lista fixa no código:

| Campo | Significado |
|---|---|
| `X` | valor medido (número ou `null`) |
| `X_tipo_codigo` | código do parâmetro → `Parametros.codigo_parametro` |
| `X_unidade_medida` | unidade; o sistema também aceita `X_medida` e `<primeiro termo de X>_unidade_medida` (o payload usa `oxigenio_dissolvido_medida` e `velocidade_unidade_medida`) |
| `X_codigo` | código da medição; não é persistido |
| `data_hora_leitura_X` | hora exata da medição; não é persistida |

Um parâmetro novo no payload **não bloqueia a carga**: ele é cadastrado em `Parametros` sem faixa de valores (seção 6.3).

## 4. Normalização

Feita por `NormalizationService.normalize()`, sem alterar o payload recebido:

1. Textos sem espaços nas pontas; texto vazio vira `None`; `cidade_estado` em maiúsculas; `municipio` nulo usa `cidade_nome`.
2. `estacao_latitude`, `estacao_longitude` e medições convertidos para número; `data_hora_ciclo` e `data_hora_leitura_*` para data/hora (ISO 8601, sem fuso).
3. Cada registro vira um **cabeçalho** mais uma **lista de itens**, um por parâmetro.
4. **Anonimização** com `src/security.py`: `cpf_hash`, `nome_hash` e `email_criptografado`. CPF, nome e e-mail originais **não são copiados** para o registro normalizado (minimização).
5. Ordenação por `data_hora_ciclo`.

O que não pode ser convertido não interrompe o lote. Vai direto para o log de rejeitados com `etapa=normalizacao`:

| Situação | Efeito |
|---|---|
| Medição não numérica; `X_tipo_codigo` vazio | só aquele item sai |
| `data_hora_ciclo` fora do ISO; coordenada não numérica; registro que não é objeto | só aquela leitura sai |
| Resposta da API que não é lista | a execução para (contrato da fonte violado) |

Os campos sem coluna no banco (`cidade_codigo`, `estacao_ativa`, `estacao_tipo`, `operador_ativo`, `X_codigo`, `data_hora_leitura_X`) são listados uma vez por lote no log, só pelo nome.

### 4.1 Registro normalizado

```python
{
    "registro_codigo": "REG-RJ-001-00001",
    "data_hora_ciclo": datetime(2026, 4, 1, 0, 0),
    "cidade_estado": "RJ",
    "municipio": "Rio de Janeiro",
    "estacao_codigo": "EST-RJ-001",
    "estacao_nome": "Estação Integrada Guanabara Norte",
    "estacao_latitude": -22.8768,
    "estacao_longitude": -43.1929,
    "operador_codigo": "OP-RJ-001",
    "cpf_hash": "<64 hex>",
    "nome_hash": "<64 hex>",
    "email_criptografado": "<token Fernet>",
    "itens": [
        {"campo": "ph", "codigo_parametro": "TIP-PH", "unidade_medida": "pH",
         "valor": 7.53, "data_hora_leitura": datetime(2026, 4, 1, 0, 2, 10)},
    ],
}
```

## 5. Parâmetros

Antes da validação, `ParametroService.sincronizar()` compara os parâmetros do lote com `Parametros`:

| Situação | Efeito |
|---|---|
| Já cadastrado, mesma unidade | aceito |
| Novo, com unidade | cadastrado sem faixa (log INFO); medições aceitas |
| Novo sem unidade; nome igual ao de outro código; unidade diferente da cadastrada | parâmetro rejeitado (log ERROR, `etapa=parametro`); as medições dele saem, o resto da leitura segue |

## 6. Validação

Feita por `ValidationService.validate_data()`, **antes de qualquer gravação**. Ela **não grava nem loga** e devolve **um resultado por registro**, na mesma ordem:

```python
{
    "registro_codigo": "REG-RJ-001-00042",
    "valido": False,
    "campos_nulos": ["operador_codigo", "cpf_hash"],
    "itens_invalidos": [{"etapa": "acuracia", "campo": "ph", "motivo": "fora da faixa 0 a 14", "valor": 17.0}],
    "motivos": [{"etapa": "completude", "campo": "operador_codigo,cpf_hash", "motivo": "campo vital nulo", "valor": None}],
    "registro": {...},   # normalizado, só com os itens válidos
}
```

### 6.1 Leitura inválida (`valido=False`)

| Etapa | Regra |
|---|---|
| `completude` | Qualquer campo vital nulo: `registro_codigo`, `data_hora_ciclo`, `cidade_estado`, `municipio`, `estacao_codigo`, `estacao_nome`, `estacao_latitude`, `estacao_longitude`, `operador_codigo`, `cpf_hash`, `nome_hash`, `email_criptografado`. **Todos** os nulos vão em `campos_nulos`. |
| `completude` | Nenhuma medição válida na leitura |
| `acuracia` | Latitude fora de -90 a 90; longitude fora de -180 a 180 |
| `validade` | `cidade_estado` sem duas letras |
| `referencia` | `cidade_estado` que não existe em `Estados` |
| `unicidade` | `registro_codigo` repetido no lote (fica o primeiro) |
| `unicidade` | Mesmo `estacao_codigo` ou `operador_codigo` com dados cadastrais diferentes no lote |

### 6.2 Medição descartada (a leitura continua válida)

| Etapa | Regra |
|---|---|
| `completude` | Valor nulo |
| `acuracia` | Fora de `Parametros.valor_minimo`/`valor_maximo` (limites inclusivos; `NULL` = sem limite; parâmetro sem faixa = sem conferência) |
| `parametro` | Parâmetro rejeitado na seção 5 |

Outlier estatístico **não** é descartado aqui: ele é sinalizado na análise (item 3.4 do enunciado). Só o valor fisicamente impossível, fora da faixa, é descartado.

## 7. Saídas

| Destino | O que recebe |
|---|---|
| Banco (`LeituraRepository.save_readings`) | Só os registros com `valido=True` e só as medições válidas, gravados de forma idempotente ([modelagem-banco.md](modelagem-banco.md)) |
| Log de rejeitados (`logs/rejeitados_*.log`) | Uma linha por leitura inválida (todos os campos nulos juntos) e uma por medição descartada de leitura válida, sem dado pessoal |
| Log da execução (`logs/pipeline_*.log`) | Progresso e uma linha `Resumo da ingestão` |

Formato das linhas de log: seção 6 de [analise-implementacao.md](analise-implementacao.md) e [seguranca-lgpd.md](seguranca-lgpd.md).

## 8. Regras de integridade

1. Nenhuma leitura existe sem estação e operador válidos (FK e validação).
2. Nenhuma medição existe sem leitura e parâmetro cadastrados (FK e validação).
3. Nenhuma medição nula ou fora da faixa é gravada.
4. A mesma leitura (`codigo_registro`) nunca é gravada duas vezes, e a reexecução de um período substitui as leituras de cada estação + dia.
5. CPF, nome e e-mail nunca são gravados em claro no banco nem no log.
6. Todo registro recebido termina em exatamente um destino: gravado (válido) ou no log de rejeitados.

O Data Lake (Bronze, Silver e Gold) não será implementado neste projeto.
