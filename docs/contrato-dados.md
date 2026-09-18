# Contrato de dados

## 1. Objetivo

Este documento define o formato esperado dos dados que entram no sistema, a estrutura de saída do processamento e as regras de validação aplicadas ao fluxo de ingestão e persistência.

O contrato tem como finalidade garantir que os dados coletados pela aplicação sejam consistentes, válidos e compatíveis com o modelo de banco e com a análise estatística do projeto.

## 2. Escopo

O contrato cobre:

- estrutura dos dados recebidos da fonte externa;
- formato das informações persistidas no banco;
- regras de validação para cada campo;
- campos obrigatórios e opcionais;
- representações esperadas para datas, números e códigos.

## 3. Origem dos dados

Os dados podem vir de:

- API REST externa;
- arquivo JSON local;
- fonte simulada em ambiente de teste ou laboratório.

Independentemente da origem, o sistema deve padronizar os dados para um formato interno consistente antes de persistir ou analisar.

## 4. Estrutura de entrada esperada

A estrutura principal de entrada deve seguir o modelo abaixo:

```json
{
  "cidade_nome": "Rio de Janeiro",
  "cidade_estado": "RJ",
  "operador_codigo": "OP-RJ-01",
  "operador_nome": "Instituto Guanabara Ambiental",
  "operador_tipo": "instituto",
  "operador_ativo": "true",
  "estacao_codigo": "EST-RJ-001",
  "estacao_nome": "Estação Integrada Guanabara Norte",
  "estacao_latitude": "-22.8768",
  "estacao_longitude": "-43.1929",
  "estacao_ativa": "true",
  "estacao_tipo": "integrada",
  "data_hora": "2026-06-01T00:00:00",
  "temperatura": "20.5",
  "umidade": "84.5",
  "pressao": "1014.3",
  "precipitacao": "0.0",
  "velocidade_vento": "17.6",
  "direcao_vento": "90.0",
  "radiacao_solar": "0.0",
  "temperatura_agua": "20.8",
  "ph": "7.49",
  "oxigenio_dissolvido": "6.93",
  "condutividade": "431.3",
  "turbidez": "8.5",
  "fonte": "SIMULADO"
}
```

## 5. Regras da estrutura de entrada

### 5.1 Campos obrigatórios

Os campos abaixo devem existir e ter valor válido:

- `cidade_nome`
- `cidade_estado`
- `operador_codigo`
- `operador_nome`
- `operador_tipo`
- `operador_ativo`
- `estacao_codigo`
- `estacao_nome`
- `estacao_latitude`
- `estacao_longitude`
- `estacao_ativa`
- `estacao_tipo`
- `data_hora`
- `temperatura`, `umidade`, `pressao`, `precipitacao`
- `velocidade_vento`, `direcao_vento`, `radiacao_solar`
- `temperatura_agua`, `ph`, `oxigenio_dissolvido`
- `condutividade`, `turbidez`
- `fonte`
- `ph`
- `oxigenio_dissolvido`
- `condutividade`

### 5.2 Campos opcionais

O contrato atual não define campos opcionais. Qualquer ausência deve ser tratada como erro de validação até que um novo contrato seja aprovado.

## 6. Regras de validação por campo

| Campo | Tipo esperado | Regra |
| --- | --- | --- |
| cidade_nome | string | obrigatório, não vazio |
| cidade_estado | string | obrigatório, sigla de duas letras |
| operador_codigo | string | obrigatório, único por operador |
| operador_nome | string | obrigatório, não vazio |
| operador_tipo | string | obrigatório |
| operador_ativo | string boolean | obrigatório, `true` ou `false` |
| estacao_codigo | string | obrigatório, único por estação |
| estacao_nome | string | obrigatório, não vazio |
| estacao_latitude | string decimal | obrigatório, entre -90 e 90 |
| estacao_longitude | string decimal | obrigatório, entre -180 e 180 |
| estacao_ativa | string boolean | obrigatório, `true` ou `false` |
| estacao_tipo | string | obrigatório |
| data_hora | string ISO 8601 | obrigatório e deve representar data/hora válida |
| temperatura | string decimal | obrigatório |
| umidade | string decimal | obrigatório, entre 0 e 100 |
| pressao | string decimal | obrigatório |
| precipitacao | string decimal | obrigatório, maior ou igual a zero |
| velocidade_vento | string decimal | obrigatório |
| direcao_vento | string decimal | obrigatório, entre 0 e 360 |
| radiacao_solar | string decimal | obrigatório, maior ou igual a zero |
| temperatura_agua | string decimal | obrigatório |
| ph | string decimal | obrigatório, entre 0 e 14 |
| oxigenio_dissolvido | string decimal | obrigatório, maior ou igual a zero |
| condutividade | string decimal | obrigatório, maior ou igual a zero |
| turbidez | string decimal | obrigatório, maior ou igual a zero |
| fonte | string | obrigatório, identifica a origem do registro |

## 7. Regras de normalização

Antes do armazenamento, os dados devem passar por normalização, nesta ordem:

- remover espaços extras no início e no fim dos textos;
- converter os campos numéricos de string para `decimal` ou `float` conforme a implementação;
- converter `operador_ativo` e `estacao_ativa` para booleano;
- converter `data_hora` para um tipo de data/hora;
- padronizar `cidade_estado` em letras maiúsculas;
- tratar valores nulos e vazios como erro, pois todos os campos atuais são obrigatórios;
- registrar registros inválidos para posterior correção.

O horário recebido não contém fuso. A aplicação deve documentar e aplicar uma única convenção, preferencialmente `America/Sao_Paulo`, antes da persistência.

## 8. Estrutura de saída do sistema

A saída do processamento pode ser representada como um objeto consolidado de análise:

```json
{
  "estacao_codigo": "EST-RJ-001",
  "cidade_nome": "Rio de Janeiro",
  "periodo": "2026-01-15",
  "metricas": {
    "temperatura_media": 24.8,
    "temperatura_mediana": 25.0,
    "temperatura_desvio_padrao": 2.4,
    "umidade_media": 68.0,
    "ph_medio": 7.2
  },
  "outliers": [
    {
      "campo": "temperatura",
      "valor": 39.5,
      "motivo": "fora do intervalo esperado"
    }
  ]
}
```

## 9. Contrato do banco

O banco deve manter a representação dos dados em entidades relacionadas:

- `Cidade`
- `Operador`
- `Estacao`
- `Leitura`

Cada entidade deve seguir as regras de integridade estabelecidas no modelo de dados. A relação principal é:

- Cidade -> Estacoes
- Operador -> Estacoes
- Estacao -> Leituras

## 10. Tratamento de erros

Quando a estrutura de entrada estiver inconsistente, o sistema deve:

- registrar a falha;
- rejeitar o registro ou blocar a persistência;
- devolver uma mensagem clara de erro;
- não armazenar dados incompletos sem validação.

## 11. Regras de integridade

1. Nenhuma leitura pode existir sem uma estação associada.
2. Nenhuma estação pode existir sem cidade e operador válidos.
3. Campos numéricos recebidos como texto devem ser convertidos e validados antes da persistência.
4. Datas devem seguir padronização ISO 8601.
5. Uma leitura deve ser idempotente para a combinação `estacao_codigo` e `data_hora`.
6. Dados sensíveis devem ser preservados apenas quando estritamente necessários.

## 12. Conclusão

Este contrato define a base de comunicação entre a fonte de dados, o sistema e o banco. Ele garante que os dados recebidos e persistidos sejam consistentes, rastreáveis e adequados para análise estatística e tomada de decisão.
