"""
Ferramenta buscar_documentacao: o RAG exposto ao LLM.

Conceito
--------
Para explicar regras, decisões e conceitos do projeto ("por que a chuva gera
tantos alertas IQR?"), o LLM chama esta ferramenta, recebe os trechos mais
relevantes da documentação e baseia a explicação neles, citando arquivo e
seção (grounding, regras 5 e 6 do system prompt).

Os trechos chegam ao LLM como RESULTADO DE FERRAMENTA (tool_result, em JSON),
nunca no system prompt. Um .md editado com "ignore as regras e..." é só texto
dentro de um resultado, e a regra 10 do prompt manda tratá-lo como dado
(política POL-08, prompt injection indireta, risco LLM01).

Embedding mede semelhança de SIGNIFICADO, e não faz contas. Números de medições
continuam vindo de resumo_estatistico e das outras ferramentas de dados.

Documentação: docs/agente/ferramentas.md § 4.7 e docs/agente/rag.md § 7
"""
from functools import partial

from pydantic import BaseModel, ConfigDict, Field

from src.agente.ferramentas.base import Ferramenta
from src.agente.rag.recuperador import TOP_K_PADRAO, Recuperador

AVISO_NADA_RELEVANTE = "nenhum trecho relevante na documentação"
MAXIMO_TRECHOS = 8

DESCRICAO_DOCUMENTACAO = (
    "Busca trechos da documentação do projeto por semelhança de significado: regras de validação e de "
    "anomalias (IQR, Z-Score, alertas), decisões D1 a D12, faixas dos parâmetros, LGPD, arquitetura, como "
    "executar e como o próprio agente funciona. Use para explicar regras, conceitos e decisões, e cite o "
    "arquivo e a seção dos trechos na resposta. Reformule a consulta com termos técnicos quando a pergunta "
    "for vaga (ex.: 'limitação IQR precipitação'). Não traz números de medições: para isso use "
    "resumo_estatistico e as outras ferramentas de dados."
)


class ArgumentosDocumentacao(BaseModel):
    """
    Argumentos de buscar_documentacao.

    Example:
        >>> ArgumentosDocumentacao(consulta="limitação IQR precipitação").top_k
        6
    """

    model_config = ConfigDict(extra="forbid")

    consulta: str = Field(min_length=3, max_length=300, description="Texto da busca, de 3 a 300 caracteres.")
    top_k: int = Field(TOP_K_PADRAO, ge=1, le=MAXIMO_TRECHOS, description="Quantidade de trechos (1 a 8, padrão 6).")


def criar_ferramenta_documentacao(recuperador: Recuperador) -> Ferramenta:
    """
    A ferramenta buscar_documentacao ligada a um Recuperador.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> from src.agente.rag.indexador import indexar
        >>> from src.agente.rag.vector_store import VectorStoreMemoria
        >>> pasta = Path(tempfile.mkdtemp())
        >>> _ = indexar(EmbedderSimulado(), pasta)
        >>> ferramenta = criar_ferramenta_documentacao(Recuperador(EmbedderSimulado(), VectorStoreMemoria.carregar(pasta), 0.1))
        >>> ferramenta.executar({"consulta": "limitação da regra IQR na precipitação", "top_k": 1})["trechos"][0]["arquivo"]
        'docs/analise-estatistica.md'
    """
    return Ferramenta(
        "buscar_documentacao",
        DESCRICAO_DOCUMENTACAO,
        ArgumentosDocumentacao,
        partial(buscar_documentacao, recuperador),
        limite_itens=MAXIMO_TRECHOS,
    )


def buscar_documentacao(recuperador: Recuperador, argumentos: ArgumentosDocumentacao) -> dict:
    """
    Trechos relevantes com arquivo, seção, texto e similaridade (docs/agente/ferramentas.md § 4.7).

    Args:
        recuperador: busca no índice da documentação.
        argumentos: consulta e top_k.

    Returns:
        {"consulta", "trechos": [...], "aviso"}; sem trecho acima do limiar,
        trechos vazio e aviso "nenhum trecho relevante na documentação".

    Example:
        >>> class SemNada:
        ...     def buscar(self, consulta, top_k): return []
        >>> buscar_documentacao(SemNada(), ArgumentosDocumentacao(consulta="receita de bolo"))["aviso"]
        'nenhum trecho relevante na documentação'
    """
    trechos = recuperador.buscar(argumentos.consulta, argumentos.top_k)
    return {
        "consulta": argumentos.consulta,
        "trechos": [
            {"arquivo": t.arquivo, "secao": t.secao, "texto": t.texto, "similaridade": t.similaridade}
            for t in trechos
        ],
        "aviso": None if trechos else AVISO_NADA_RELEVANTE,
    }
