-- Permissões do usuário só de leitura do agente analítico.
-- Políticas POL-01 (somente leitura) e POL-02 (dados pessoais) de
-- docs/agente/guardrails-e-owasp.md § 9, decisão L4 de 21/10/2026.
--
-- NÃO é uma migration: muda permissões, não a estrutura das tabelas, por isso
-- fica fora de sql/migrations e não altera sql/ddl_banco_relacional.sql.
-- Idempotente: GRANT e DENY repetidos não geram erro nem duplicam nada.
--
-- Passo 1 (uma vez, por quem administra o banco, com a senha FORA do Git):
--     Azure SQL Database (usuário contido no banco):
--         CREATE USER agente_leitura WITH PASSWORD = '<senha forte>';
-- Passo 2: executar este script no banco do projeto.
-- Passo 3: AGENTE_SQL_CONNECTIONSTRING no .env com UID=agente_leitura.
--
-- Por que não o papel db_datareader: ele dá leitura de TODAS as tabelas,
-- inclusive Operadores (CPF e nome com hash, e-mail criptografado). Aqui o
-- usuário recebe SELECT só nas tabelas que as ferramentas usam (menor privilégio).

IF DATABASE_PRINCIPAL_ID('agente_leitura') IS NULL
    THROW 50001, 'O usuário agente_leitura não existe. Crie-o antes (passo 1 acima e docs/manual-execucao.md § 4).', 1;
GO

-- Leitura só do que as ferramentas consultam (LeituraRepository, EstacaoRepository,
-- MunicipioRepository e ParametroRepository).
GRANT SELECT ON dbo.Estados TO agente_leitura;
GRANT SELECT ON dbo.Municipios TO agente_leitura;
GRANT SELECT ON dbo.Estacoes TO agente_leitura;
GRANT SELECT ON dbo.Parametros TO agente_leitura;
GRANT SELECT ON dbo.Leituras TO agente_leitura;
GRANT SELECT ON dbo.Leitura_Itens TO agente_leitura;
GO

-- POL-02: nada de operadores. A coluna Leituras.operador_id continua legível:
-- sem acesso a Operadores, o número sozinho não identifica ninguém, e um DENY
-- de coluna faz o SQL Server recusar até SELECT COUNT(*) FROM dbo.Leituras
-- (comportamento conferido no teste de integração em 21/10/2026).
DENY SELECT ON dbo.Operadores TO agente_leitura;
GO

-- POL-01: escrita e mudança de estrutura negadas explicitamente, mesmo que
-- algum papel conceda essas permissões no futuro (DENY vence GRANT).
DENY INSERT, UPDATE, DELETE, ALTER ON SCHEMA::dbo TO agente_leitura;
GO
