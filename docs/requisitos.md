# Requisitos do sistema

## 1. Visão geral

O sistema tem como objetivo coletar, validar, persistir e analisar dados ambientais de estações de monitoramento. A solução deve funcionar como um pipeline de dados, permitindo a ingestão de informações vindas de fontes externas, a organização em banco relacional e a geração de indicadores estatísticos para apoio à análise.

O projeto é orientado a arquitetura em camadas e deve separar responsabilidades entre configuração, domínio, persistência, análise e relatório.

## 2. Objetivo do sistema

O sistema deve permitir que:

- as configurações do ambiente sejam carregadas de forma segura;
- os dados ambientais sejam coletados de fontes como API REST ou arquivos JSON;
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
O sistema deve consumir dados ambientais de uma fonte externa, como API REST ou arquivo JSON.

Critérios:
- realizar a leitura dos dados em formato estruturado;
- transformar os dados em registros utilizáveis pelo sistema;
- identificar falhas quando a fonte estiver indisponível ou retornar dados inválidos.

### RF03 - Validação de integridade dos dados
O sistema deve normalizar e verificar se os dados recebidos possuem estrutura e tipo corretos antes de serem persistidos.

Critérios:
- validar campos obrigatórios;
- converter strings numéricas para tipos numéricos internos;
- converter strings booleanas para booleanos sem aceitar valores ambíguos;
- confirmar datas, identificadores e intervalos físicos;
- rejeitar registros incompletos ou inconsistentes.

### RF04 - Tratamento de dados sensíveis
O sistema deve aplicar regras para reduzir ou eliminar dados sensíveis antes do armazenamento.

Critérios:
- remover ou anonimizar identificadores sensíveis;
- registrar quando houver necessidade de mascaramento;
- garantir que dados pessoais não sejam armazenados sem necessidade.

### RF05 - Persistência no banco
O sistema deve salvar os dados validados em banco relacional.

Critérios:
- persistir informações de cidades, operadores, estações e leituras;
- manter relacionamento entre as entidades;
- impedir duplicidade por estação e instante de medição;
- registrar falhas de gravação com retorno de erro adequado.

### RF06 - Consulta e recuperação de dados
O sistema deve consultar os dados armazenados por estação, cidade, operador e intervalo de tempo.

Critérios:
- permitir filtros por período;
- recuperar dados por identificador da estação;
- suportar consultas simples e agregadas.

### RF07 - Cálculo estatístico
O sistema deve calcular métricas estatísticas a partir dos dados persistidos.

Critérios:
- calcular média, mediana e desvio padrão;
- identificar variações relevantes;
- possibilitar agrupamento por estação, cidade ou período.

### RF08 - Identificação de outliers
O sistema deve identificar registros que estejam fora do padrão esperado.

Critérios:
- aplicar regras estatísticas sobre os dados;
- distinguir valores inconsistentes de valores normais;
- registrar os registros considerados atípicos.

### RF09 - Geração de relatório
O sistema deve gerar um relatório final com os principais indicadores e resultados da análise.

Critérios:
- apresentar resultados em formato legível;
- incluir dados relevantes para tomada de decisão;
- permitir geração textual ou em arquivo exportável.

### RF10 - Tratamento de erro e observabilidade
O sistema deve registrar eventos de falha durante o processamento.

Critérios:
- registrar erros de conexão, validação, persistência e consulta;
- não expor credenciais em logs;
- manter rastreabilidade do fluxo executado.

## 5. Requisitos não funcionais

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

## 6. Regras de negócio

1. Toda estação deve pertencer a uma cidade válida.
2. Toda leitura deve estar associada a uma estação existente.
3. Campos como temperatura, umidade, pressão, pH, oxigênio dissolvido, condutividade e turbidez devem ser validados antes da persistência.
4. Registros incompletos ou inválidos não devem ser armazenados sem tratamento.
5. Dados sensíveis devem ser removidos ou mascarados antes do armazenamento.
6. A análise deve considerar o contexto de estação, cidade e período para produzir resultados relevantes.
7. O sistema deve registrar falhas para facilitar manutenção e correção.
8. O processamento repetido do mesmo par `estacao_codigo` e `data_hora` não deve criar uma nova leitura.

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
