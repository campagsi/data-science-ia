# Dicionário de dados

Campos do payload da API (`src/api/data_set.json`), o tipo depois da normalização e o destino no banco. As regras de normalização e validação estão em [contrato-dados.md](contrato-dados.md); as colunas, em [modelagem-banco.md](modelagem-banco.md).

## Convenções

- **Vital:** sem ele a leitura é rejeitada (completude). As medições não são vitais: a nula é descartada sozinha.
- **Descartado:** não tem coluna no banco (decisão D5 em [analise-implementacao.md](analise-implementacao.md)).
- Datas em ISO 8601, sem fuso.
- Texto vazio vale como nulo.

## Cabeçalho da leitura

| Campo do payload | Tipo recebido | Tipo interno | Vital | Destino |
|---|---|---|---|---|
| `registro_codigo` | string | string | sim | `Leituras.codigo_registro` (chave natural) |
| `data_hora_ciclo` | string ISO 8601 | datetime | sim | `Leituras.data_hora` |
| `cidade_estado` | string | string, maiúsculas | sim | busca em `Estados.sigla` |
| `municipio` | string | string | sim* | `Municipios.nome` |
| `cidade_nome` | string | string | — | usado quando `municipio` vem nulo |
| `cidade_codigo` | string | — | — | descartado |
| `estacao_codigo` | string | string | sim | `Estacoes.codigo_estacao` |
| `estacao_nome` | string | string | sim | `Estacoes.nome` |
| `estacao_latitude` | número | float | sim | `Estacoes.latitude` (-90 a 90) |
| `estacao_longitude` | número | float | sim | `Estacoes.longitude` (-180 a 180) |
| `estacao_ativa`, `estacao_tipo` | boolean, string | — | — | descartados |
| `operador_codigo` | string | string | sim | `Operadores.codigo_operador` |
| `operador_cpf` | string | `cpf_hash` (64 hex) | sim | `Operadores.cpf_hash`; original nunca gravado |
| `operador_nome_completo` | string | `nome_hash` (64 hex) | sim | `Operadores.nome_hash`; original nunca gravado |
| `operador_email` | string | `email_criptografado` | sim | `Operadores.email_criptografado` (reversível) |
| `operador_ativo` | boolean | — | — | descartado |
| — | — | — | — | `Leituras.fonte` = `FONTE_DADOS` (URL da API) |

\* `municipio` nulo é aceito quando `cidade_nome` está preenchido.

## Medições (11 parâmetros no payload atual)

Para cada parâmetro `X`: `X` → `Leitura_Itens.valor`; `X_tipo_codigo` → `Parametros.codigo_parametro`; `X_unidade_medida` → `Parametros.unidade_medida`. `X_codigo` e `data_hora_leitura_X` são descartados. As faixas vêm do `sql/dml_populacao.sql` (decisão D6, proposta aguardando validação do time).

| Campo `X` | Código (`X_tipo_codigo`) | Nome em `Parametros` | Unidade | Faixa válida |
|---|---|---|---|---|
| `temperatura_agua` | `TIP-TAG` | Temperatura da água | °C | 0 a 45 |
| `ph` | `TIP-PH` | pH | pH | 0 a 14 |
| `temperatura` | `TIP-TMP` | Temperatura do ar | °C | -40 a 60 |
| `umidade` | `TIP-UMI` | Umidade relativa do ar | % | 0 a 100 |
| `pressao` | `TIP-PRE` | Pressão atmosférica ao nível do mar | hPa | 870 a 1085 |
| `precipitacao` | `TIP-CHU` | Precipitação | mm | ≥ 0 |
| `velocidade_vento` | `TIP-VEN` | Velocidade do vento | km/h | 0 a 200 |
| `radiacao_solar` | `TIP-RAD` | Radiação solar | W/m² | 0 a 1500 |
| `oxigenio_dissolvido` | `TIP-OXI` | Oxigênio dissolvido | mg/L | 0 a 20 |
| `condutividade` | `TIP-CON` | Condutividade elétrica a 25 °C | µS/cm | ≥ 0 |
| `turbidez` | `TIP-TUR` | Turbidez | NTU | ≥ 0 |

Nomes de unidade fora do padrão no payload: `oxigenio_dissolvido_medida` e `velocidade_unidade_medida` (para `velocidade_vento`).

## Perfil do dataset atual (9.888 registros)

| Situação | Quantidade | Tratamento |
|---|---|---|
| Sem estação nem operador | 50 | leitura rejeitada |
| Com estação e sem operador | 32 | leitura rejeitada |
| Medições nulas nos registros válidos | 2.681 | só o item descartado |
| Medições fora da faixa nos registros válidos | 603 | só o item descartado |
| Registros gravados | 9.806 leituras, 104.582 itens | — |
