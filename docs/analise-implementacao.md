# Análise da implementação atual

## 1. Objetivo e escopo

Este documento compara o fluxo de execução existente no projeto `Data-Science-Ia` com o fluxo definido em [docs/diagramas/diagrama-sequencia.md](diagramas/diagrama-sequencia.md).

O objetivo é registrar tudo que precisa ser ajustado para que o pipeline execute na ordem prevista, mantendo os nomes atuais de classes e métodos. A proposta é de refatoração do fluxo e de ligação entre as camadas. Não há proposta de renomear métodos existentes nem de reescrever a lógica estatística dos métodos de análise.

Quando um método existente possui uma incompatibilidade que impede o encadeamento, ela é apontada como bloqueio técnico. O método deve permanecer com seu nome e responsabilidade; o ajuste deve ser limitado ao contrato de chamada, ao encaminhamento dos dados ou à correção mínima necessária para que o fluxo consiga utilizá-lo.

## 2. Fluxo definido pelo diagrama

O diagrama estabelece esta sequência obrigatória:

```text
Usuário
  -> main.py.run_pipeline()
  -> config.py.load_config()
  -> data_client.py.fetch_data()
  -> normalization_service.py.normalize()
  -> validation_service.py.validate_data()
  -> models/estacao.py.validar_estacao()
  -> models/leitura.py.validar_leitura()
  -> leitura_repository.py.save_readings()
  -> database.py.connect()
  -> insert_estacao() e insert_leituras()
  -> analytics_service.py.calculate_metrics()
  -> leitura_repository.py.get_readings_by_station()
  -> media(), mediana(), desvio_padrao(), detectar_outliers()
  -> report_service.py.generate_report()
  -> Usuário
```

Esse fluxo representa um pipeline síncrono. Cada etapa deve devolver um resultado para a próxima; uma etapa não deve apenas imprimir dados ou encerrar o processo sem informar sucesso ou falha.

## 3. Fluxo real de execução hoje

O código não inicia pelo fluxo do diagrama. O arquivo `main.py` executa comandos no nível do módulo assim que é importado:

1. cria `AnaliticsService`;
2. chama `analisar_leituras_meteriologicas_cidade()`;
3. chama `analisar_leituras_qualidade_agua_cidade()`;
4. imprime os resultados da segunda análise;
5. mantém `criar_tabelas()` comentado.

O fluxo de ingestão só é iniciado separadamente por `src/ingestion/importar_dados.py`. Nesse módulo, `importar_dados()` faz o seguinte:

1. carrega `MOCK_API` com `getenv()`;
2. lê `src/api/data_set.json` quando `MOCK_API` está vazio;
3. ou chama `GET {MOCK_API}/api/v1/data-set`;
4. chama `importar_cidades()`;
5. chama `importar_operadores()`;
6. chama `importar_estacoes()`;
7. chama `importar_leituras()`.

Portanto, hoje não existe um único fluxo que faça ingestão, validação, persistência, consulta, análise e relatório. Há dois fluxos independentes: um de importação e outro de análise.

## 4. Matriz de atendimento ao diagrama

| Etapa do diagrama | Situação atual | O que precisa ser modificado no fluxo |
| --- | --- | --- |
| `main.py.run_pipeline()` | Não existe. O arquivo executa análise no nível do módulo. | Criar a orquestração `run_pipeline()` no ponto de entrada existente e mover para ela a ordem completa do processamento. Manter `main.py` como ponto de entrada. |
| `config.py.load_config()` | Não existe uma classe ou função com esse nome. `load_dotenv()` ocorre em módulos diferentes e as variáveis são lidas diretamente. | Centralizar o carregamento da configuração antes de qualquer cliente ou conexão. O resultado deve ser encaminhado para o restante do fluxo. |
| `data_client.py.fetch_data()` | Não existe. A função `importar_dados()` mistura leitura de arquivo, chamada HTTP e persistência. | Separar apenas o fornecimento de dados brutos da persistência. Reutilizar a regra atual de arquivo local/API, fazendo o resultado chegar à normalização. |
| `normalization_service.py.normalize()` | Não existe. Os modelos Pydantic fazem apenas conversões implícitas pontuais. | Inserir uma etapa explícita de normalização antes da criação dos modelos e antes da persistência. |
| `validation_service.py.validate_data()` | Não existe. Cada função de importação cria modelos isoladamente. | Inserir uma etapa única de validação do lote, mantendo os modelos existentes como fonte das validações estruturais. |
| `Estacao.validar_estacao()` | Não existe. `EstacaoModel` é somente um `BaseModel`. | Preservar `EstacaoModel` e conectar sua validação ao fluxo. Não criar uma segunda representação sem necessidade. |
| `Leitura.validar_leitura()` | Não existe. `LeituraModel` possui somente `field_validator` para valores vazios. | Preservar `LeituraModel` e usá-lo para validar cada leitura antes do repositório. |
| `leitura_repository.save_readings()` | Não existe. A persistência é dividida entre quatro `create_many()`. | Orquestrar os quatro repositórios atuais na ordem cidade, operador, estação e leitura. Se um método agregador for criado, ele deve apenas coordenar chamadas existentes. |
| `database.py.connect()` | Não existe com esse nome. `DatabaseConnection` abre uma conexão dentro de cada operação. | Manter `DatabaseConnection` e definir o ponto de conexão usado pela persistência. O fluxo deve garantir conexão e falha controlada antes dos inserts. |
| `insert_estacao()` | Não existe. `EstacaoRepository.create_many()` insere estações. | Encaminhar os dados para `EstacaoRepository.create_many()` sem renomear o método existente. |
| `insert_leituras()` | Não existe. `LeituraRepository.create_many()` está presente, mas hoje grava na tabela errada. | Encaminhar para `LeituraRepository.create_many()` e corrigir o bloqueio de tabela/entidade antes da integração. |
| `analytics_service.calculate_metrics()` | Não existe. A classe é `AnaliticsService` e possui quatro métodos públicos de análise. | `run_pipeline()` deve chamar os métodos existentes conforme o escopo escolhido. Não renomear `AnaliticsService` nem os métodos `analisar_*`. |
| `get_readings_by_station()` | Não existe com esse nome. Há consultas por cidade/estação e tipo em `LeituraRepository`. | Reutilizar os métodos existentes e encaminhar filtros de cidade/estação/período corretamente. |
| `media()`, `mediana()`, `desvio_padrao()`, `detectar_outliers()` | Não existem como métodos públicos separados. O cálculo está dentro de `__analisar_leituras()` e `__identificar_outliers()`. | Manter os métodos privados atuais como implementação dos cálculos. O fluxo deve consumir seus resultados por meio dos métodos `analisar_*`. |
| `report_service.generate_report()` | Não existe. `main.py` imprime DataFrames diretamente. | Criar a etapa de saída que receba estatísticas e outliers e gere o relatório textual/estruturado. |

## 5. Pontos em que o fluxo atual não atende

### 5.1 Orquestração e ponto de entrada

- `main.py` não possui `run_pipeline()`.
- A análise é executada antes da ingestão e não há garantia de que existam dados no banco.
- O resultado da análise meteorológica é sobrescrito pelo resultado da análise de qualidade da água.
- A criação das tabelas está comentada no arquivo de entrada.
- A execução de `main.py` captura `Exception`, imprime o erro e termina normalmente. Uma automação pode interpretar essa execução como sucesso.
- O fluxo de importação termina sem devolver quantidade de registros, entidades persistidas ou resultado para a análise.
- Não existe um resultado intermediário padronizado entre as etapas.

**Refatoração necessária:** transformar `main.py` em orquestrador explícito. A sequência mínima deve ser `load_config -> fetch_data -> normalize -> validate -> persist -> analyze -> report`. Cada chamada deve ser feita uma vez e seu retorno deve alimentar a etapa seguinte.

