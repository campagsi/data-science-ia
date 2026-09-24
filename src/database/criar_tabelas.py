from src.database.connection import DatabaseConnection

database = DatabaseConnection()


## Realiza a criação das tabelas no banco de dados caso não exista
def __criar_tabela_cidades():
    """
    Realiza a criação da tabela Cidades no banco de dados caso não exista
    """
    query = """
        IF OBJECT_ID('dbo.Cidades', 'U') IS NULL
        BEGIN
            CREATE TABLE Cidades (
                id INT IDENTITY(1, 1) PRIMARY KEY, 
                nome VARCHAR(100), 
                estado VARCHAR(2)
            );
        END;
        """
    database.execute(query)


def __criar_tabela_operadores():
    """
    Realiza a criação da tabela Operadores no banco de dados caso não exista
    """
    query = """
        IF OBJECT_ID('dbo.Operadores', 'U') IS NULL
        BEGIN
            CREATE TABLE Operadores (
                id INT IDENTITY(1, 1) PRIMARY KEY, 
                codigo VARCHAR(50), 
                nome VARCHAR(100), 
                tipo VARCHAR(50),
                cidade_id INT NOT NULL,

                CONSTRAINT FK_Operadores_Cidades FOREIGN KEY (cidade_id)
                    REFERENCES Cidades(id)
            );
        END;
        """
    database.execute(query)


def __criar_tabela_estacoes():
    """
    Realiza a criação da tabela Estacoes no banco de dados caso não exista
    """
    query = """
            IF OBJECT_ID('dbo.Estacoes', 'U') IS NULL
            BEGIN
                CREATE TABLE Estacoes (
                    id INT IDENTITY(1, 1) PRIMARY KEY, 
                    codigo VARCHAR(50), 
                    nome VARCHAR(100),
                    cidade_id INT NOT NULL,
                    operador_id INT NOT NULL,
                    latitude FLOAT,
                    longitude FLOAT,
                    ativa BIT,
                    tipo VARCHAR(50),

                    CONSTRAINT FK_Estacoes_Cidades FOREIGN KEY(cidade_id)
                        REFERENCES Cidades(id),
                    CONSTRAINT FK_Estacoes_Operadores FOREIGN KEY(operador_id)
                        REFERENCES Operadores(id)
                );
            END;

            IF COL_LENGTH('dbo.Leituras', 'fonte') IS NULL
            BEGIN
                ALTER TABLE Leituras ADD fonte VARCHAR(100) NULL;
            END;
        """
    database.execute(query)


def __criar_tabela_leituras():
    """
    Realiza a criação da tabela Leituras no banco de dados caso não exista
    """
    query = """
            IF OBJECT_ID('dbo.Leituras', 'U') IS NULL
            BEGIN
                CREATE TABLE Leituras (
                    id INT IDENTITY(1, 1) PRIMARY KEY, 
                    estacao_id INT NOT NULL, 
                    data_hora DATETIME NOT NULL,
                    temperatura FLOAT,
                    umidade FLOAT,
                    pressao FLOAT,
                    precipitacao FLOAT,
                    velocidade_vento FLOAT,
                    direcao_vento FLOAT,
                    radiacao_solar FLOAT,
                    temperatura_agua FLOAT,
                    ph FLOAT,
                    oxigenio_dissolvido FLOAT,
                    condutividade FLOAT,
                    turbidez FLOAT,
                    fonte VARCHAR(100) NOT NULL,

                    CONSTRAINT FK_Leituras_Estacoes FOREIGN KEY(estacao_id)
                        REFERENCES Estacoes(id)
                );
            END;              
        """
    database.execute(query)


def __excluir_tabelas():
    """Exclui as tabelas e seus dados"""
    query = """
        DROP TABLE IF EXISTS dbo.Leituras;
        DROP TABLE IF EXISTS dbo.Estacoes;
        DROP TABLE IF EXISTS dbo.Operadores;
        DROP TABLE IF EXISTS dbo.Cidades;
    """
    database.execute(query)


def criar_tabelas():
    """
    Função responsável por criar todas as tabelas necessárias no banco de dados
    """
    __criar_tabela_cidades()
    __criar_tabela_operadores()
    __criar_tabela_estacoes()
    __criar_tabela_leituras()


def recriar_tabelas():
    __excluir_tabelas()
    __criar_tabela_cidades()
    __criar_tabela_operadores()
    __criar_tabela_estacoes()
    __criar_tabela_leituras()


if __name__ == "__main__":
    recriar_tabelas()
