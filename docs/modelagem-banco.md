# Modelo de Dados

## Visão Geral
O modelo foi estruturado de forma relacional, permitindo que uma cidade possua várias estações de monitoramento e que cada estação registre várias leituras ao longo do tempo.

A estrutura é composta por três entidades principais:

* `Cidades`
* `Estacoes`
* `Leituras`

## Diagrama de Classes
```mermaid
classDiagram

    Cidades "1" --> "0..*" Estacoes : possui
    Estacoes "1" --> "0..*" Leituras : gera

    class Cidades {
        +int id
        +String nome
        +String estado
    }

    class Estacoes {
        +int id
        +String codigo
        +String nome
        +int cidade_id
        +String operador
        +decimal latitude
        +decimal longitude
        +boolean ativa
    }

    class Leituras {
        +int id
        +int estacao_id
        +DateTime data_hora
        +decimal temperatura
        +decimal umidade
        +decimal pressao
        +decimal ph
        +decimal oxigenio_dissolvido
        +decimal condutividade
    }

    note for Cidades "PK: id"
    note for Estacoes "PK: id | FK: cidade_id | UNIQUE: codigo"
    note for Leituras "PK: id | FK: estacao_id"
```

## Considerações

O modelo foi estruturado para separar:

* informações geográficas;
* informações cadastrais das estações;
* dados temporais das medições.

Essa separação reduz a repetição de informações e permite que uma estação tenha um histórico de várias leituras sem precisar duplicar seus dados cadastrais.

A utilização de uma entidade específica para cidades também permite que várias estações compartilhem a mesma cidade sem repetir informações como nome e estado em cada registro.

A tabela de leituras concentra os valores obtidos ao longo do tempo, permitindo posteriormente realizar consultas, filtros e análises dos parâmetros ambientais.
