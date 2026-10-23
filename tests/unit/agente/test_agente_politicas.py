"""
Testes das políticas de segurança do agente (docs/agente/guardrails-e-owasp.md § 9).

- POL-01 (somente leitura): nenhum código de src/agente usa métodos de escrita,
  e o catálogo é exatamente a lista fechada de ferramentas de leitura.
- POL-02 (dados pessoais): nenhum retorno de ferramenta tem chave ou padrão de
  dado pessoal, para todas as ferramentas, com argumentos variados.
- POL-12 (dependências): o agente não importa bibliotecas fora das aprovadas
  em docs/agente/bibliotecas.md.
"""
import ast
import json
import re
from pathlib import Path

import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.ferramentas.catalogo import FERRAMENTAS_DE_DADOS, FERRAMENTAS_PERMITIDAS

PASTA_AGENTE = Path(__file__).resolve().parents[3] / "src" / "agente"
PASTA_PREVISAO = PASTA_AGENTE.parent / "previsao"

# POL-01 / POL-02: nomes que nunca podem aparecer no código do agente.
NOMES_PROIBIDOS = {
    "save_readings",
    "substituir_leituras",
    "insert_leituras",
    "merge_many",
    "create_many",
    "insert_estacao",
    "run_pipeline",
    "OperadorRepository",
    "descriptografar_email",
    "execute_many",
}
# POL-02: chaves e padrões de dado pessoal que nenhum retorno pode conter.
CHAVES_PESSOAIS = {"cpf", "cpf_hash", "nome_hash", "email", "email_criptografado", "operador", "operador_id"}
PADRAO_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PADRAO_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# POL-12: bibliotecas de terceiros aprovadas para o agente até a fase atual.
BIBLIOTECAS_APROVADAS = {"anthropic", "chromadb", "fastembed", "joblib", "numpy", "openai", "pandas", "pydantic", "scipy", "sklearn", "tiktoken"}

ARGUMENTOS_DE_TESTE = {
    "panorama_dados": [{}],
    "listar_parametros": [{}],
    "resumo_estatistico": [{}, {"parametros": ["TIP-PH"], "data_inicio": "2026-06-02"}],
    "listar_anomalias": [{}, {"parametro": "TIP-PH", "ordenar_por": "data", "limite": 50}],
    "serie_temporal": [{"parametro": "TIP-TMP", "data_inicio": "2026-06-01", "data_fim": "2026-06-03", "granularidade": "hora"}],
    "perfil_horario": [{"parametro": "TIP-TMP"}],
    "comparar_periodos": [{"parametro": "TIP-TMP", "inicio_a": "2026-06-01", "fim_a": "2026-06-03", "turno_a": "dia",
                           "inicio_b": "2026-06-01", "fim_b": "2026-06-03", "turno_b": "noite"}],
    "correlacao": [{"parametros": ["TIP-TMP", "TIP-PH", "TIP-CHU"]}],
    "probabilidade_evento": [{"evento_parametro": "TIP-PH", "evento_operador": ">", "evento_valor": 7.1,
                              "condicao_parametro": "TIP-TMP", "condicao_operador": ">=", "condicao_valor": 25}],
    "buscar_documentacao": [{"consulta": "anonimização de CPF e e-mail do operador"}, {"consulta": "LGPD dados pessoais", "top_k": 8}],
    "dias_semelhantes": [{"data": "2026-06-01"}, {"data": "2026-06-02", "estacao": "EST-1", "top_k": 10}],
    "prever": [{"parametro": "TIP-TMP", "horizonte_horas": 6}, {"parametro": "TIP-TMP", "estacao": "EST-1", "horizonte_horas": 6}],
}


def arquivos_do_agente() -> list[Path]:
    """Todos os arquivos Python de src/agente."""
    return sorted(PASTA_AGENTE.rglob("*.py"))


@pytest.mark.parametrize("arquivo", arquivos_do_agente(), ids=lambda p: p.relative_to(PASTA_AGENTE).as_posix())
def test_pol01_codigo_do_agente_nao_usa_metodos_de_escrita(arquivo):
    nomes_usados = set(re.findall(r"\b\w+\b", arquivo.read_text(encoding="utf-8")))

    assert not nomes_usados & NOMES_PROIBIDOS


def test_pol01_catalogo_e_a_lista_fechada_de_leitura(registro, registro_completo):
    assert registro.nomes() == FERRAMENTAS_DE_DADOS
    assert registro_completo.nomes() == FERRAMENTAS_PERMITIDAS
    verbos_de_escrita = ("inserir", "gravar", "apagar", "excluir", "atualizar", "executar", "sql", "delete", "insert", "update")
    assert not [nome for nome in registro.nomes() if any(verbo in nome for verbo in verbos_de_escrita)]


def test_pol01_toda_ferramenta_tem_argumentos_de_teste(registro_completo):
    """Garante que o teste de PII abaixo cobre uma ferramenta nova assim que ela entrar no catálogo."""
    assert set(ARGUMENTOS_DE_TESTE) == set(registro_completo.nomes())


def chaves_recursivas(valor) -> set[str]:
    """Todas as chaves de dicionário, em qualquer nível."""
    if isinstance(valor, dict):
        return set(valor) | {c for item in valor.values() for c in chaves_recursivas(item)}
    if isinstance(valor, list):
        return {c for item in valor for c in chaves_recursivas(item)}
    return set()


@pytest.mark.parametrize(
    "nome, argumentos",
    [(nome, argumentos) for nome, lista in ARGUMENTOS_DE_TESTE.items() for argumentos in lista],
)
def test_pol02_retorno_sem_dados_pessoais(registro_completo, nome, argumentos):
    """Inclui os trechos da documentação: exemplos de CPF e e-mail nos .md chegam mascarados."""
    resultado = registro_completo.executar(ChamadaFerramenta("c1", nome, argumentos))
    texto = json.dumps(resultado.dados, ensure_ascii=False)

    assert resultado.sucesso, resultado.erro
    assert not {c.lower() for c in chaves_recursivas(resultado.dados)} & CHAVES_PESSOAIS
    assert not PADRAO_CPF.search(texto)
    assert not PADRAO_EMAIL.search(texto)


def importacoes_de_terceiros(arquivo: Path) -> set[str]:
    """Pacotes de primeiro nível importados pelo arquivo, sem a biblioteca padrão e sem src."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    nomes = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            nomes.add(no.module.split(".")[0])
    import sys

    return {nome for nome in nomes if nome != "src" and nome not in sys.stdlib_module_names}


def test_pol12_agente_so_importa_bibliotecas_aprovadas():
    # src/previsao (Fase 10) entra junto: a ferramenta prever carrega o modelo treinado lá.
    arquivos = arquivos_do_agente() + sorted(PASTA_PREVISAO.rglob("*.py"))
    usadas = set().union(*(importacoes_de_terceiros(arquivo) for arquivo in arquivos))

    assert usadas <= BIBLIOTECAS_APROVADAS, f"biblioteca sem registro em docs/agente/bibliotecas.md: {usadas - BIBLIOTECAS_APROVADAS}"
