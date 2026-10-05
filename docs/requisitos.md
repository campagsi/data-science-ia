# Requisitos do sistema

## Fonte normativa e escopo

O enunciado original em [projeto_modulo_1.md](projeto_modulo_1.md) é a referência para os requisitos da entrega. Este documento detalha esse escopo; requisitos técnicos adicionais são extensões e devem ser identificados como tais. As escolhas da Parte 2 ([projeto_final.pdf](projeto_final.pdf)) e o estado da implementação estão em [analise-implementacao.md](analise-implementacao.md).

O enunciado permite API REST pública ou JSON simulado e cita SQLite ou PostgreSQL. A implementação usa uma API FastAPI local que serve JSON simulado e Azure SQL. A fonte simulada se enquadra numa alternativa permitida; Azure SQL diverge das opções de banco e precisa de confirmação para a entrega.

## 1. Visão geral

O sistema tem como objetivo coletar, validar, persistir e analisar dados ambientais de estações de monitoramento. A solução deve funcionar como um pipeline de dados, permitindo a ingestão de informações vindas de fontes externas, a organização em banco relacional e a geração de indicadores estatísticos para apoio à análise.

O projeto é orientado a arquitetura em camadas e deve separar responsabilidades entre configuração, domínio, persistência, análise e relatório.

## 2. Objetivo do sistema

O sistema deve permitir que:

- as configurações do ambiente sejam carregadas de forma segura;
- os dados ambientais sejam coletados de uma API REST;
- os registros sejam validados antes de entrar no banco;
- os dados sejam salvos em estrutura relacional;
- métricas estatísticas sejam calculadas por estação, período e parâmetro;
- outliers e inconsistências sejam identificados;
- relatórios e resultados finais sejam gerados para análise humana.

## 3. Escopo

### 3.1 Fora do escopo

- interface gráfica de usuário;
- autenticação de usuários finais;
- dashboard interativo em tempo real;
- processamento de dados em streaming contínuo;
- deploy em ambiente de produção completo.

### 3.2 Dentro do escopo

- carregamento de credenciais e endpoints;
- ingestão de dados ambientais;
- validação e limpeza dos dados;
- persistência em banco de dados;
- consultas e análises estatísticas;
- geração de relatório final.

## 4. Requisitos funcionais

### RF01 - Carregamento de configuração
O sistema deve carregar as variáveis de ambiente e as credenciais necessárias para acessar as fontes e o banco de dados.

Critérios:
- ler arquivos de configuração e variáveis de ambiente;
- proteger dados sensíveis;
- falhar com mensagem clara se alguma informação obrigatória estiver ausente.

### RF02 - Ingestão de dados
O sistema deve obter dados ambientais de uma API REST pública ou de uma fonte JSON simulada. Na implementação atual, `FONTE_DADOS` aponta para a API FastAPI local do projeto, que disponibiliza o dataset JSON.

Critérios:
- realizar a leitura dos dados em formato estruturado;
- transformar os dados em registros utilizáveis pelo sistema;
- identificar falhas quando a fonte estiver indisponível ou retornar dados inválidos.

### RF03 - Validação de integridade dos dados
O sistema deve interpretar o JSON e tratar inconsistências da carga inicial, incluindo campos ausentes ou nulos, antes da persistência.

Critérios:
- converter o JSON em estruturas nativas do Python;
- aplicar regras explícitas para campos ausentes/nulos, distinguindo ausência de zero;
- não persistir valores inconsistentes sem tratamento.

Validação de campos obrigatórios, conversão de tipos e intervalos físicos são regras detalhadas em [contrato-dados.md](contrato-dados.md). Implementado na Parte 2: a validação devolve um resultado por registro, rejeita só a leitura ou a medição com problema, sem interromper o lote, e tudo o que não é importado vai para o log de rejeitados.

### RF04 - Tratamento de dados sensíveis
O sistema deve aplicar regras para reduzir ou eliminar dados sensíveis antes do armazenamento.

Critérios:
- remover ou anonimizar identificadores sensíveis;
- registrar quando houver necessidade de mascaramento;
- garantir que dados pessoais não sejam armazenados sem necessidade.

Implementado na Parte 2: CPF e nome do operador viram hash SHA-256 (ou HMAC-SHA256 com pepper), e o e-mail é criptografado de forma reversível (Fernet), tudo por `src/security.py`. Os originais não seguem para o banco nem para o log ([seguranca-lgpd.md](seguranca-lgpd.md)).

### RF05 - Persistência no banco
O sistema deve salvar os dados limpos em banco relacional SQLite ou PostgreSQL, conforme o enunciado original.

Critérios:
- manter, no mínimo, as tabelas relacionadas de estações e leituras temporais;
- inserir os dados usando scripts Python;
- registrar falhas de gravação com retorno de erro adequado.

A implementação atual usa Azure SQL e o modelo 3FN da Parte 2 (estados, municípios, estações, operadores, parâmetros, leituras e itens), mantido por scripts SQL ([modelagem-banco.md](modelagem-banco.md)). A idempotência, exigida no item 3.7 do projeto final, é garantida por `codigo_registro` único e pela substituição de partição estação + dia.

