# Segurança e LGPD

Este documento é a referência única de **anonimização, criptografia e regras de log** do projeto. Os demais documentos apontam para cá em vez de repetir as regras.

## Requisito do enunciado

[projeto_final.pdf](projeto_final.pdf), item 3.2: o cadastro de operadores contém dados pessoais sensíveis (CPF e nome completo). É obrigatório aplicar **anonimização irreversível via hashing (SHA-256)** nas chaves de identificação pessoal e **criptografia reversível** para dados que exijam recuperação futura.

Item 3.7: logs estruturados com data/hora, severidade (INFO, WARNING, ERROR) e mensagem, sem exibições simples de tela.

## Dados pessoais no payload

| Campo do payload | Tratamento | Técnica | Destino no banco |
|---|---|---|---|
| `operador_cpf` | Anonimização irreversível | SHA-256 | `Operadores.cpf_hash` |
| `operador_nome_completo` | Anonimização irreversível | SHA-256 | `Operadores.nome_hash` |
| `operador_email` | Criptografia reversível | Fernet (simétrica) | `Operadores.email_criptografado` (decisão D7, migration V002) |
| `operador_codigo`, `estacao_codigo`, nomes de estação e coordenadas | Mantidos | — | Identificam equipamento e local, não pessoa; são necessários para os relacionamentos |

## Módulo central: `src/security.py`

Toda anonimização e criptografia passa por **um único módulo**, no mesmo formato de `avanade-ds-ia/modulo-1/projeto-pratico/src/security.py`. Nenhum outro arquivo importa `hashlib` ou `cryptography` para tratar dado pessoal.

| Função | Faz | Retorno |
|---|---|---|
| `anonimizar_cpf(cpf)` | `strip()`, `encode('utf-8')`, `hashlib.sha256(...).hexdigest()` | Texto hexadecimal de 64 caracteres, ou `None` se vazio |
| `anonimizar_nome(nome)` | Igual ao CPF; antes, normaliza espaços e caixa para que o mesmo nome gere o mesmo hash | 64 caracteres, ou `None` |
| `criptografar_email(email)` | `Fernet(chave).encrypt(email.encode('utf-8')).decode('utf-8')` | Token de texto, ou `None` se vazio |
| `descriptografar_email(token)` | Operação inversa, só para consulta autorizada | E-mail original |

Diferenças em relação ao exemplo:

- **A chave não fica no código.** No exemplo, `CHAVE_MESTRA` está fixa no arquivo; aqui ela vem da variável `CHAVE_CRIPTOGRAFIA` do `.env` (lida pelo `src/config.py`). É uma chave Fernet (Base64 de 32 bytes), gerada com `Fernet.generate_key()`. Se ela faltar, o pipeline não inicia.
- **Hash com chave secreta (decisão D8).** O CPF tem só 10¹¹ combinações, então um SHA-256 puro pode ser revertido por força bruta. Com `CHAVE_HASH` preenchida no `.env`, o módulo usa HMAC-SHA256 com esse segredo; com ela vazia, usa SHA-256 puro, como no exemplo. Nos dois casos, o resultado tem 64 caracteres e cabe no DDL atual.
- **Configuração explícita.** As chaves chegam ao módulo por `configurar_seguranca(chave, chave_hash)`, chamada em `iniciar_aplicacao()` no `main.py`. Chamar qualquer função antes disso gera erro, para evitar hash sem a `CHAVE_HASH` por esquecimento.
- **Uma chave para o time.** A `CHAVE_CRIPTOGRAFIA` e a `CHAVE_HASH` precisam ser as mesmas em todas as máquinas que gravam no banco. Com valores diferentes, o mesmo CPF gera outro hash e os e-mails gravados por outra máquina não podem ser lidos.
- **Retorno `None` para vazio**, como no exemplo, permite que a checagem de campos nulos (completude) funcione sobre os campos já anonimizados.

Pontos de atenção:

- O Fernet gera um token diferente a cada execução para o mesmo e-mail. Por isso o e-mail criptografado **não serve como chave** nem para comparação: a unicidade do operador continua em `codigo_operador` e `cpf_hash`.
- Perder ou trocar a `CHAVE_CRIPTOGRAFIA` torna os e-mails gravados irrecuperáveis. Guardar a chave fora do repositório (secret manager ou cofre do time).
- A dependência `cryptography` precisa entrar no `requirements.txt`.

## Onde a anonimização é aplicada

Seguindo o fluxo de `transform.py` do exemplo (proteção → regra de negócio → minimização):

1. **Normalização** do payload (limpeza de texto e tipos).
2. **Anonimização** com `src/security.py`: gera `cpf_hash`, `nome_hash` e `email_criptografado`.
3. **Minimização:** os campos originais (`operador_cpf`, `operador_nome_completo`, `operador_email`) são **removidos do registro** logo após o passo 2. Daí em diante, validação, log e persistência só enxergam a versão protegida.
4. Validação, persistência e log de rejeitados.

Como o dado em claro deixa de existir no registro depois do passo 3, nenhuma etapa posterior consegue gravá-lo no banco ou no log por engano.

**Camada Bronze (não implementada neste projeto):** a ingestão deste repositório não grava no Data Lake. Se ela vier a ser implementada: o enunciado (3.1) pede o JSON bruto em formato original, então os dados pessoais ficam em claro **somente** em `data_lake/bronze/`. Essa pasta tem acesso restrito, e os arquivos de dados dela não podem ir para o Git (só o `.gitkeep`). A partir da Silver e no banco relacional, apenas a versão anonimizada.

## Logs: módulo central `src/logger.py`

A configuração de log também fica em **um único lugar**, no padrão de `transform.py` e `01_ingestao_api.py`:

- `logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s', handlers=[...])`, chamado **uma vez** no início do `main.py` por `configurar_logs(etapa)`;
- loggers nomeados, como `logging.getLogger('TechDados_Logger')` do exemplo:
  - `DataScienceIA_Logger`: execução do pipeline (console + `logs/pipeline_AAAAMMDD_HHMMSS.log`);
  - `DataScienceIA_Rejeitados`: tudo o que não foi importado (`logs/rejeitados_AAAAMMDD_HHMMSS.log`);
- cada módulo só faz `logger = logging.getLogger('DataScienceIA_Logger')` e nunca chama `basicConfig` nem `print`;
- cada arquivo começa com um cabeçalho (`[cabeçalho]`) que diz qual etapa o criou (ingestão, análise, consulta ou coleta), por quê e o que contém; o de rejeitados de uma etapa que não importa dados fica só com o cabeçalho.

O formato das linhas de rejeitados e os níveis de severidade estão na seção 6 de [analise-implementacao.md](analise-implementacao.md).

## Regras

- Nunca registrar em log CPF, nome, e-mail, hash ou token de criptografia. Para identificar o operador, usar só `operador_codigo`.
- Nunca registrar tokens, senhas, string de conexão, `CHAVE_CRIPTOGRAFIA` ou `CHAVE_HASH`.
- Manter credenciais e chaves apenas em variáveis de ambiente ou secret manager; o `.env.example` traz só os nomes das variáveis.
- `logs/` e os arquivos de dados de `data_lake/` ficam fora do Git.
- Restringir o acesso ao banco, à pasta `data_lake/bronze/` e aos logs.
- Revisar todo campo novo do payload antes de incluí-lo no contrato: se identificar pessoa, ele entra na tabela "Dados pessoais no payload" acima.