### 5.2 Configuração

O diagrama espera `config.py.load_config()`, mas a configuração está espalhada:

- `src/ingestion/importar_dados.py` chama `load_dotenv()` e lê `MOCK_API` no import do módulo;
- `src/database/connection.py` chama `load_dotenv()` e lê `AZURE_SQL_CONNECTIONSTRING` dentro de `DatabaseConnection`;
- não existe objeto único de configurações;
- não existe validação central de variáveis obrigatórias.

**Refatoração necessária:** carregar a configuração uma única vez no início de `run_pipeline()` e encaminhar os valores para o cliente e para a persistência. `DatabaseConnection` continua sendo a classe de acesso ao banco; a mudança é evitar que cada etapa descubra a configuração de forma independente.

### 5.3 Coleta dos dados

`importar_dados()` mistura três responsabilidades: obter dados, transformar dados e persistir dados. Isso impede o encadeamento representado no diagrama.

Pontos atuais:

- a URL local usa o arquivo `src/api/data_set.json`;
- a URL remota usa `MOCK_API` e o caminho `/api/v1/data-set`;
- não há validação de que o JSON recebido seja uma lista;
- não há retorno explícito chamado `raw_data` para a próxima etapa;
- a função captura `BaseException`, incluindo interrupções do processo, e converte tudo em `RuntimeError`;
- no bloco `__main__`, erros são apenas impressos.

**Refatoração necessária:** preservar a lógica de leitura local/API, mas deixar a coleta devolver os dados brutos. A chamada de `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()` deve ocorrer depois das etapas de normalização e validação, dentro da orquestração.

### 5.4 Normalização

O contrato recebe números, booleanos e data/hora como strings. O fluxo atual não possui `normalize()` e depende da coerção do Pydantic.

Não está garantido antes da persistência:

- remoção de espaços nos textos;
- conversão explícita de `operador_ativo` e `estacao_ativa`;
- conversão explícita de coordenadas e medições;
- conversão e padronização de `data_hora`;
- padronização de `cidade_estado`;
- rejeição de strings vazias nos campos obrigatórios;
- aplicação de uma convenção para horário sem fuso.

**Refatoração necessária:** adicionar a chamada de normalização entre coleta e validação. O método deve produzir registros com a mesma nomenclatura usada pelos modelos e pelas funções de importação. Não alterar os nomes `CidadeModel`, `OperadorModel`, `EstacaoModel`, `LeituraModel` ou das funções `importar_*`.

### 5.5 Validação e modelos

Os modelos existentes cobrem a forma básica das entidades, mas não representam toda a etapa do diagrama:

- `CidadeModel` valida apenas `nome` e `estado`;
- `OperadorModel` não recebe `operador_ativo`, embora o contrato o exija;
- `EstacaoModel` recebe os tipos internos, mas não valida limites de latitude/longitude nem strings vazias;
- `LeituraModel` exige `fonte`, mas `importar_leituras()` usa `item.get("fonte")`, o que pode gerar erro de validação se o campo faltar;
- `LeituraModel` converte string vazia para `None`, enquanto o contrato declara as medições obrigatórias;
- não existem métodos `validar_estacao()` ou `validar_leitura()` como descritos no diagrama;
- não existe um validador de lote que devolva registros válidos e erros identificáveis.

**Refatoração necessária:** inserir uma etapa `validate_data()` que crie os modelos e devolva o conjunto validado para a persistência. A validação deve acontecer antes de qualquer `create_many()`. Os nomes das classes e métodos existentes devem ser mantidos; métodos novos só devem atuar como coordenação da validação já feita pelos modelos.

### 5.6 Ordem e dependência da persistência

O código atual já possui uma ordem parcial correta:

```text
importar_cidades()
  -> importar_operadores()
  -> importar_estacoes()
  -> importar_leituras()
```

Essa ordem deve ser preservada porque as etapas seguintes procuram IDs gerados no banco. Entretanto, há problemas que impedem o fluxo completo:

- as tabelas precisam existir antes da primeira função de importação;
- os inserts são executados em conexões e commits separados;
- não existe transação única para cidade, operador, estação e leitura;
- não há garantia de que `get_by_name()` ou `get_by_codigo()` encontrou o registro antes de acessar `[...]`;
- não há idempotência para reprocessamento;
- `LeituraRepository.create_many()` insere em `operadores`, usando `OperadorModel`, em vez de inserir leituras;
- o schema não possui a coluna `fonte`, embora `LeituraModel` a exija;
- o schema não possui restrição única para `(estacao_id, data_hora)`;
- o campo `operador_ativo` não é persistido.

**Refatoração necessária:** o orquestrador deve garantir criação/verificação do schema, executar as quatro importações na ordem e só iniciar a análise depois que todas terminarem. A persistência deve retornar falha ao orquestrador, para impedir análise de lote parcialmente gravado.

### 5.7 Repositórios e acesso ao banco

`DatabaseConnection` oferece `execute()`, `execute_many()`, `fetch_one()` e `fetch_all()`, mas o diagrama usa nomes de outra abstração (`connect`, `insert_*`, `select_*`). O fluxo deve adaptar-se à implementação existente.

Bloqueios encontrados:

- `OperadorRepository.get_by_id()` chama `execute()` em um `SELECT`, em vez de `fetch_one()`;
- `OperadorRepository.get_by_id()` e `get_by_name()` montam retorno com chaves `estado`, que não correspondem ao operador;
- `OperadorRepository.create()` monta SQL por interpolação e aponta para `cidades`, apesar de ser um repositório de operadores;
- `EstacaoRepository.get_all()` devolve somente um dicionário da primeira linha, apesar do nome indicar lista;
- `LeituraRepository` contém métodos de operador/cidade copiados e não métodos de inserção de leitura coerentes;
- `LeituraRepository.create_many()` usa SQL de `operadores` e recebe `OperadorModel`;
- as consultas de leituras montam `params` com `data_inicio` e `data_fim` mesmo quando os filtros não foram adicionados à SQL;
- em consultas por cidade há uma vírgula ausente antes de `E.nome`;
- `get_leituras_qualidade_agua_by_cidade()` recebe o parâmetro chamado `estacao_id`, embora filtre por `E.cidade_id`;
- retornos `None` de consultas não são tratados uniformemente pelos consumidores.

**Refatoração necessária:** manter os nomes dos repositórios e dos métodos usados pela aplicação, corrigindo apenas os contratos que bloqueiam o fluxo. As consultas devem ser parametrizadas e os parâmetros devem corresponder às condições realmente adicionadas. A conexão deve ser obtida antes da persistência e os erros devem voltar para `run_pipeline()`.

### 5.8 Análise estatística

A análise existente está concentrada em `AnaliticsService`:

- `__preparar_dataframe()` converte medições para números;
- `__analisar_leituras()` calcula quantidade, média, mediana e desvio padrão;
- `__identificar_outliers()` calcula limites pelo IQR;
- os quatro métodos públicos `analisar_leituras_meteriologicas_cidade()`, `analisar_leituras_qualidade_agua_cidade()`, `analisar_leituras_meteriologicas_estacao()` e `analisar_leituras_qualidade_agua_estacao()` selecionam a consulta e o tipo de análise;
- `buscar_estacoes()` e `bucar_cidades()` consultam entidades auxiliares.

O diagrama cita `calculate_metrics()`, `media()`, `mediana()`, `desvio_padrao()` e `detectar_outliers()`, mas esses nomes não existem. Não se deve renomear os métodos atuais para satisfazer o diagrama. A adaptação deve ser feita no orquestrador ou por um método coordenador que consuma os quatro métodos públicos existentes.

Pontos que interrompem ou distorcem a execução:

