Projeto Prático Integrador: Pipeline de Monitoramento e Análise de Dados Ambientais

Objetivo Geral

Desenvolver uma aplicação completa em Python para capturar, tratar, analisar, persistir e disponibilizar dados de estações de monitoramento ambiental (qualidade da água e dados meteorológicos), aplicando boas práticas de código, segurança, estatística e controle de versão.

Enunciado e Requisitos do Projeto

1. Consumo de API & Tratamento de JSON (Módulos: Lógica Python e API JSON)

Consumir uma API REST pública (ou simulada via arquivo JSON) contendo leituras temporais de estações ambientais (ex: temperatura, pH, oxigênio dissolvido, condutividade).

Realizar o parsing do JSON em estruturas nativas do Python (lists, dicts).

Tratar inconsistências na carga inicial (como campos ausentes ou nulos).

2. Persistência de Dados e Consultas SQL (Módulo: Banco de Dados e SQL)

Criar um banco de dados relacional (SQLite ou PostgreSQL).

Estruturar o modelo relacional com pelo menos duas tabelas: estacoes (metadados das estações) e leituras (dados temporais).

Inserir os dados limpos no banco usando scripts Python.

Escrever consultas SQL essenciais: agregações por estação, junções (JOIN), e filtros por intervalo de datas.

3. Análise Estatística (Módulo: Estatística Básica)

Extrair os dados armazenados no SQL e calcular métricas estatísticas essenciais por parâmetro ambiental:

Tendência central: Média e Mediana.

Dispersão: Desvio Padrão e Intervalo Interquartil.

Identificar registros anômalos (outliers) utilizando a regra do amplitude interquartil (IQR).

4. Engenharia de Dados & Arquitetura (Módulo: Boas Práticas de Engenharia)

Organizar o projeto em uma estrutura de código modular (ex: src/ingestion, src/database, src/analytics).

Aplicar princípios de Clean Code (funções pequenas, nomes expressivos, tipagem explicativa) e tratamento de exceções (try/except) - se, assim, for necessario.

Utilizar o GitHub Copilot como assistente para geração de documentação (docstrings), criação de testes unitários para as funções de cálculo estatístico e otimização do código.

5. Segurança e Governança (Módulo: Governança e Segurança de Dados)

Garantir o gerenciamento seguro de credenciais e rotas de API utilizando variáveis de ambiente (.env e python-dotenv).

Implementar rotinas simples de anonimização ou exclusão de campos sensíveis de identificadores de operadores/estações (alinhado a diretrizes da LGPD).

6. Versionamento e Entrega (Módulo: Git / GitHub)

Criar um repositório Git local com fluxo de branches funcional (main, feature/ingestao, feature/sql, etc.).

Documentar todo o projeto no arquivo README.md com instruções de execução, arquitetura simplificada e decisões técnicas.

Subir o repositório no GitHub e realizar a entrega via Pull Request final.

Entregáveis Esperados

Repositório GitHub: Código estruturado, histórico de commits legível e README.md explicativo.

Banco de Dados Populado: Arquivo de banco de dados ou script DDL/DML automatizado.

Relatório Técnico/Apresentação: Demonstração prática do pipeline executando e exibindo as análises estatísticas geradas no terminal ou em relatório textual.