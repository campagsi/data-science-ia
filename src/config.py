from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parents[1]

# Leituras.fonte é VARCHAR(100) no sql/ddl_banco_relacional.sql.
TAMANHO_MAXIMO_FONTE = 100

# Agente (docs/agente/arquitetura.md § 9). simulado = LLM roteirizado, sem rede.
FORNECEDORES_LLM = ("anthropic", "openai", "simulado")
# Fornecedores com LLM de verdade (exigem chave, modelo e o usuário só de leitura do banco).
FORNECEDORES_REAIS = ("anthropic", "openai")
# DA3: memoria (Fase 4) ou chroma (Fase 5); o Azure SQL VECTOR foi descartado.
BANCOS_VETORIAIS = ("memoria", "chroma")
# effort do Claude: profundidade do raciocínio e principal alavanca de custo (DA9).
ESFORCOS = ("low", "medium", "high")
# DA2: modelo do fastembed, multilíngue, 384 dimensões.
MODELO_EMBEDDINGS_PADRAO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass(frozen=True)
class Settings:
    # URL da API de ingestão; também é o valor gravado em Leituras.fonte.
    fonte_dados: str
    azure_sql_connectionstring: str
    chave_criptografia: str = ""
    chave_hash: str = ""


def load_config() -> Settings:
    """Carrega a configuração do pipeline sem expor valores sensíveis."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    connection_string = os.getenv("AZURE_SQL_CONNECTIONSTRING", "").strip()
    if not connection_string:
        raise ValueError("A variável AZURE_SQL_CONNECTIONSTRING deve estar configurada.")

    fonte_dados = os.getenv("FONTE_DADOS", "").strip()
    if not fonte_dados:
        raise ValueError("A variável FONTE_DADOS deve estar configurada.")
    if len(fonte_dados) > TAMANHO_MAXIMO_FONTE:
        raise ValueError(
            f"A variável FONTE_DADOS deve ter no máximo {TAMANHO_MAXIMO_FONTE} caracteres."
        )

    chave_criptografia = os.getenv("CHAVE_CRIPTOGRAFIA", "").strip()
    if not chave_criptografia:
        raise ValueError("A variável CHAVE_CRIPTOGRAFIA deve estar configurada.")

    return Settings(
        fonte_dados=fonte_dados,
        azure_sql_connectionstring=connection_string,
        chave_criptografia=chave_criptografia,
        # Opcional: sem a chave de hash, o hash é SHA-256 puro (decisão D8).
        chave_hash=os.getenv("CHAVE_HASH", "").strip(),
    )


@dataclass(frozen=True)
class ConfigAgente:
    llm_fornecedor: str
    llm_modelo: str = ""
    # repr=False: a chave não aparece ao imprimir a configuração nem em log.
    anthropic_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    # Usuário só de leitura do agente (política POL-01); traz senha, então também fora do repr.
    sql_connectionstring: str = field(default="", repr=False)
    embeddings_modelo: str = MODELO_EMBEDDINGS_PADRAO
    vetores: str = "memoria"
    dir_indice: Path = RAIZ_PROJETO / "data" / "agente"
    # Limites da decisão DA6.
    max_ferramentas: int = 6
    max_linhas: int = 50
    historico_turnos: int = 10
    timeout_segundos: int = 60
    # Política POL-07 (consumo limitado), Fase 3.
    max_tokens_saida: int = 16000
    esforco: str = "medium"
    max_tokens_pergunta: int = 60000
    prazo_pergunta_segundos: int = 180


def load_config_agente() -> ConfigAgente:
    """
    Carrega a configuração do agente (variáveis AGENTE_* e a chave do LLM).

    Separada de load_config() para que a ingestão não passe a exigir chaves
    de LLM, e o agente não exija as variáveis da ingestão.
    """
    load_dotenv(RAIZ_PROJETO / ".env")

    fornecedor = os.getenv("AGENTE_LLM_FORNECEDOR", "").strip().lower()
    if fornecedor not in FORNECEDORES_LLM:
        raise ValueError(
            f"A variável AGENTE_LLM_FORNECEDOR deve ser uma destas: {', '.join(FORNECEDORES_LLM)}."
        )

    modelo = os.getenv("AGENTE_LLM_MODELO", "").strip()
    chave = os.getenv("ANTHROPIC_API_KEY", "").strip()
    chave_openai = os.getenv("OPENAI_API_KEY", "").strip()
    if fornecedor != "simulado" and not modelo:
        raise ValueError("A variável AGENTE_LLM_MODELO deve estar configurada.")
    if fornecedor == "anthropic" and not chave:
        raise ValueError("A variável ANTHROPIC_API_KEY deve estar configurada.")
    if fornecedor == "openai" and not chave_openai:
        raise ValueError("A variável OPENAI_API_KEY deve estar configurada.")

    # POL-01: com o LLM real, o agente só lê o banco com o usuário próprio, sem
    # permissão de escrita. Não há recaída na connection string da ingestão.
    sql_connectionstring = os.getenv("AGENTE_SQL_CONNECTIONSTRING", "").strip()
    if fornecedor in FORNECEDORES_REAIS and not sql_connectionstring:
        raise ValueError(
            "A variável AGENTE_SQL_CONNECTIONSTRING deve estar configurada "
            "(usuário só de leitura do agente, ver docs/manual-execucao.md)."
        )

    vetores = os.getenv("AGENTE_VETORES", "").strip().lower() or "memoria"
    if vetores not in BANCOS_VETORIAIS:
        raise ValueError(
            f"A variável AGENTE_VETORES deve ser uma destas: {', '.join(BANCOS_VETORIAIS)}."
        )

    esforco = os.getenv("AGENTE_ESFORCO", "").strip().lower() or "medium"
    if esforco not in ESFORCOS:
        raise ValueError(f"A variável AGENTE_ESFORCO deve ser uma destas: {', '.join(ESFORCOS)}.")

    dir_indice = Path(os.getenv("AGENTE_DIR_INDICE", "").strip() or "data/agente")
    if not dir_indice.is_absolute():
        dir_indice = RAIZ_PROJETO / dir_indice

    return ConfigAgente(
        llm_fornecedor=fornecedor,
        llm_modelo=modelo,
        anthropic_api_key=chave,
        openai_api_key=chave_openai,
        sql_connectionstring=sql_connectionstring,
        embeddings_modelo=os.getenv("AGENTE_EMBEDDINGS_MODELO", "").strip() or MODELO_EMBEDDINGS_PADRAO,
        vetores=vetores,
        dir_indice=dir_indice,
        max_ferramentas=_inteiro_positivo("AGENTE_MAX_FERRAMENTAS", 6),
        max_linhas=_inteiro_positivo("AGENTE_MAX_LINHAS", 50),
        historico_turnos=_inteiro_positivo("AGENTE_HISTORICO_TURNOS", 10),
        timeout_segundos=_inteiro_positivo("AGENTE_TIMEOUT_SEGUNDOS", 60),
        max_tokens_saida=_inteiro_positivo("AGENTE_MAX_TOKENS_SAIDA", 16000),
        esforco=esforco,
        max_tokens_pergunta=_inteiro_positivo("AGENTE_MAX_TOKENS_PERGUNTA", 60000),
        prazo_pergunta_segundos=_inteiro_positivo("AGENTE_PRAZO_PERGUNTA_SEGUNDOS", 180),
    )


@dataclass(frozen=True)
class ConfigIndice:
    embeddings_modelo: str = MODELO_EMBEDDINGS_PADRAO
    dir_indice: Path = RAIZ_PROJETO / "data" / "agente"
    vetores: str = "memoria"
    # Só o --indexar-dias usa: lê as medições com o usuário só de leitura do agente.
    sql_connectionstring: str = field(default="", repr=False)


def load_config_indice() -> ConfigIndice:
    """
    Configuração da indexação da documentação (python main.py --indexar).

    Lê só AGENTE_EMBEDDINGS_MODELO, AGENTE_DIR_INDICE e AGENTE_VETORES: indexar
    não precisa do LLM nem do banco, então não exige as outras variáveis do agente.
    AGENTE_SQL_CONNECTIONSTRING é opcional aqui: só o --indexar-dias (Fase 9) lê o banco.
    """
    load_dotenv(RAIZ_PROJETO / ".env")
    vetores = os.getenv("AGENTE_VETORES", "").strip().lower() or "memoria"
    if vetores not in BANCOS_VETORIAIS:
        raise ValueError(f"A variável AGENTE_VETORES deve ser uma destas: {', '.join(BANCOS_VETORIAIS)}.")
    dir_indice = Path(os.getenv("AGENTE_DIR_INDICE", "").strip() or "data/agente")
    if not dir_indice.is_absolute():
        dir_indice = RAIZ_PROJETO / dir_indice
    return ConfigIndice(
        embeddings_modelo=os.getenv("AGENTE_EMBEDDINGS_MODELO", "").strip() or MODELO_EMBEDDINGS_PADRAO,
        dir_indice=dir_indice,
        vetores=vetores,
        sql_connectionstring=os.getenv("AGENTE_SQL_CONNECTIONSTRING", "").strip(),
    )


def _inteiro_positivo(variavel: str, padrao: int) -> int:
    """Lê uma variável inteira opcional (vazia = padrão), exigindo valor >= 1."""
    texto = os.getenv(variavel, "").strip()
    if not texto:
        return padrao
    try:
        valor = int(texto)
    except ValueError:
        raise ValueError(f"A variável {variavel} deve ser um número inteiro.") from None
    if valor < 1:
        raise ValueError(f"A variável {variavel} deve ser maior que zero.")
    return valor