- consultas que retornam `None` precisam chegar como lista vazia ao DataFrame;
- as consultas por estação não retornam o campo `estacao`, então o relatório de outliers não identifica a estação;
- `AnaliticsService` possui a grafia existente `Analitics` e `meteriologicas`; esses nomes devem ser preservados durante a refatoração;
- `__COLUNAS` e `__NOMES` estão anotados como dicionários de dicionários, mas armazenam tuplas em `__COLUNAS`;
- há um `print()` de unidades em `analisar_leituras_meteriologicas_estacao()`, o que mistura análise com saída de console;
- o fluxo atual executa duas análises, mas não consolida seus resultados.

**Refatoração necessária:** após a persistência, selecionar o escopo de análise, chamar os métodos públicos existentes e reunir estatísticas e outliers em um objeto único para o relatório. A lógica matemática privada deve continuar sendo usada.

### 5.9 Relatório e saída

`report_service.py` e `generate_report()` não existem. Atualmente `main.py` imprime um DataFrame e um DataFrame de outliers diretamente.

Isso não atende ao diagrama porque:

- não existe saída única do pipeline;
- não há separação entre cálculo e apresentação;
- o relatório meteorológico é sobrescrito pelo relatório de qualidade da água;
- não há formato estruturado para consumo posterior;
- erros de relatório não são diferenciados de erros de banco ou ingestão.

**Refatoração necessária:** criar uma etapa final de relatório que receba todos os indicadores produzidos por `AnaliticsService`, preserve estatísticas e outliers das duas categorias e devolva a saída ao usuário. A impressão atual pode ser reaproveitada dentro dessa etapa, mas não deve continuar no corpo principal de `main.py`.

## 6. Fluxo-alvo usando os nomes atuais

O fluxo pode atender ao diagrama sem renomear as classes e métodos atuais:

```text
main.py.run_pipeline()
  |
  +-- carregar configuração (.env, MOCK_API, AZURE_SQL_CONNECTIONSTRING)
  |
  +-- obter dados brutos (arquivo local ou requests.get usado por importar_dados)
  |
  +-- normalizar registros
  |
  +-- validar e construir:
  |     CidadeModel
  |     OperadorModel
  |     EstacaoModel
  |     LeituraModel
  |
  +-- persistir na ordem existente:
  |     importar_cidades()
  |     importar_operadores()
  |     importar_estacoes()
  |     importar_leituras()
  |
  +-- analisar dados persistidos:
  |     AnaliticsService.analisar_leituras_meteriologicas_cidade()
  |     AnaliticsService.analisar_leituras_qualidade_agua_cidade()
  |     [ou os equivalentes por estação]
  |
  +-- consolidar estatísticas e outliers
  |
  +-- gerar relatório final
  |
  +-- retornar sucesso ou erro ao usuário/sistema operacional
```

A separação acima é de fluxo. As funções `importar_*` continuam responsáveis pelos seus inserts e os métodos `analisar_*` continuam responsáveis pelo cálculo; o que muda é quando e como são chamados.

## 7. Lista completa de modificações de fluxo

### 7.1 Preparação

1. Definir `main.py` como único ponto de entrada do pipeline.
2. Criar `run_pipeline()` como coordenador, sem executar análise durante o import do módulo.
3. Garantir que as tabelas sejam criadas ou verificadas antes da ingestão.
4. Carregar configuração antes de instanciar cliente HTTP ou `DatabaseConnection`.
5. Padronizar o retorno de sucesso, quantidade processada e falha.

### 7.2 Entrada e transformação

1. Obter `raw_data` de arquivo ou API sem persistir nessa etapa.
2. Confirmar que a fonte devolveu uma lista de registros.
3. Executar a normalização antes de instanciar os modelos.
4. Validar o lote completo e separar registros válidos de erros.
5. Não chamar nenhum `create_many()` quando o lote não estiver validado.
6. Encaminhar os mesmos nomes de campos usados no JSON para as funções `importar_*`.

### 7.3 Persistência

1. Executar `importar_cidades()` antes das demais entidades.
2. Executar `importar_operadores()` depois de cidades.
3. Executar `importar_estacoes()` depois de operadores.
4. Executar `importar_leituras()` por último.
5. Interromper o pipeline se qualquer etapa falhar.
6. Garantir que a leitura use a estação persistida e que a estação use cidade e operador existentes.
7. Corrigir o encaminhamento de `LeituraRepository.create_many()` para a tabela e os campos de leitura.
8. Garantir que o schema aceite `fonte` e os demais campos realmente enviados.
9. Definir a estratégia de reprocessamento antes de chamar novamente a ingestão.

### 7.4 Consulta e análise

1. Só iniciar `AnaliticsService` depois da persistência concluída.
2. Escolher explicitamente o escopo: cidade ou estação.
3. Encaminhar corretamente `cidade_id`/`estacao_id`, `data_inicio` e `data_fim`.
4. Garantir que cada consulta devolva lista, inclusive quando não houver dados.
5. Executar as análises meteorológica e de qualidade da água sem sobrescrever seus resultados.
6. Consolidar os retornos dos métodos `analisar_*` para o relatório.

### 7.5 Relatório e encerramento

1. Encaminhar o resultado consolidado para a etapa de relatório.
2. Preservar estatísticas, outliers, período e escopo da consulta.
3. Exibir ou salvar o relatório somente depois de todas as análises.
4. Retornar código de erro diferente de zero quando houver falha de configuração, fonte, validação, banco, análise ou relatório.
5. Não imprimir credenciais nem detalhes de conexão nos erros.

## 8. Bloqueios que precisam ser resolvidos para o fluxo executar

Estes itens não são mudanças de nome ou de desenho da lógica de negócio. São incompatibilidades atuais que impedem o encadeamento descrito:

1. `main.py` não chama ingestão e análise em uma sequência única.
2. Não existem `config.py`, `data_client.py`, `normalization_service.py`, `validation_service.py` e `report_service.py`.
3. `LeituraRepository.create_many()` grava no destino errado e usa o modelo errado.
4. O schema de `Leituras` não possui `fonte`.
5. As consultas de `LeituraRepository` possuem parâmetros extras e uma consulta com erro de sintaxe.
6. `OperadorRepository.get_by_id()` executa `SELECT` pelo método de escrita.
7. A persistência não é transacional entre as quatro entidades.
8. Não há estratégia de idempotência para leituras.
9. Os dados retornados por alguns repositórios não têm o formato esperado pelos consumidores.
10. O cálculo por estação não preserva o nome da estação no resultado de outliers.
11. Não existe geração de relatório consolidado.
12. O tratamento de erro do ponto de entrada não sinaliza falha ao sistema operacional.

## 9. Itens que não devem ser alterados na refatoração

Para preservar o código existente e a compatibilidade com as chamadas atuais:

- manter `AnaliticsService` com a grafia atual;
- manter `analisar_leituras_meteriologicas_cidade()`;
- manter `analisar_leituras_qualidade_agua_cidade()`;
- manter `analisar_leituras_meteriologicas_estacao()`;
- manter `analisar_leituras_qualidade_agua_estacao()`;
- manter `importar_dados()`, `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()`;
- manter `CidadeRepository`, `OperadorRepository`, `EstacaoRepository`, `LeituraRepository` e `DatabaseConnection`;
- manter os modelos `CidadeModel`, `OperadorModel`, `EstacaoModel` e `LeituraModel`;
- manter `__analisar_leituras()` e `__identificar_outliers()` como implementação dos cálculos;
- não substituir a análise por outra biblioteca ou algoritmo;
- não transformar o pipeline em uma API web: a API FastAPI existente é fonte do dataset, não o orquestrador do processamento.

## 10. Plano de refatoração por fases

As fases abaixo devem ser executadas na ordem indicada. Cada fase possui um objetivo isolado, os arquivos envolvidos, os métodos que precisam existir e um critério objetivo para revisão. A fase seguinte só deve começar quando o critério da fase anterior estiver atendido.

### Fase 0 - Congelar o comportamento atual

