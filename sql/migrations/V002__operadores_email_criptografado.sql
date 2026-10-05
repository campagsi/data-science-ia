-- V002 — E-mail do operador com criptografia reversível (decisão D7,
-- aprovada em 05/10/2026). O token Fernet (~140 caracteres) não cabe em
-- email_hash VARCHAR(64); o e-mail passa a ser gravado criptografado
-- (src/security.py, criptografar_email). Ver docs/seguranca-lgpd.md.
-- Idempotente: pode ser reexecutada sem erro.

IF COL_LENGTH('dbo.Operadores', 'email_hash') IS NOT NULL
    ALTER TABLE dbo.Operadores DROP COLUMN email_hash;
GO

IF COL_LENGTH('dbo.Operadores', 'email_criptografado') IS NULL
    ALTER TABLE dbo.Operadores ADD email_criptografado VARCHAR(255) NULL;
GO
