# Dicionário de dados

> **Parte 2:** o payload da API mudou (uma medição vira cinco campos: valor, `_unidade_medida`, `_codigo`, `_tipo_codigo` e `data_hora_leitura_`; operador com CPF, nome completo e e-mail). O mapeamento atual do payload para o banco, o formato normalizado e as regras de nulos estão nas seções 3 e 4 de [analise-implementacao.md](analise-implementacao.md). Este documento descreve o contrato da Parte 1 e será reescrito na fase 11 do [TODO](todo-idempotencia.md).

## Convenções

O JSON de origem entrega todos os valores como texto. A coluna **Tipo interno** representa o tipo após a normalização e antes da persistência.

| Campo | Tipo recebido | Tipo interno | Obrigatório | Unidade / regra |
| --- | --- | --- | --- | --- |
| `cidade_nome` | string | string | sim | nome não vazio |
| `cidade_estado` | string | string | sim | sigla de duas letras, em maiúsculas |
| `operador_codigo` | string | string | sim | identificador único do operador |
| `operador_nome` | string | string | sim | nome não vazio |
| `operador_tipo` | string | string | sim | categoria do operador |
| `operador_ativo` | string | boolean | sim | somente `true` ou `false` |
| `estacao_codigo` | string | string | sim | identificador único da estação |
| `estacao_nome` | string | string | sim | nome não vazio |
| `estacao_latitude` | string decimal | decimal | sim | graus, entre -90 e 90 |
| `estacao_longitude` | string decimal | decimal | sim | graus, entre -180 e 180 |
| `estacao_ativa` | string | boolean | sim | somente `true` ou `false` |
| `estacao_tipo` | string | string | sim | categoria da estação |
| `data_hora` | string ISO 8601 | datetime | sim | data/hora sem fuso no payload atual |
| `temperatura` | string decimal | decimal | não | temperatura do ar, °C |
| `umidade` | string decimal | decimal | não | umidade relativa, % |
| `pressao` | string decimal | decimal | não | pressão atmosférica, hPa |
| `precipitacao` | string decimal | decimal | não | precipitação, unidade a confirmar |
| `velocidade_vento` | string decimal | decimal | não | unidade a confirmar na origem |
| `direcao_vento` | string decimal | decimal | não | direção, graus de 0 a 360 |
| `radiacao_solar` | string decimal | decimal | não | unidade a confirmar na origem |
| `temperatura_agua` | string decimal | decimal | não | temperatura da água, °C |
| `ph` | string decimal | decimal | não | escala de 0 a 14 |
| `oxigenio_dissolvido` | string decimal | decimal | não | unidade a confirmar na origem |
| `condutividade` | string decimal | decimal | não | unidade a confirmar na origem |
| `turbidez` | string decimal | decimal | não | unidade a confirmar na origem |
| `fonte` | string | string | sim | origem do registro, por exemplo `SIMULADO` |

## Regras de qualidade

- Textos devem ser removidos de espaços nas extremidades.
- Campos numéricos devem aceitar apenas representações decimais válidas.
- Medições ausentes (sem a chave, `null` ou string vazia) são gravadas como `NULL`, sem estimativa.
- Booleanos não devem ser convertidos por coerção genérica: valores diferentes de `true` e `false` devem ser rejeitados.
- A data deve ser convertida para um tipo de data/hora e receber uma convenção de fuso definida pela aplicação.
- A combinação `estacao_codigo` e `data_hora` deve ser única para impedir duplicidade de leituras.