**Objetivo:** registrar o ponto de partida antes de alterar o fluxo.

**O que será feito:**

1. Executar a compilação dos módulos Python.
2. Registrar quais imports funcionam sem conexão com o banco.
3. Registrar as assinaturas atuais de `importar_dados()`, `importar_cidades()`, `importar_operadores()`, `importar_estacoes()`, `importar_leituras()` e dos métodos públicos de `AnaliticsService`.
4. Separar falhas de ambiente, como ausência de `.env` ou conexão, de falhas de código.
5. Não modificar regras de negócio nesta fase.

**Arquivos envolvidos:** `main.py`, `src/ingestion/importar_dados.py`, `src/services/analytics_service.py` e módulos de persistência.

**Critério de revisão:** existe um registro claro do comportamento atual e a equipe consegue distinguir erro de fluxo de erro de infraestrutura.

**Resultado executado em 23/09/2026:**

- `python -m compileall -q Data-Science-Ia\src Data-Science-Ia\main.py`: concluído sem erros de sintaxe;
- dependências `dotenv`, `mssql_python`, `requests`, `pydantic`, `pandas` e `fastapi`: disponíveis no ambiente virtual;
- arquivo `.env`: encontrado com as chaves `AZURE_SQL_CONNECTIONSTRING` e `MOCK_API`, sem registrar os valores sensíveis;
- imports de `src.models`, `src.repository`, `src.services.analytics_service`, `src.ingestion.importar_dados` e `src.database.connection`: concluídos;
- assinaturas confirmadas: `importar_dados()`, `importar_cidades(dados)`, `importar_operadores(dados)`, `importar_estacoes(dados)`, `importar_leituras(dados)` e os quatro métodos públicos `analisar_*` de `AnaliticsService`;
- `main.py` não declara `run_pipeline()` e executa análise durante o import;
- importar `main.py` tentou consultar o Azure SQL, falhou com timeout do driver e imprimiu `RuntimeError`, mas o processo terminou com status `0`.

**Classificação do baseline:** a sintaxe e as dependências locais estão adequadas. O timeout do Azure SQL é uma falha de infraestrutura/conectividade para essa execução. Já a consulta durante o import de `main.py` e o status de sucesso após a falha são falhas de fluxo e controle de erro que devem ser tratadas nas Fases 1 e 10.

### Fase 1 - Transformar `main.py` no orquestrador

**Objetivo:** fazer o ponto de entrada executar uma única sequência, sem análise durante o import do módulo.

**Métodos a criar ou organizar:**

```python
def run_pipeline() -> dict:
  """Coordena configuração, ingestão, validação, persistência, análise e relatório."""
```

**O que será feito:**

1. Mover o código atualmente executado no nível do módulo para dentro de `run_pipeline()`.
2. Remover a atribuição duplicada de `analise, outliers`, preservando os dois resultados.
3. Fazer o bloco `if __name__ == "__main__":` chamar somente `run_pipeline()`.
4. Não instanciar `AnaliticsService` quando `main.py` for apenas importado.
5. Definir um retorno estruturado para sucesso, por exemplo com dados persistidos, indicadores e relatório.
6. Deixar exceções subirem até um único ponto de tratamento, que deverá retornar código de falha ao sistema operacional.

**Dependências:** nenhuma fase funcional anterior.

**Critério de revisão:** importar `main.py` não executa consultas; executar o arquivo chama uma única função coordenadora.

**Implementação concluída:**

- `run_pipeline()` foi criado em `main.py`;
- a instanciação de `AnaliticsService` e as consultas foram movidas para dentro do método;
- os resultados meteorológicos e de qualidade da água passaram a ser preservados em grupos separados;
- `_exibir_resultados()` foi criado para manter a apresentação fora da coordenação do pipeline;
- o bloco `if __name__ == "__main__":` agora é o único ponto que inicia a execução;
- importar `main.py` não executa consultas nem acessa o banco;
- falhas na execução do script são enviadas para `stderr` e terminam com `SystemExit(1)`;
- `run_pipeline()` mantém as exceções para o chamador, sem mascarar falhas.

**Validação executada:** `py_compile` passou; o import de `main.py` retornou `IMPORT_OK` e confirmou `run_pipeline`; o teste controlado de falha confirmou propagação da exceção com código de processo `1`; os diagnósticos do arquivo não apontaram erros.

### Fase 2 - Criar a camada de configuração

**Objetivo:** atender à chamada `Main -> Config: load_config()` do diagrama.

**Novo arquivo sugerido:** `src/config.py`.

**Método a criar:**

```python
def load_config() -> dict:
  """Carrega e valida MOCK_API e AZURE_SQL_CONNECTIONSTRING."""
```

**O que será feito:**

1. Carregar o `.env` em um único ponto.
2. Ler `MOCK_API` e `AZURE_SQL_CONNECTIONSTRING`.
3. Definir quais valores são obrigatórios no modo API e no modo arquivo local.
4. Devolver `settings` para `run_pipeline()`.
5. Não registrar credenciais ou a string completa de conexão nos logs.
6. Ajustar `DatabaseConnection` para receber ou utilizar a configuração sem repetir a descoberta de ambiente em cada etapa.

**Métodos existentes preservados:** `DatabaseConnection.__init__()` continuará existindo; a mudança é fazer sua configuração ser previsível.

**Dependências:** Fase 1.

**Critério de revisão:** uma configuração inválida falha antes da tentativa de acessar a API ou o banco, com mensagem sem segredo.

**Implementação concluída:**

- `src/config.py` passou a centralizar o carregamento do arquivo `.env`;
- `Settings` passou a disponibilizar `mock_api` e `azure_sql_connectionstring`;
- `MOCK_API` e `AZURE_SQL_CONNECTIONSTRING` são validadas antes da execução do pipeline;
- `MOCK_API` tornou-se obrigatória, pois a ingestão depende exclusivamente da API;
- o caminho `dataset_path` foi removido da configuração;
- nenhum valor sensível é registrado nas mensagens de erro ou de validação;
- `DataClient` deixou de possuir leitura direta do arquivo JSON e sempre consulta o endpoint da API;
- a configuração é carregada no início de `run_pipeline()` e encaminhada para `DataClient`;
- a fachada legada `importar_dados()` também utiliza `load_config()` e `DataClient`.

**Validação executada:**

- compilação dos módulos Python concluída sem erros;
- assinatura de `Settings` confirmada sem o campo `dataset_path`;
- ausência de `__read_local_dataset` confirmada em `DataClient`;
- diagnósticos dos arquivos alterados não apontaram erros;
- referências do pipeline ao arquivo local foram removidas;
- a documentação de execução foi atualizada para indicar a API como única fonte de dados.

### Fase 3 - Separar a coleta de dados da persistência

**Objetivo:** atender à chamada `Main -> Client: fetch_data()` e produzir `raw_data` sem gravar dados.

**Novo arquivo sugerido:** `src/ingestion/data_client.py`.

**Classe e método sugeridos:**

```python
class DataClient:
  def fetch_data(self) -> list[dict]:
    """Consulta exclusivamente a API configurada."""
```

**O que será feito:**

1. Mover a chamada `requests.get()` para `DataClient.fetch_data()`.
2. Consultar exclusivamente o endpoint `{MOCK_API}/api/v1/data-set`.
3. Falhar quando `MOCK_API` não estiver configurada ou quando a API estiver indisponível.
4. Validar que a resposta é uma lista antes de devolvê-la.
5. Preservar `importar_dados()` como método público compatível, fazendo-o delegar à nova sequência ou mantendo-o como fachada temporária.
6. Remover de `importar_dados()` a chamada direta às quatro funções de persistência quando o pipeline estiver usando a nova orquestração.

**Dependências:** Fase 2.

**Critério de revisão:** `fetch_data()` devolve dados brutos exclusivamente da API e não chama nenhum repository nem `create_many()`.

