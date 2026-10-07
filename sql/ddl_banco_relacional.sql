-- DDL do banco relacional (CREATE TABLE, chaves e índices).
-- Fonte da verdade do schema: sempre reflete o banco com TODAS as migrations
-- de sql/migrations/ aplicadas. ATENÇÃO: apaga todas as tabelas e dados.
/* =========================================
   REMOVER TABELAS (ORDEM DAS DEPENDÊNCIAS)
   Filhas antes das mães; dbo.Cidades é do modelo antigo (Parte 1).
========================================= */
DROP TABLE IF EXISTS dbo.Leitura_Itens;
DROP TABLE IF EXISTS dbo.Leituras;
DROP TABLE IF EXISTS dbo.Parametros;
DROP TABLE IF EXISTS dbo.Estacoes;
DROP TABLE IF EXISTS dbo.Operadores;
DROP TABLE IF EXISTS dbo.Municipios;
DROP TABLE IF EXISTS dbo.Estados;
DROP TABLE IF EXISTS dbo.Cidades;
 
GO
 
/* =========================================
   ESTADOS
========================================= */
 
CREATE TABLE Estados
(
    id_estado INT IDENTITY(1,1) PRIMARY KEY,
 
    sigla CHAR(2) NOT NULL,
    nome VARCHAR(100) NOT NULL,
 
    CONSTRAINT UQ_Estados_Sigla UNIQUE (sigla),
    CONSTRAINT UQ_Estados_Nome UNIQUE (nome)
);
 
GO
 
/* =========================================
   MUNICIPIOS
========================================= */
 
CREATE TABLE Municipios
(
    id_municipio INT IDENTITY(1,1) PRIMARY KEY,
 
    nome VARCHAR(150) NOT NULL,
 
    estado_id INT NOT NULL,
 
    CONSTRAINT FK_Municipios_Estados
        FOREIGN KEY (estado_id)
        REFERENCES Estados(id_estado),
 
    CONSTRAINT UQ_Municipio_Estado
        UNIQUE (nome, estado_id)
);
 
GO
 
/* =========================================
   ESTACOES
========================================= */
 
CREATE TABLE Estacoes
(
    id_estacao INT IDENTITY(1,1) PRIMARY KEY,
 
    codigo_estacao VARCHAR(50) NOT NULL,
    nome VARCHAR(150) NOT NULL,
 
    municipio_id INT NOT NULL,
 
    latitude DECIMAL(10,7) NOT NULL,
    longitude DECIMAL(10,7) NOT NULL,
 
    CONSTRAINT UQ_Estacoes_Codigo
        UNIQUE (codigo_estacao),
 
    CONSTRAINT FK_Estacoes_Municipios
        FOREIGN KEY (municipio_id)
        REFERENCES Municipios(id_municipio),
 
    CONSTRAINT CK_Estacoes_Latitude
        CHECK (latitude BETWEEN -90 AND 90),
 
    CONSTRAINT CK_Estacoes_Longitude
        CHECK (longitude BETWEEN -180 AND 180)
);
 
GO
 
/* =========================================
   OPERADORES
========================================= */
 
CREATE TABLE Operadores
(
    id_operador INT IDENTITY(1,1) PRIMARY KEY,
 
    codigo_operador VARCHAR(50) NOT NULL,
 
    nome_hash VARCHAR(64) NOT NULL,
    cpf_hash VARCHAR(64) NOT NULL,
 
    municipio_id INT NOT NULL,
 
    -- Criptografia reversível (Fernet); migration V002.
    email_criptografado VARCHAR(255) NULL,
 
    CONSTRAINT UQ_Operadores_Codigo
        UNIQUE (codigo_operador),
 
    CONSTRAINT UQ_Operadores_CPF
        UNIQUE (cpf_hash),
 
    CONSTRAINT FK_Operadores_Municipios
        FOREIGN KEY (municipio_id)
        REFERENCES Municipios(id_municipio)
);
 
GO
 
/* =========================================
   PARAMETROS
========================================= */
 
CREATE TABLE Parametros
(
    id_parametro INT IDENTITY(1,1) PRIMARY KEY,
 
    codigo_parametro VARCHAR(50) NOT NULL,
    nome VARCHAR(100) NOT NULL,
 
    unidade_medida VARCHAR(30) NOT NULL,
 
    valor_minimo FLOAT NULL,
    valor_maximo FLOAT NULL,
 
    CONSTRAINT UQ_Parametros_Codigo
        UNIQUE (codigo_parametro),
 
    CONSTRAINT UQ_Parametros_Nome
        UNIQUE (nome)
);
 
GO
 
/* =========================================
   LEITURAS (CABECALHO)
========================================= */
 
CREATE TABLE Leituras
(
    id_leitura INT IDENTITY(1,1) PRIMARY KEY,
 
    operador_id INT NOT NULL,
    estacao_id INT NOT NULL,
 
    data_hora DATETIME2 NOT NULL,
 
    fonte VARCHAR(100) NOT NULL,
 
    data_ingestao DATETIME2 NOT NULL
        DEFAULT GETDATE(),
 
    -- registro_codigo do payload; chave natural (migration V001).
    codigo_registro VARCHAR(50) NOT NULL,
 
    CONSTRAINT UQ_Leituras_CodigoRegistro
        UNIQUE (codigo_registro),
 
    CONSTRAINT FK_Leituras_Operadores
        FOREIGN KEY (operador_id)
        REFERENCES Operadores(id_operador),
 
    CONSTRAINT FK_Leituras_Estacoes
        FOREIGN KEY (estacao_id)
        REFERENCES Estacoes(id_estacao)
);
 
GO
 
/* =========================================
   LEITURA_ITENS (DETALHE)
========================================= */
 
CREATE TABLE Leitura_Itens
(
    leitura_id INT NOT NULL,
    parametro_id INT NOT NULL,
 
    valor FLOAT NOT NULL,
 
    CONSTRAINT PK_Leitura_Itens
        PRIMARY KEY
        (
            leitura_id,
            parametro_id
        ),
 
    CONSTRAINT FK_LeituraItens_Leituras
        FOREIGN KEY (leitura_id)
        REFERENCES Leituras(id_leitura),
 
    CONSTRAINT FK_LeituraItens_Parametros
        FOREIGN KEY (parametro_id)
        REFERENCES Parametros(id_parametro)
);
 
GO
 
/* =========================================
   INDICES
========================================= */
 
CREATE INDEX IX_Municipios_Estado
ON Municipios (estado_id);
 
CREATE INDEX IX_Estacoes_Municipio
ON Estacoes (municipio_id);
 
CREATE INDEX IX_Operadores_Municipio
ON Operadores (municipio_id);
 
CREATE INDEX IX_Leituras_DataHora
ON Leituras (data_hora);
 
CREATE INDEX IX_Leituras_Estacao
ON Leituras (estacao_id);
 
CREATE INDEX IX_Leituras_Operador
ON Leituras (operador_id);
 
-- Substituição de partição (estação + dia) na carga idempotente; migration V001.
CREATE INDEX IX_Leituras_Estacao_DataHora
ON Leituras (estacao_id, data_hora);
 
CREATE INDEX IX_LeituraItens_Parametro
ON Leitura_Itens (parametro_id);
 
GO