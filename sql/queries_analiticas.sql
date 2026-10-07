-- Consultas analíticas sobre o banco relacional (modelo 3FN).
--
-- Mesmas definições de src/services/analytics_service.py: STDEV e VAR são
-- amostrais e PERCENTILE_CONT interpola como o pandas, então os números batem
-- com o relatório de `python main.py --analise`.
--
-- Filtros: @codigo_estacao NULL = todas as estações; @data_inicio e @data_fim
-- NULL = todo o período. Cada lote (separado por GO) pode ser executado sozinho.

-- 1. Métricas por estação e parâmetro (contagem, média, desvio, variância, mínimo, máximo)
DECLARE @codigo_estacao VARCHAR(50) = NULL;
DECLARE @data_inicio DATE = NULL;
DECLARE @data_fim DATE = NULL;

SELECT
    E.codigo_estacao,
    E.nome AS estacao,
    P.codigo_parametro,
    P.nome AS parametro,
    P.unidade_medida,
    COUNT(*) AS quantidade,
    AVG(I.valor) AS media,
    STDEV(I.valor) AS desvio_padrao,
    VAR(I.valor) AS variancia,
    MIN(I.valor) AS minimo,
    MAX(I.valor) AS maximo
FROM dbo.Leitura_Itens AS I
INNER JOIN dbo.Leituras AS L ON L.id_leitura = I.leitura_id
INNER JOIN dbo.Parametros AS P ON P.id_parametro = I.parametro_id
INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
WHERE (@codigo_estacao IS NULL OR E.codigo_estacao = @codigo_estacao)
  AND (@data_inicio IS NULL OR CAST(L.data_hora AS DATE) >= @data_inicio)
  AND (@data_fim IS NULL OR CAST(L.data_hora AS DATE) <= @data_fim)
GROUP BY E.codigo_estacao, E.nome, P.codigo_parametro, P.nome, P.unidade_medida
ORDER BY E.codigo_estacao, P.codigo_parametro;
GO

-- 2. Mediana, quartis, IQR e limites da regra IQR por estação e parâmetro
DECLARE @codigo_estacao VARCHAR(50) = NULL;
DECLARE @data_inicio DATE = NULL;
DECLARE @data_fim DATE = NULL;

WITH quartis AS (
    SELECT DISTINCT
        E.codigo_estacao,
        P.codigo_parametro,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY I.valor)
            OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS q1,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY I.valor)
            OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS mediana,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY I.valor)
            OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS q3
    FROM dbo.Leitura_Itens AS I
    INNER JOIN dbo.Leituras AS L ON L.id_leitura = I.leitura_id
    INNER JOIN dbo.Parametros AS P ON P.id_parametro = I.parametro_id
    INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
    WHERE (@codigo_estacao IS NULL OR E.codigo_estacao = @codigo_estacao)
      AND (@data_inicio IS NULL OR CAST(L.data_hora AS DATE) >= @data_inicio)
      AND (@data_fim IS NULL OR CAST(L.data_hora AS DATE) <= @data_fim)
)
SELECT
    codigo_estacao,
    codigo_parametro,
    mediana,
    q1,
    q3,
    q3 - q1 AS iqr,
    q1 - 1.5 * (q3 - q1) AS limite_inferior,
    q3 + 1.5 * (q3 - q1) AS limite_superior
FROM quartis
ORDER BY codigo_estacao, codigo_parametro;
GO

-- 3. Medições anômalas (fora do IQR ou com |Z| > 3), com o indicador de alerta
DECLARE @codigo_estacao VARCHAR(50) = NULL;
DECLARE @data_inicio DATE = NULL;
DECLARE @data_fim DATE = NULL;
DECLARE @limite_zscore FLOAT = 3.0;

WITH medicoes AS (
    SELECT
        E.codigo_estacao,
        P.codigo_parametro,
        L.codigo_registro,
        L.data_hora,
        I.valor,
        COUNT(*) OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS quantidade,
        AVG(I.valor) OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS media,
        STDEV(I.valor) OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS desvio,
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY I.valor)
            OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS q1,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY I.valor)
            OVER (PARTITION BY E.codigo_estacao, P.codigo_parametro) AS q3
    FROM dbo.Leitura_Itens AS I
    INNER JOIN dbo.Leituras AS L ON L.id_leitura = I.leitura_id
    INNER JOIN dbo.Parametros AS P ON P.id_parametro = I.parametro_id
    INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
    WHERE (@codigo_estacao IS NULL OR E.codigo_estacao = @codigo_estacao)
      AND (@data_inicio IS NULL OR CAST(L.data_hora AS DATE) >= @data_inicio)
      AND (@data_fim IS NULL OR CAST(L.data_hora AS DATE) <= @data_fim)
),
classificadas AS (
    SELECT
        *,
        (valor - media) / NULLIF(desvio, 0) AS zscore,
        -- A regra IQR só vale com pelo menos 4 valores.
        CASE WHEN quantidade >= 4
              AND (valor < q1 - 1.5 * (q3 - q1) OR valor > q3 + 1.5 * (q3 - q1))
             THEN 1 ELSE 0 END AS fora_iqr
    FROM medicoes
)
SELECT
    codigo_estacao,
    codigo_parametro,
    codigo_registro,
    data_hora,
    valor,
    zscore,
    CASE
        WHEN fora_iqr = 1 AND ABS(zscore) > @limite_zscore THEN 'IQR+ZSCORE'
        WHEN fora_iqr = 1 THEN 'IQR'
        ELSE 'ZSCORE'
    END AS alerta_qualidade
FROM classificadas
WHERE fora_iqr = 1 OR ABS(zscore) > @limite_zscore
ORDER BY codigo_estacao, codigo_parametro, data_hora;
GO

-- 4. Leituras e medições por dia e estação (volume e completude ao longo do tempo)
DECLARE @codigo_estacao VARCHAR(50) = NULL;

SELECT
    E.codigo_estacao,
    CAST(L.data_hora AS DATE) AS dia,
    COUNT(DISTINCT L.id_leitura) AS leituras,
    COUNT(*) AS medicoes,
    CAST(COUNT(*) AS FLOAT) / COUNT(DISTINCT L.id_leitura) AS medicoes_por_leitura
FROM dbo.Leituras AS L
INNER JOIN dbo.Leitura_Itens AS I ON I.leitura_id = L.id_leitura
INNER JOIN dbo.Estacoes AS E ON E.id_estacao = L.estacao_id
WHERE @codigo_estacao IS NULL OR E.codigo_estacao = @codigo_estacao
GROUP BY E.codigo_estacao, CAST(L.data_hora AS DATE)
ORDER BY E.codigo_estacao, dia;
GO

-- 5. Medições por parâmetro (conferência com o resumo da ingestão)
SELECT P.codigo_parametro, P.nome, COUNT(I.leitura_id) AS medicoes
FROM dbo.Parametros AS P
LEFT JOIN dbo.Leitura_Itens AS I ON I.parametro_id = P.id_parametro
GROUP BY P.codigo_parametro, P.nome
ORDER BY P.codigo_parametro;
GO
