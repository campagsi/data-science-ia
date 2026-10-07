-- DML de população do banco (carga inicial de domínio).
-- Idempotente: pode ser executado quantas vezes for preciso; MERGE pela chave
-- natural (Estados.sigla, Parametros.codigo_parametro) insere o que falta e
-- atualiza o que mudou, sem duplicar.
-- Executar depois do ddl_banco_relacional.sql (e das migrations).
-- Pelo sqlcmd, usar -f 65001 para ler o arquivo em UTF-8 (acentos, °, µ, ²).

SET NOCOUNT ON;
GO

/* =========================================
   ESTADOS (27 unidades federativas)
   O payload só traz a sigla (cidade_estado); Estados.nome é obrigatório.
========================================= */

MERGE dbo.Estados AS destino
USING (VALUES
    ('AC', N'Acre'),
    ('AL', N'Alagoas'),
    ('AP', N'Amapá'),
    ('AM', N'Amazonas'),
    ('BA', N'Bahia'),
    ('CE', N'Ceará'),
    ('DF', N'Distrito Federal'),
    ('ES', N'Espírito Santo'),
    ('GO', N'Goiás'),
    ('MA', N'Maranhão'),
    ('MT', N'Mato Grosso'),
    ('MS', N'Mato Grosso do Sul'),
    ('MG', N'Minas Gerais'),
    ('PA', N'Pará'),
    ('PB', N'Paraíba'),
    ('PR', N'Paraná'),
    ('PE', N'Pernambuco'),
    ('PI', N'Piauí'),
    ('RJ', N'Rio de Janeiro'),
    ('RN', N'Rio Grande do Norte'),
    ('RS', N'Rio Grande do Sul'),
    ('RO', N'Rondônia'),
    ('RR', N'Roraima'),
    ('SC', N'Santa Catarina'),
    ('SP', N'São Paulo'),
    ('SE', N'Sergipe'),
    ('TO', N'Tocantins')
) AS origem (sigla, nome)
ON destino.sigla = origem.sigla
WHEN MATCHED AND destino.nome <> origem.nome THEN
    UPDATE SET nome = origem.nome
WHEN NOT MATCHED BY TARGET THEN
    INSERT (sigla, nome) VALUES (origem.sigla, origem.nome);
GO

/* =========================================
   PARAMETROS (11 parâmetros do payload atual)
   codigo_parametro = valor de <param>_tipo_codigo no payload.
   valor_minimo / valor_maximo: faixa de validade física usada na validação
   de acurácia (fase 6). NULL = sem limite. Decisão D6 em
   docs/analise-implementacao.md: faixas aprovadas pelo time em 06/10/2026.
   Parâmetros novos são cadastrados pelo pipeline (fase 7), com faixa NULL.
========================================= */

MERGE dbo.Parametros AS destino
USING (VALUES
    --  codigo     nome                                         unidade    min     max
    ('TIP-TAG', N'Temperatura da água',                  N'°C',     0,      45),    -- proposta
    ('TIP-PH',  N'pH',                                   N'pH',     0,      14),    -- enunciado
    ('TIP-TMP', N'Temperatura do ar',                    N'°C',     -40,    60),    -- proposta
    ('TIP-UMI', N'Umidade relativa do ar',               N'%',      0,      100),   -- código Parte 1
    ('TIP-PRE', N'Pressão atmosférica ao nível do mar',  N'hPa',    870,    1085),  -- proposta (recordes mundiais)
    ('TIP-CHU', N'Precipitação',                         N'mm',     0,      NULL),  -- código Parte 1 (não negativo)
    ('TIP-VEN', N'Velocidade do vento',                  N'km/h',   0,      200),   -- proposta
    ('TIP-RAD', N'Radiação solar',                       N'W/m²',   0,      1500),  -- proposta
    ('TIP-OXI', N'Oxigênio dissolvido',                  N'mg/L',   0,      20),    -- proposta
    ('TIP-CON', N'Condutividade elétrica a 25 °C',       N'µS/cm',  0,      NULL),  -- código Parte 1 (não negativo)
    ('TIP-TUR', N'Turbidez',                             N'NTU',    0,      NULL)   -- código Parte 1 (não negativo)
) AS origem (codigo_parametro, nome, unidade_medida, valor_minimo, valor_maximo)
ON destino.codigo_parametro = origem.codigo_parametro
WHEN MATCHED AND (
       destino.nome <> origem.nome
    OR destino.unidade_medida <> origem.unidade_medida
    OR ISNULL(destino.valor_minimo, -1e308) <> ISNULL(CAST(origem.valor_minimo AS FLOAT), -1e308)
    OR ISNULL(destino.valor_maximo,  1e308) <> ISNULL(CAST(origem.valor_maximo AS FLOAT),  1e308)
) THEN
    UPDATE SET
        nome = origem.nome,
        unidade_medida = origem.unidade_medida,
        valor_minimo = origem.valor_minimo,
        valor_maximo = origem.valor_maximo
WHEN NOT MATCHED BY TARGET THEN
    INSERT (codigo_parametro, nome, unidade_medida, valor_minimo, valor_maximo)
    VALUES (origem.codigo_parametro, origem.nome, origem.unidade_medida,
            origem.valor_minimo, origem.valor_maximo);
GO