**Implementação concluída:**

- `DataClient.fetch_data()` ficou responsável exclusivamente pela consulta HTTP ao endpoint `{MOCK_API}/api/v1/data-set`;
- a resposta da API continua sendo validada como uma lista de objetos antes de seguir para o pipeline;
- erros HTTP e de conexão da API interrompem a coleta e são propagados ao chamador;
- `importar_dados()` foi mantida como fachada pública, mas agora apenas carrega a configuração, consulta o `DataClient` e retorna os dados brutos;
- a fachada `importar_dados()` deixou de chamar `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()`;
- a persistência continua explícita no `run_pipeline()`, depois da normalização e da validação;
- as funções públicas de persistência foram preservadas para manter os nomes e contratos existentes;
- o bloco executável de `importar_dados.py` agora informa somente a quantidade de registros recebidos da API.

**Validação executada:**

- compilação dos módulos Python concluída sem erros;
- teste controlado confirmou que `importar_dados()` retorna os dados recebidos;
- teste controlado confirmou que `DataClient.fetch_data()` é chamado uma vez;
- teste controlado confirmou que nenhuma função `importar_*` de persistência é chamada pela fachada;
- diagnósticos do arquivo alterado não apontaram erros.

### Fase 4 - Criar a normalização explícita

**Objetivo:** atender à chamada `Main -> Normalizer: normalize(raw_data)` antes da validação.

**Novo arquivo sugerido:** `src/services/normalization_service.py`.

**Classe e método sugeridos:**

```python
class NormalizationService:
  def normalize(self, raw_data: list[dict]) -> list[dict]:
    """Converte e padroniza os registros brutos."""
```

**O que será feito:**

1. Remover espaços extras de códigos, nomes, tipos, estado e `fonte`.
2. Converter campos numéricos e coordenadas para `float`.
3. Converter `operador_ativo` e `estacao_ativa` para `bool` sem aceitar valores ambíguos.
4. Converter `data_hora` para `datetime`.
5. Padronizar `cidade_estado` em letras maiúsculas.
6. Manter exatamente os nomes de campos esperados pelas funções `importar_*`.
7. Devolver uma lista nova, sem alterar silenciosamente o payload original.

**Métodos existentes preservados:** o `field_validator` de `LeituraModel` continua funcionando, mas deixa de ser a única etapa de conversão.

**Dependências:** Fase 3.

**Critério de revisão:** um registro normalizado não depende de coerção implícita para chegar aos tipos internos esperados.

**Implementação concluída:**

- `NormalizationService.normalize()` passou a validar que o payload recebido é uma lista;
- cada registro também é validado como um objeto/dicionário antes do processamento;
- campos textuais continuam sendo copiados e tratados com `strip()`;
- campos numéricos são convertidos explicitamente para `float`;
- strings numéricas vazias ou compostas apenas por espaços são normalizadas para `None`;
- `operador_ativo` e `estacao_ativa` continuam aceitando somente representações booleanas conhecidas;
- `data_hora` continua sendo convertida explicitamente a partir do formato ISO;
- `cidade_estado` continua sendo padronizada em letras maiúsculas quando informada;
- o payload original não é alterado, pois cada registro é copiado antes da normalização;
- os nomes dos campos recebidos da API são preservados para as etapas de validação e persistência.

**Validação executada:**

- teste controlado confirmou a conversão de textos, números, booleanos e data/hora;
- teste controlado confirmou o tratamento de valores numéricos vazios;
- teste controlado confirmou a padronização de `cidade_estado`;
- teste controlado confirmou que o registro original permanece inalterado;
- compilação e diagnósticos do serviço concluídos sem erros.

### Fase 5 - Criar a validação compatível com os modelos

**Objetivo:** atender à chamada `Main -> Validator: validate_data(normalized_data)`.

**Novo arquivo sugerido:** `src/services/validation_service.py`.

**Classe e métodos sugeridos:**

```python
class ValidationService:
  def validate_data(self, normalized_data: list[dict]) -> list[dict]:
    """Valida o lote e devolve somente registros aptos à persistência."""

  def validar_estacao(self, registro: dict) -> EstacaoModel:
    """Cria e valida um EstacaoModel."""

  def validar_leitura(self, registro: dict, estacao_id: int) -> LeituraModel:
    """Cria e valida um LeituraModel associado à estação."""
```

**O que será feito:**

1. Validar campos obrigatórios antes dos inserts.
2. Instanciar `CidadeModel`, `OperadorModel`, `EstacaoModel` e `LeituraModel` com os dados normalizados.
3. Aplicar os limites de latitude, longitude, umidade, direção do vento, pH e valores não negativos definidos no contrato.
4. Preservar os métodos `validar_estacao()` e `validar_leitura()` como métodos de coordenação mesmo que inicialmente deleguem diretamente ao Pydantic.
5. Devolver erros com o índice do registro e o campo inválido.
6. Impedir que qualquer `create_many()` seja chamado se a política escolhida for rejeição do lote inteiro.
7. Manter a associação entre os dados do registro bruto e as entidades tipadas necessárias à persistência.

**Dependências:** Fase 4.

**Critério de revisão:** dados inválidos falham antes do primeiro insert e a validação pode ser testada sem conexão com o banco.

**Implementação concluída:**

- `ValidationService.validate_data()` passou a exigir todos os campos definidos como obrigatórios no contrato de dados;
- `operador_ativo` e `estacao_ativa` passaram a ser exigidos no lote validado;
- os campos numéricos obrigatórios são conferidos após a normalização;
- `cidade_estado` é validada como uma sigla alfabética de duas letras;
- latitude e longitude são validadas nos intervalos `[-90, 90]` e `[-180, 180]`;
- umidade, direção do vento e pH são validados nos intervalos definidos pelo contrato;
- precipitação, radiação solar, oxigênio dissolvido, condutividade e turbidez não podem ser negativos;
- valores numéricos devem ser finitos;
- `validar_estacao()` continua delegando a construção da estação ao `EstacaoModel`;
- `validar_leitura()` continua delegando a construção da leitura ao `LeituraModel`;
- a política adotada rejeita o lote inteiro quando qualquer registro é inválido;
- códigos repetidos são permitidos quando representam a mesma entidade em leituras diferentes;
- códigos de operador ou estação associados a dados conflitantes no mesmo lote são rejeitados;
- nenhum repositório é acessado durante a validação.

**Validação executada:**

- lote válido com duas leituras da mesma estação aceito;
- registro sem campo obrigatório rejeitado;
- valor de pH fora do intervalo rejeitado;
- conflito de identidade para o mesmo código de estação rejeitado;
- compilação e diagnósticos do serviço concluídos sem erros.

**Ajuste posterior (medições opcionais):**

- motivo: o dataset da API tem 82 registros (de 5.520) com uma medição ausente, e a exigência de todas as medições fazia `validate_data()` rejeitar o lote inteiro (pendência da Fase 7);
- as 12 medições foram retiradas de `_REQUIRED_FIELDS`; `__validate_ranges()` passou a ignorar medições nulas ou sem a chave. Medição informada continua sujeita aos intervalos do contrato, e a rejeição do lote inteiro por registro inválido foi mantida;
- `LeituraModel`, `importar_leituras()` e as colunas de medição de `Leituras` já aceitavam nulos, então nenhuma outra camada foi alterada;
- arquivos alterados: `src/services/validation_service.py`, [contrato-dados.md](contrato-dados.md), [dicionario-dados.md](dicionario-dados.md) e [arquitetura.md](arquitetura.md);
- validação: o dataset atual passado por `normalize()` e `validate_data()` resultou em 5.520 registros válidos, sem rejeição do lote.

### Fase 6 - Organizar a persistência e os métodos-ponte do diagrama

**Objetivo:** atender à sequência `save_readings() -> connect() -> insert_estacao() -> insert_leituras()` usando os repositórios existentes.

