# Análise estatística

## Objetivo

Calcular indicadores sobre as leituras normalizadas, preservando o contexto de cidade, operador, estação, período e fonte.

## Parâmetros analisados

As métricas devem ser aplicadas aos campos numéricos:

- `temperatura`
- `umidade`
- `pressao`
- `precipitacao`
- `velocidade_vento`
- `direcao_vento`
- `radiacao_solar`
- `temperatura_agua`
- `ph`
- `oxigenio_dissolvido`
- `condutividade`
- `turbidez`

## Agrupamentos

Os relatórios devem permitir agrupamento por:

- `cidade_nome` e `cidade_estado`;
- `operador_codigo`;
- `estacao_codigo`;
- data ou intervalo de `data_hora`;
- `fonte`.

## Métricas

Para cada grupo e parâmetro, calcular:

- quantidade de registros;
- média;
- mediana;
- desvio padrão;
- primeiro e terceiro quartis;
- intervalo interquartil (IQR);
- mínimo e máximo.

## Outliers

Um valor será considerado potencialmente atípico quando estiver fora do intervalo:

`[Q1 - 1,5 * IQR, Q3 + 1,5 * IQR]`

O relatório deve informar o campo, o valor, a estação, a data/hora e o limite que foi ultrapassado. Valores atípicos não devem ser removidos automaticamente; devem ser sinalizados para análise.

## Cuidados

- converter os dados antes de usar qualquer função estatística;
- não misturar unidades diferentes no mesmo agrupamento;
- registrar a quantidade de valores descartados por erro de conversão;
- diferenciar ausência de dados de valor zero;
- considerar a convenção de fuso definida no contrato.
