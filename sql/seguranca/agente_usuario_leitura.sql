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
-- usuário recebe SELECT só nas tabelas que as ferramentas usam (menor privilégio)
-- e, de Operadores, só as colunas do código (decisão de 23/10/2026).

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

-- POL-02: de Operadores, o agente lê só o código (codigo_operador, que identifica
-- o posto de trabalho e não é dado pessoal) e o id usado no JOIN com Leituras.
-- Nome e CPF (hash), e-mail (criptografado) e município do operador ficam negados
-- por coluna: DENY vence GRANT, mesmo que algum papel conceda leitura no futuro.
-- Cuidado: com coluna negada, o SQL Server recusa SELECT * e COUNT(*) na tabela;
-- por isso LeituraRepository.get_operadores() conta por COUNT(L.id_leitura).
-- O REVOKE tira o DENY da tabela inteira da versão anterior deste script; GRANT e
-- DENY de coluna vêm logo depois, então rodar de novo dá o mesmo resultado.
REVOKE SELECT ON dbo.Operadores FROM agente_leitura;
GRANT SELECT ON dbo.Operadores (id_operador, codigo_operador) TO agente_leitura;
DENY SELECT ON dbo.Operadores (nome_hash, cpf_hash, email_criptografado, municipio_id) TO agente_leitura;
GO

-- POL-01: escrita e mudança de estrutura negadas explicitamente, mesmo que
-- algum papel conceda essas permissões no futuro (DENY vence GRANT).
DENY INSERT, UPDATE, DELETE, ALTER ON SCHEMA::dbo TO agente_leitura;
GO