**Métodos de coordenação sugeridos:**

```python
class LeituraRepository:
  def save_readings(self, registros_ok: list[dict]) -> dict:
    """Coordena a persistência das entidades na ordem correta."""
```

```python
class DatabaseConnection:
  def connect(self):
    """Abre a conexão usada pela unidade de persistência."""
```

```python
class EstacaoRepository:
  def insert_estacao(self, estacoes):
    """Método-ponte compatível com o diagrama; delega ao insert existente."""
```

```python
class LeituraRepository:
  def insert_leituras(self, leituras):
    """Método-ponte compatível com o diagrama; delega a create_many()."""
```

**O que será feito:**

1. Manter `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()` com os nomes atuais.
2. Fazer `save_readings()` coordenar essas funções ou os repositories equivalentes, na ordem cidade, operador, estação e leitura.
3. Criar os métodos-ponte do diagrama mesmo que a primeira implementação apenas delegue a `create_many()`.
4. Corrigir `LeituraRepository.create_many()` para inserir em `Leituras` com `LeituraModel`.
5. Corrigir consultas de dependência para tratar cidade, operador e estação inexistentes antes de acessar IDs.
6. Corrigir `OperadorRepository.get_by_id()` para usar `fetch_one()`.
7. Corrigir os parâmetros condicionais das consultas de `LeituraRepository`.
8. Corrigir a consulta por cidade que possui separação incorreta antes de `E.nome`.
9. Definir a transação e o rollback do lote.
10. Implementar a chave de idempotência `(estacao_id, data_hora)` no schema e no insert.

**Dependências:** Fases 2, 5 e schema compatível.

**Critério de revisão:** nenhum dado é persistido antes da validação; uma falha interrompe o lote; leituras repetidas não criam duplicidade.

**Implementação concluída:**

- `DatabaseConnection.connect()` foi criado como método de compatibilidade para abertura explícita da conexão;
- `EstacaoRepository.insert_estacao()` foi criado como ponte para `create_many()`;
- `LeituraRepository.insert_leituras()` foi criado como ponte para `create_many()`;
- `LeituraRepository.save_readings()` passou a coordenar a persistência na ordem `cidades -> operadores -> estações -> leituras`;
- `main.py` passou a chamar uma única unidade de persistência depois da normalização e da validação;
- os métodos públicos `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()` foram preservados;
- os caches de cidade, operador e estação são limpos antes de cada lote para evitar referências obsoletas;
- a persistência agora falha explicitamente quando uma cidade, operador ou estação necessária não é encontrada;
- `LeituraRepository.create_many()` continua gravando `LeituraModel` na tabela `Leituras`;
- a ordem de dependência das entidades permanece explícita e interrompe o lote quando uma etapa falha.

**Validação executada:**

- teste controlado confirmou a ordem `cidades -> operadores -> estações -> leituras`;
- teste controlado confirmou o retorno da quantidade de registros processados;
- compilação dos módulos Python concluída sem erros;
- diagnósticos dos arquivos alterados não apontaram erros.

**Limitação registrada para a Fase 7:** a conexão ainda é aberta individualmente pelas operações existentes, e a transação única e a idempotência física por `(estacao_id, data_hora)` dependem do alinhamento do schema e da conexão na próxima fase. *Transação única resolvida na Fase 7; idempotência física pendente.*

### Fase 7 - Alinhar schema e conexão do banco

**Objetivo:** garantir que a persistência tenha o contrato físico necessário para executar.

**Arquivos envolvidos:** `src/database/criar_tabelas.py`, `src/database/connection.py` e repositories.

**O que será feito:**

1. Adicionar `fonte` em `Leituras`.
2. Adicionar `ativo` em `Operadores`, caso o contrato permaneça obrigatório.
3. Aplicar `NOT NULL` aos campos realmente obrigatórios.
4. Adicionar unicidade para códigos de operadores e estações.
5. Adicionar unicidade para `(estacao_id, data_hora)`.
6. Ajustar tipos e limites conforme o contrato de dados.
7. Preservar `DatabaseConnection.execute()`, `execute_many()`, `fetch_one()` e `fetch_all()`.
8. Criar `connect()` como método de compatibilidade, sem remover os métodos atuais.
9. Garantir que `criar_tabelas()` seja chamado antes da ingestão, sem recriar tabelas destrutivamente por padrão.

**Dependências:** Fase 6 para que o schema seja validado pelos inserts reais.

**Critério de revisão:** o schema aceita todos os campos dos modelos e rejeita duplicidades de leitura no banco.

**Implementação parcial** (somente conexão e transação; o schema foi mantido sem alterações por decisão da revisão):

- `DatabaseConnection` passou a aceitar a string de conexão no construtor; sem parâmetro, continua lendo `AZURE_SQL_CONNECTIONSTRING` do ambiente;
- `DatabaseConnection.transaction()` foi criado: mantém uma única conexão aberta durante o bloco, faz commit ao final e rollback em qualquer falha;
- `execute()`, `execute_many()`, `fetch_one()` e `fetch_all()` foram preservados e passaram a usar a conexão da transação ativa quando existir; fora de uma transação, o comportamento é o mesmo de antes;
- `CidadeRepository`, `OperadorRepository`, `EstacaoRepository` e `LeituraRepository` passaram a receber opcionalmente a `DatabaseConnection` a ser usada, mantendo o construtor sem argumentos;
- `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()` passaram a receber opcionalmente a conexão e repassá-la aos repositórios; a lógica das funções não foi alterada;
- `LeituraRepository.save_readings()` passou a executar as quatro importações dentro de `transaction()`;
- `run_pipeline()` cria a `DatabaseConnection` com `settings.azure_sql_connectionstring` e a encaminha para `save_readings()`;
- correção aprovada dos bloqueios de consulta: vírgula ausente antes de `E.nome` e parâmetros de período enviados somente quando o filtro correspondente é adicionado à SQL.

**Decisões registradas:**

- transação implementada em `DatabaseConnection` (decisão 4 da seção 13);
- `src/database/criar_tabelas.py` e `OperadorModel` permanecem como estavam; os itens 1 a 6 e 9 desta fase continuam pendentes.

**Validação executada** (banco descartável no SQL Server Express local, removido ao final):

- compilação dos módulos Python e import de `main.py` concluídos sem erros;
- carga de 5.438 registros completos do dataset em uma única transação: 10 cidades, 25 operadores, 30 estações e 5.438 leituras;
- falha em `importar_leituras()` desfez a cidade, o operador e a estação inseridos antes no mesmo lote;
- consultas por cidade sem período, com um dia e por estação com período executadas sem erro;
- `calculate_metrics(cidade_id=1, ...)` executado com estatísticas preenchidas.

**Pendências encontradas:**

- `criar_tabelas()` falha em banco vazio: `__criar_tabela_estacoes()` executa `ALTER TABLE Leituras` antes de `__criar_tabela_leituras()` criar a tabela. Em bancos com as tabelas já criadas, a execução funciona. Para o teste local, as tabelas foram criadas com um contorno no próprio script de teste;
- sem restrições de unicidade, reprocessar o mesmo lote duplicou todos os registros (20 cidades, 50 operadores, 60 estações e 10.876 leituras);
- `operador_ativo` continua sem coluna correspondente em `Operadores`;
- ~~o dataset da API contém 82 registros (de 5.520) com alguma medição ausente: 55 com string vazia e 27 sem a chave, e `validate_data()` rejeitava o lote inteiro.~~ Resolvida pelo ajuste posterior da Fase 5: as medições passaram a ser opcionais e são gravadas como `NULL`.

### Fase 8 - Criar o método de análise compatível com o diagrama

**Objetivo:** conectar `Main -> Analytics: calculate_metrics()` sem renomear `AnaliticsService` nem seus métodos públicos atuais.

