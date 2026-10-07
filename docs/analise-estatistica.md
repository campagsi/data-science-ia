# Análise estatística

Implementa o item 3.4 do [projeto_final.pdf](projeto_final.pdf): tendência central, dispersão e detecção automática de anomalias **por estação e por parâmetro ambiental**, lendo as medições gravadas no banco 3FN (`Leituras` + `Leitura_Itens` + `Parametros` + `Estacoes`). O critério 4 do enunciado ("logs de execução comprovando a detecção de outliers") é atendido pelo log da execução. As decisões D9, D10 e D11 estão na seção 10 de [analise-implementacao.md](analise-implementacao.md).

## Onde está

| Peça | Papel |
|---|---|
| `LeituraRepository.get_medicoes()` | Uma linha por medição, com filtros por estação, município, parâmetros e período |
| `AnaliticsService.calculate_metrics()` | Lê as medições do recorte e chama `analisar_medicoes()` |
| `AnaliticsService.analisar_medicoes()` | Cálculo puro (pandas): métricas, outliers e indicador de alerta |
| `ReportService` | Relatório estruturado, texto para log/console e CSV |
| `logger.registrar_anomalias()` | Uma linha `WARNING` por medição anômala no log da execução |
| `main.py --analise` | Execução em lote (todas as estações ou uma) |
| CLI (`python main.py`) | Consulta interativa: município → estação → período |
| [sql/queries_analiticas.sql](../sql/queries_analiticas.sql) | As mesmas métricas e anomalias em SQL (`GROUP BY`, `PERCENTILE_CONT`, janelas) |

## Agrupamento

Cada grupo é **estação + parâmetro**. Os parâmetros vêm do banco, sem lista fixa no código, então um parâmetro novo cadastrado na ingestão entra na análise sem alteração. Cada parâmetro tem uma única unidade (`Parametros.unidade_medida`), por isso um grupo nunca mistura unidades. A ausência de medição não vira zero: o item nulo não é gravado e simplesmente não entra no grupo.

## Métricas

| Métrica | Definição |
|---|---|
| Quantidade | Valores no grupo |
| Média e mediana | Tendência central |
| Desvio padrão e variância | **Amostrais** (n − 1), padrão do pandas; `STDEV` e `VAR` no SQL |
| Q1, Q3 e IQR | Quartis com interpolação linear (pandas `quantile`; `PERCENTILE_CONT` no SQL); IQR = Q3 − Q1 |
| Mínimo e máximo | Contexto |
| Limites IQR | `[Q1 − 1,5·IQR, Q3 + 1,5·IQR]`, só com pelo menos 4 valores no grupo |
| Anomalias | Medições sinalizadas no grupo |

Com um único valor, desvio e variância ficam indefinidos (`None`).

## Anomalias e indicador de alerta de qualidade

Uma medição é **anômala** se estiver fora dos limites IQR **ou** se o Z-Score, `(valor − média) / desvio`, tiver módulo maior que **3** (decisão D10). O indicador de alerta de qualidade informa qual regra sinalizou:

| Alerta | Significado |
|---|---|
| `IQR` | Fora dos limites IQR, com \|Z\| ≤ 3 |
| `ZSCORE` | Dentro dos limites IQR, com \|Z\| > 3 |
| `IQR+ZSCORE` | As duas regras concordam |

- Desvio zero (todos os valores iguais) ou um único valor: Z-Score indefinido, sem alerta por Z-Score.
- Menos de 4 valores: sem regra IQR.
- Com n ≤ 10, \|Z\| nunca passa de 3 (o máximo amostral é (n − 1)/√n). Em grupos pequenos, só o IQR sinaliza.
- Anomalias **não são removidas**: são sinalizadas para análise. Só o valor fisicamente impossível, fora de `Parametros.valor_minimo`/`valor_maximo`, é descartado, e isso acontece na ingestão (etapa `acuracia`).
- O indicador fica só no resultado da análise, no relatório/CSV e no log (D9). Ele não é gravado no banco, porque depende do recorte analisado.

Cada anomalia traz estação, parâmetro, unidade, data/hora, `codigo_registro`, valor, limites IQR, Z-Score e alerta.

## Como executar

```bash
python main.py --analise                                      # todas as estações, todo o período
python main.py --analise --estacao EST-RJ-001                 # uma estação
python main.py --analise --inicio 2026-06-01                  # um dia
python main.py --analise --inicio 2026-06-01 --fim 2026-06-30 # intervalo
python main.py                                                # CLI interativa (datas em dd/mm/aaaa)
```

O relatório vai para o log da execução (`logs/pipeline_*.log`) em `INFO`, e cada anomalia vai numa linha `WARNING`:

```text
2026-10-06 10:00:00,000 - [WARNING] - Alerta de qualidade: alerta=IQR+ZSCORE estacao="Estação Integrada Guanabara Norte" registro=REG-... parametro="ph" data_hora=2026-06-03 06:00:00 valor=9.3 limites_iqr=[6.98, 7.94] zscore=4.10
```

Na CLI, a opção `0` grava `estatisticas.csv` e `anomalias.csv` (separador `;`) em `relatorios/`, pasta criada se não existir e fora do Git.

## Resultado com o dataset atual

Conferido em `tests/test_quality_stat.py` (sem banco) e em `tests/integration/test_analytics.py` (banco de teste, comparando o serviço com `queries_analiticas.sql`):

- 9.806 leituras e 104.582 medições de 1 estação, 11 parâmetros;
- **1.824 anomalias**: 1.528 `IQR` e 296 `IQR+ZSCORE`; nenhuma só por Z-Score;
- por parâmetro: precipitação 1.210, condutividade 101, turbidez 92, oxigênio dissolvido 76, pressão 75, pH 73, temperatura do ar 71, umidade 53, temperatura da água 47, vento 26, radiação solar 0.

**Limitação da regra IQR na precipitação:** a maior parte das leituras é 0 mm, então Q1 = Q3 = 0 e IQR = 0. Com isso, toda chuva acima de zero sai como `IQR` (1.210 dos 1.824 alertas). Na radiação solar, que também tem muitos zeros (noite), o IQR é largo (≈438 W/m²) e nada é sinalizado. Decisão D12 (06/10/2026): a regra é mantida igual para todos os parâmetros. Na leitura dos alertas de precipitação, `IQR` sem `ZSCORE` indica só que choveu, não um valor suspeito.
