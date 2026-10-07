-- V001 — Chave natural de Leituras (decisão D1, aprovada em 05/10/2026).
-- codigo_registro = registro_codigo do payload ("Identificador da Leitura" do
-- enunciado). Garante que o mesmo registro nunca seja gravado duas vezes.
-- Idempotente: pode ser reexecutada sem erro.
-- NOT NULL direto só funciona porque Leituras estava vazia quando foi aplicada.

IF COL_LENGTH('dbo.Leituras', 'codigo_registro') IS NULL
    ALTER TABLE dbo.Leituras ADD codigo_registro VARCHAR(50) NOT NULL;
GO

IF OBJECT_ID('dbo.UQ_Leituras_CodigoRegistro', 'UQ') IS NULL
    ALTER TABLE dbo.Leituras
        ADD CONSTRAINT UQ_Leituras_CodigoRegistro UNIQUE (codigo_registro);
GO

-- Usado pela substituição de partição (estação + dia) na carga idempotente.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Leituras_Estacao_DataHora')
    CREATE INDEX IX_Leituras_Estacao_DataHora ON dbo.Leituras (estacao_id, data_hora);
GO