**Método de coordenação sugerido:**

```python
class AnaliticsService:
  def calculate_metrics(self, cidade_id=None, estacao_id=None,
              data_inicio=None, data_fim=None) -> dict:
    """Executa as análises existentes e consolida estatísticas e outliers."""
```

**O que será feito:**

1. Receber explicitamente o escopo de cidade ou estação.
2. Chamar os métodos atuais `analisar_leituras_meteriologicas_*` e `analisar_leituras_qualidade_agua_*`.
3. Preservar os resultados das duas categorias sem sobrescrever variáveis.
4. Manter `__analisar_leituras()` como responsável por média, mediana e desvio padrão.
5. Manter `__identificar_outliers()` como responsável pelo IQR.
6. Converter retorno `None` das consultas em lista vazia antes do DataFrame.
7. Remover saída de console de dentro da análise ou encaminhá-la ao relatório.
8. Garantir que análises por estação mantenham o identificador/nome da estação.

**Dependências:** Fase 6 e Fase 7.

**Critério de revisão:** uma chamada a `calculate_metrics()` devolve um objeto consolidado com estatísticas e outliers dos dois grupos.

**Implementação concluída:**

- `AnaliticsService.calculate_metrics()` recebe `cidade_id` ou `estacao_id`, rejeita a ausência de escopo e o uso simultâneo dos dois, e chama os métodos existentes `analisar_leituras_meteriologicas_*` e `analisar_leituras_qualidade_agua_*`;
- o retorno consolida `escopo`, `periodo`, `meteorologica` e `qualidade_agua`, cada grupo com `analise` e `outliers`, sem sobrescrita de resultados;
- `__analisar_leituras()` e `__identificar_outliers()` continuam responsáveis pelos cálculos; nenhum cálculo foi alterado;
- o retorno `None` das consultas já chega ao DataFrame como lista vazia por `__preparar_dataframe()` (`dados or []`);
- removido o `print()` de unidades em `analisar_leituras_meteriologicas_estacao()`; a análise não escreve mais no console;
- `AnaliticsService` passou a receber opcionalmente a `DatabaseConnection` e repassá-la aos repositórios, como os demais componentes da Fase 7; `run_pipeline()` encaminha a mesma conexão usada na persistência;
- a anotação de `__COLUNAS` foi corrigida para `dict[str, tuple[str, ...]]`, que é o tipo realmente armazenado;
- na análise por estação, a estação é identificada por `escopo.estacao_id`; os outliers não trazem a coluna `Estação`, porque todas as leituras pertencem à mesma estação. Na análise por cidade, os outliers mantêm a coluna `Estação`.

**Correspondência com o diagrama de sequência:** os nomes do diagrama não foram criados como novos métodos, para não duplicar a lógica existente:

| Diagrama | Implementação |
| --- | --- |
| `calculate_metrics()` | `AnaliticsService.calculate_metrics()` |
| `get_readings_by_station()` | `LeituraRepository.get_leituras_*_by_estacao()` e `get_leituras_*_by_cidade()` |
| `media()`, `mediana()`, `desvio_padrao()` | `AnaliticsService.__analisar_leituras()` |
| `detectar_outliers()` | `AnaliticsService.__identificar_outliers()` |

**Validação executada** (banco descartável no SQL Server Express local, removido ao final, com a conexão padrão do ambiente apontando para um servidor inexistente para confirmar o uso da conexão injetada):

- compilação dos módulos Python concluída sem erros;
- `calculate_metrics()` por cidade e por estação devolveu estatísticas dos dois grupos e outliers em DataFrame;
- nenhuma saída de console durante a análise;
- escopo ausente e escopo duplo rejeitados com `ValueError`;
- `ReportService.generate_report()` e `_exibir_resultados()` executados com o resultado por cidade.

**Pendência encontrada:** quando o período não possui leituras, `__analisar_leituras()` devolve uma string em vez do dicionário com `Estatísticas`, e `_exibir_resultados()` falha com `TypeError`. A correção altera a lógica do método e está pendente de aprovação.

### Fase 9 - Criar o relatório final

**Objetivo:** atender à chamada `Main -> Report: generate_report(indicadores)`.

**Novo arquivo sugerido:** `src/services/report_service.py`.

**Classe e método sugeridos:**

```python
class ReportService:
  def generate_report(self, indicadores: dict) -> dict | str:
    """Formata estatísticas, outliers, escopo e período para o usuário."""
```

**O que será feito:**

1. Receber o retorno consolidado de `calculate_metrics()`.
2. Preservar estatísticas meteorológicas e de qualidade da água.
3. Preservar os outliers e seus limites IQR.
4. Incluir cidade/estação, período e quantidade de leituras.
5. Separar formatação de relatório da lógica estatística.
6. Permitir saída textual e estruturada, sem expor credenciais.
7. Fazer `run_pipeline()` devolver o relatório ao chamador.

**Dependências:** Fase 8.

**Critério de revisão:** o usuário recebe um relatório único e nenhum resultado de análise é perdido por sobrescrita.

**Implementação concluída:**

- `ReportService.generate_report()` recebe o retorno de `calculate_metrics()` e devolve o relatório estruturado com `escopo`, `periodo` e `grupos`;
- cada grupo (`meteorologica` e `qualidade_agua`) preserva a `analise`, com quantidade de leituras e estatísticas, e os `outliers` convertidos para lista de registros com `Limite Inferior` e `Limite Superior` do IQR;
- `ReportService.format_report()` foi criado para gerar a saída textual a partir do relatório estruturado;
- a formatação textual que estava em `_exibir_resultados()` no `main.py` foi movida sem alteração para `format_report()`; `_exibir_resultados()` passou apenas a imprimir o texto devolvido pelo serviço;
- `run_pipeline()` continua devolvendo o relatório estruturado ao chamador; a impressão ocorre somente no bloco `__main__`;
- o relatório contém apenas resultados da análise, sem configuração nem credenciais.

**Decisão registrada:** `ReportService` oferece as duas saídas (decisão 3 da seção 13): estruturada, por `generate_report()`, e textual, por `format_report()`.

**Validação executada** (banco descartável no SQL Server Express local, removido ao final):

- compilação dos módulos Python concluída sem erros;
- para `cidade_id=1`, `estacao_id=1` e `cidade_id=3`, a saída de `_exibir_resultados()` ficou idêntica, caractere a caractere, à produzida pela implementação anterior;
- o relatório estruturado manteve escopo, período, os dois grupos, a quantidade de leituras e os limites IQR dos outliers;
- o texto gerado não contém dados de conexão.

**Pendências encontradas:**

- quando o período não possui leituras, a análise devolve uma string e a formatação falha com `TypeError`, como já ocorria antes (pendência registrada na Fase 8);
- a saída textual mantém o conteúdo da versão anterior e não exibe escopo, período nem o nome de cada grupo; essas informações estão apenas no relatório estruturado;
- o relatório estruturado contém `date` e `Timestamp` do pandas, portanto não é serializável diretamente em JSON caso seja necessário exportá-lo em arquivo.

### Fase 10 - Tratamento de erros, testes e integração final

**Objetivo:** verificar o fluxo completo e garantir que cada etapa falhe de forma rastreável.

**O que será feito:**

1. Classificar falhas de configuração, coleta, normalização, validação, persistência, consulta, análise e relatório.
2. Não capturar `BaseException` nas etapas de aplicação; capturar somente exceções esperadas.
3. Registrar a etapa e o identificador do registro sem expor segredos.
4. Fazer o processo principal retornar código diferente de zero em caso de falha.
5. Criar testes unitários para `load_config()`, `fetch_data()`, `normalize()`, `validate_data()` e `generate_report()`.
6. Criar testes dos métodos-ponte vazios ou delegadores.
7. Criar testes de integração para ordem de persistência, rollback, consulta por período e idempotência.
8. Executar um teste de ponta a ponta com dataset local e banco de teste.
9. Atualizar o diagrama somente se a implementação final diferir do fluxo aprovado.

