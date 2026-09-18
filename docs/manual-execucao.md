# Manual de execução

## Requisitos

Antes de executar o projeto, certifique-se de que o ambiente atende aos requisitos mínimos:

- Python 3.10 ou superior
- pip atualizado
- acesso ao banco de dados configurado
- arquivo `.env` com variáveis necessárias

## 1. Preparar o ambiente

Crie um ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente:

```bash
# Windows
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate
```

## 2. Instalar dependências

```bash
pip install -r requirements.txt
```

No PowerShell, caso a execução de scripts esteja bloqueada:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

## 3. Configurar variáveis de ambiente

Crie um arquivo `.env` com base no `.env.example` e defina valores como:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=monitoramento
DB_USER=postgres
DB_PASSWORD=sua_senha
```

## 4. Criar banco e tabelas

Execute o script de criação das tabelas:

```bash
python src/database/criar_tabelas.py
```

## 5. Executar a aplicação

```bash
python src/main.py
```

## 6. Verificar resultados

O fluxo deve:

- carregar o JSON bruto
- normalizar strings numéricas, booleanas e data/hora
- validar registros e intervalos
- persistir os dados no banco
- executar consultas e estatísticas
- exibir o relatório final ou salvar os resultados

## Estrutura executada

A execução segue a seguinte ordem lógica:

```text
configuração -> ingestão -> validação -> persistência -> análise -> relatório
```

## Dicas

- mantenha `.env` fora do controle de versão
- sempre atualize o `.env.example` quando novas variáveis forem adicionadas
- teste cada módulo separadamente antes de rodar o pipeline completo
