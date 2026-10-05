# Análise estatística

O enunciado original pede média, mediana, desvio padrão, IQR e identificação de outliers pela regra IQR, por parâmetro ambiental. Também pede consultas/agregações SQL por estação e filtros por período. Agrupamentos adicionais por cidade, operador e fonte são extensões, não requisitos originais. O estado atual da implementação está em [analise-implementacao.md](analise-implementacao.md).

## Objetivo

Calcular indicadores dos parâmetros ambientais usando os dados persistidos. O requisito original pede os cálculos por parâmetro e a consulta/agregação por estação; a implementação também oferece análise por cidade. Preservar contexto de operador e fonte é uma possibilidade de extensão, não requisito original.

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

## Agrupamentos previstos

O escopo mínimo é análise por estação e parâmetro ambiental, com filtros por data ou intervalo. A implementação também permite consulta por cidade. Agrupamentos por operador e fonte não fazem parte do escopo original e não estão disponíveis no serviço atual.

## Métricas exigidas

Para cada parâmetro ambiental no escopo consultado, o enunciado exige:

- média;
- mediana;
- desvio padrão;
- intervalo interquartil (IQR).

Para identificar outliers pela regra IQR, também se calculam primeiro e terceiro quartis (Q1 e Q3).

## Métricas complementares

Quantidade de registros, mínimo e máximo podem ser apresentados como contexto adicional, mas não substituem as métricas exigidas pelo trabalho.

## Outliers

Um valor será considerado potencialmente atípico quando estiver fora do intervalo:

`[Q1 - 1,5 * IQR, Q3 + 1,5 * IQR]`

O relatório deve informar o campo, o valor, a estação, a data/hora e o limite que foi ultrapassado. Valores atípicos não devem ser removidos automaticamente; devem ser sinalizados para análise.

## Cuidados

- converter os dados antes de usar qualquer função estatística;
- não misturar unidades diferentes no mesmo agrupamento;
- diferenciar ausência de dados de valor zero;
- considerar a convenção de fuso definida no contrato.

Registrar a quantidade de valores descartados por erro de conversão é uma melhoria de observabilidade; não está no enunciado original nem está implementada. Hoje a conversão numérica da análise usa coerção para valores inválidos.

## Situação da implementação

O serviço calcula quantidade, média, mediana e desvio padrão. Usa Q1, Q3 e IQR para definir os limites de outliers, mas não apresenta o IQR como métrica no resumo. Portanto, a detecção por IQR está implementada, mas a lista de métricas está parcial. As estatísticas são calculadas em pandas; ainda falta uma consulta SQL demonstrativa com agregação por estação (`GROUP BY`).

**Parte 2:** o serviço de análise (`src/services/analytics_service.py`) e a CLI ainda consultam o modelo da Parte 1 (`Cidades` e uma coluna por medição), que não existe mais no banco. Por isso a análise está fora da ingestão (`gerar_relatorio()` em `main.py`). Na fase de analytics, ela será adaptada para:

- ler `Leituras` + `Leitura_Itens` + `Parametros`, por estação e parâmetro;
- acrescentar o que o projeto final pede (item 3.4): variância, IQR como métrica, validação por **Z-Score** e um indicador de alerta de qualidade nas leituras anômalas.

Só os valores fisicamente impossíveis (fora de `Parametros.valor_minimo`/`valor_maximo`) são descartados na ingestão. Os outliers estatísticos continuam no banco para serem sinalizados aqui.