### RF06 - Consulta e recuperação de dados
O sistema deve consultar dados por estação e escrever consultas SQL com agregações por estação, junções (`JOIN`) e filtros por intervalo de datas.

Critérios:
- permitir filtros por período;
- recuperar dados por identificador da estação;
- demonstrar agregações SQL por estação e consultas com `JOIN`.

Consulta por cidade e operador é extensão do modelo atual, não requisito original.

### RF07 - Cálculo estatístico
O sistema deve calcular métricas estatísticas a partir dos dados persistidos.

Critérios:
- calcular média, mediana, desvio padrão e intervalo interquartil (IQR);
- identificar variações relevantes;
- calcular por parâmetro ambiental, com contexto de estação e período.

### RF08 - Identificação de outliers
O sistema deve identificar registros que estejam fora do padrão esperado.

Critérios:
- aplicar regras estatísticas sobre os dados;
- distinguir valores inconsistentes de valores normais;
- registrar os registros considerados atípicos.

### RF09 - Geração de relatório
O sistema deve apresentar no terminal ou em relatório textual os principais indicadores e resultados da análise.

Critérios:
- apresentar resultados em formato legível;
- incluir dados relevantes para tomada de decisão;
- disponibilizar o resultado em formato textual legível; exportação em arquivo é opcional.

### RF10 - Tratamento de erro e observabilidade (extensão do projeto)
O sistema deve registrar eventos de falha durante o processamento.

Critérios:
- registrar erros de conexão, validação, persistência e consulta;
- não expor credenciais em logs;
- manter rastreabilidade do fluxo executado.

Implementado: `src/logger.py` com log da execução (com o resumo da ingestão) e log de rejeitados, com data/hora, severidade e mensagem, sem dados pessoais nem credenciais.

## 5. Requisitos não funcionais e critérios técnicos complementares

Os itens seguintes detalham boas práticas para a solução. Quando não estiverem explicitamente no enunciado original, devem ser entendidos como critérios adicionais do projeto.

### RNF01 - Segurança
O sistema deve proteger informações sensíveis e evitar vazamento de credenciais.

### RNF02 - Manutenibilidade
A estrutura deve separar responsabilidades por camada e facilitar futuras alterações sem acoplar módulos.

### RNF03 - Confiabilidade
O fluxo deve tratar falhas de ingestão, validação e persistência sem quebrar o processo completo.

### RNF04 - Desempenho
O sistema deve processar volumes de dados esperados sem degradar excessivamente a execução do pipeline.

### RNF05 - Testabilidade
As etapas do pipeline devem ser testáveis separadamente, especialmente validação, persistência e análise.

### RNF06 - Portabilidade
O sistema deve funcionar em ambientes de execução compatíveis com Python e banco relacional, com ajustes mínimos de configuração.

## 6. Regras do domínio e extensões

As regras de integridade abaixo detalham o modelo relacional adotado. A idempotência passou a ser requisito no projeto final (item 3.7).

1. Toda estação deve pertencer a um município válido, e todo município a um estado cadastrado.
2. Toda leitura deve estar associada a uma estação existente.
3. Campos como temperatura, umidade, pressão, pH, oxigênio dissolvido, condutividade e turbidez devem ser validados antes da persistência.
4. Registros incompletos ou inválidos não devem ser armazenados sem tratamento.
5. Dados sensíveis devem ser removidos ou mascarados antes do armazenamento.
6. A análise deve considerar o contexto da estação e do período; agrupamento por cidade é uma extensão.
7. O sistema deve registrar falhas para facilitar manutenção e correção.
8. O processamento repetido do mesmo registro (`codigo_registro`) ou do mesmo período não deve criar uma nova leitura: as leituras de cada estação + dia do lote são substituídas.

## 7. Casos de uso principais

### UC01 - Carregar ambiente
O operador inicia a execução e o sistema carrega as configurações e credenciais.

### UC02 - Buscar dados ambientais
O sistema acessa a fonte de dados e coleta as informações necessárias.

### UC03 - Validar registros
O sistema verifica se cada dado atende às regras esperadas antes do armazenamento.

### UC04 - Persistir dados
O sistema salva as informações em banco relacional.

### UC05 - Consultar e analisar
O sistema recupera os dados e calcula métricas e indicadores.

### UC06 - Visualizar relatório final
O sistema apresenta os indicadores e resultados para o usuário ou responsável pela análise.

## 8. Critérios de aceitação

### Critério 1
A aplicação deve iniciar com configurações válidas e sem expor credenciais em logs ou código-fonte.

### Critério 2
Quando a fonte de dados estiver disponível, a ingestão deve ocorrer sem quebrar o fluxo.

### Critério 3
Dados inválidos devem ser rejeitados ou tratados antes da gravação.

### Critério 4
Quando a persistência for concluída, os dados devem poder ser consultados por estação e período.

### Critério 5
A análise deve gerar indicadores estatísticos e localizar outliers relevantes.

### Critério 6
O relatório final deve ser legível e refletir os resultados do processamento.

## 9. Conclusão

Os requisitos apontam para um sistema de processamento de dados ambientais em pipeline, com foco em confiabilidade, organização em camadas e análise estatística. O projeto deve priorizar robustez na ingestão, integridade dos dados e clareza na geração de indicadores, mantendo a operação segura e rastreável.