**Dependências:** todas as fases anteriores.

**Critério de revisão:** o pipeline completo executa na ordem do diagrama, os testes críticos passam e falhas produzem resultado não ambíguo.

**Implementação realizada (testes):**

- criada a pasta `tests/`, adicionada ao controle de versão, com testes unitários em `tests/unit` e de integração em `tests/integration`; a estrutura, o conteúdo de cada arquivo e o guia de execução estão na seção 4 de [plano-testes.md](plano-testes.md);
- `pytest` e `pytest-cov` foram adicionados ao `requirements.txt`; `.pytest_cache`, `.coverage` e `htmlcov` foram adicionados ao `.gitignore`;
- `tests/conftest.py` substitui `AZURE_SQL_CONNECTIONSTRING` e `MOCK_API` por valores de teste antes de qualquer import de `src`, para que nenhum teste acesse o banco real;
- os testes de integração só rodam com `TEST_SQL_MASTER_CONNECTIONSTRING` configurada; cada sessão cria um banco descartável e o remove ao final;
- itens 5 a 8 desta fase: atendidos pelos testes unitários (`load_config()`, `fetch_data()`, `normalize()`, `validate_data()`, `generate_report()`, métodos-ponte e orquestração) e de integração (ordem de persistência, rollback, consulta por período, idempotência e ponta a ponta);
- item 4: atendido pelo `main.py` atual, que envia o erro para `stderr` e termina com código `1` (`test_execucao_com_falha_termina_com_codigo_1_sem_expor_segredo`);
- itens 1 a 3: pendentes. O `main.py` atual não identifica a etapa em que a falha ocorreu; os testes verificam que o erro original é propagado e interrompe as etapas seguintes.

**Validação executada:**

- sem banco de teste: 58 testes aprovados e 7 de integração ignorados;
- cobertura com `--cov=src --cov=main`: `config` 100%, `data_client` 100%, `report_service` 100%, `validation_service` 95%, `normalization_service` 94%, `analytics_service` 78%, `main.py` 76%; o total do projeto (64%) inclui repositórios e a API, não exercitados pelos testes unitários;
- os testes de integração não foram executados nesta entrega, por falta de SQL Server de teste no ambiente.

**Pendências encontradas:**

- `importar_cidades()`, `importar_operadores()`, `importar_estacoes()` e `importar_leituras()` capturam `BaseException` (item 2); a correção altera o corpo dessas funções e depende de aprovação;
- `criar_tabelas()` falha em banco vazio (pendência da Fase 7); o `tests/integration/conftest.py` cria o schema com um contorno, sem alterar o schema produzido;
- `test_reprocessar_o_lote_nao_duplica_leituras` está marcado como `xfail` estrito até as restrições `UNIQUE` da Fase 7 serem criadas;
- os cenários CT-01, CT-02 e CT-03 de [plano-testes.md](plano-testes.md) esperam comportamentos ainda não implementados (descarte individual com log, rejeição de data futura e `upsert`).

## 11. Ordem de dependência entre fases

```text
Fase 0
  -> Fase 1
  -> Fase 2
  -> Fase 3
  -> Fase 4
  -> Fase 5
  -> Fase 6 <-> Fase 7
  -> Fase 8
  -> Fase 9
  -> Fase 10
```

As Fases 6 e 7 dependem uma da outra na validação prática: o repository precisa conhecer o schema, e o schema precisa ser validado pelos comandos reais do repository. Elas podem ser desenvolvidas em conjunto, mas nenhuma das duas deve ser considerada concluída isoladamente.

## 12. Entregas esperadas por fase

| Fase | Entrega principal | Revisão solicitada |
| --- | --- | --- |
| 0 | Registro do comportamento atual | Confirmar baseline e falhas conhecidas |
| 1 | `main.py.run_pipeline()` | Confirmar sequência e retorno do orquestrador |
| 2 | `load_config()` | Confirmar variáveis obrigatórias e segurança |
| 3 | `DataClient.fetch_data()` | Confirmar separação entre coleta e persistência |
| 4 | `NormalizationService.normalize()` | Confirmar conversões e nomes dos campos |
| 5 | `ValidationService.validate_data()` | Confirmar política para registros inválidos |
| 6 | `save_readings()`, `insert_estacao()`, `insert_leituras()` | Confirmar ordem, transação e idempotência |
| 7 | Schema e `DatabaseConnection.connect()` | Confirmar contrato físico do banco |
| 8 | `AnaliticsService.calculate_metrics()` | Confirmar escopo e consolidação dos resultados |
| 9 | `ReportService.generate_report()` | Confirmar formato e conteúdo do relatório |
| 10 | Testes e execução ponta a ponta | Confirmar critérios de aceite |

## 13. Decisões que precisam ser revisadas antes da implementação

Antes de iniciar as alterações de código, a revisão deve decidir:

1. Se a validação rejeitará o lote inteiro ou persistirá registros válidos e reportará inválidos. *Fase 5: rejeição do lote inteiro quando algum registro é inválido; medições ausentes não invalidam o registro e são gravadas como `NULL`.*
2. Se `cidade_id` ou `estacao_id` será o escopo padrão de `calculate_metrics()`. *Fase 8: o método não possui escopo padrão e exige um dos dois; `run_pipeline()` usa hoje `cidade_id=1` e o período de 01/06/2026 a 01/12/2026 fixos no código.*
3. Se `ReportService.generate_report()` devolverá texto, dicionário ou ambos. *Fase 9: ambos; `generate_report()` devolve o dicionário e `format_report()` o texto.*
4. Se a transação será implementada dentro de `DatabaseConnection` ou em um objeto de persistência específico. *Fase 7: `DatabaseConnection.transaction()`.*
5. Se `criar_tabelas()` será executado automaticamente em todo pipeline ou apenas em uma etapa de preparação.
6. Qual convenção de fuso será aplicada a `data_hora` sem fuso.
7. Como será feita a idempotência: ignorar, atualizar ou rejeitar a leitura duplicada.

## 14. Critérios de aceite do novo fluxo

O fluxo estará alinhado ao diagrama quando:

- `main.py` executar uma única função de orquestração;
- `load_config()`, `fetch_data()`, `normalize()`, `validate_data()`, `save_readings()`, `connect()`, `calculate_metrics()` e `generate_report()` existirem com os contratos definidos;
- a configuração for carregada antes das demais etapas;
- a fonte devolver dados brutos sem persistir durante a coleta;
- normalização e validação ocorrerem antes de qualquer insert;
- cidades, operadores, estações e leituras forem persistidos nessa ordem;
- falha em qualquer etapa interromper o processamento seguinte;
- consultas por cidade/estação e período retornarem parâmetros compatíveis;
- `AnaliticsService` produzir estatísticas e outliers sem perda de resultados;
- o relatório receber um resultado consolidado;
- a repetição do lote não criar leituras duplicadas;
- erros terminarem com indicação de falha para quem iniciou o processo;
- os nomes atuais de classes e métodos continuarem disponíveis;
- o código executar a mesma sequência documentada no diagrama.

## 15. Conclusão

O código atual possui partes importantes da solução, principalmente os modelos, os repositórios, as funções de importação e o serviço estatístico. O problema central é que essas partes não estão conectadas no fluxo do diagrama: a importação e a análise são executadas separadamente, e vários contratos entre repositório, banco e análise ainda não são compatíveis.

A refatoração deve começar pelo `main.py`, estabelecer o encadeamento único e depois corrigir os bloqueios de contrato encontrados nos repositórios e no schema. Os métodos de negócio existentes devem continuar sendo usados, com seus nomes preservados. O objetivo é fazer o dado percorrer as etapas na ordem correta, desde a configuração até o relatório final.