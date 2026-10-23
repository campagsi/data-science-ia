"""
Ferramenta dias_semelhantes: embeddings sobre a análise temporal (Fase 9).

Conceito
--------
"Que dias foram parecidos com 15/06?" não é uma conta: é uma busca por
SEMELHANÇA. O resumo textual do dia pedido (dias/resumos.py) vira a consulta,
e o índice dos dias devolve os vizinhos mais próximos da mesma estação, cada
um com o próprio resumo.

    15/06 → "Chuva forte: 32,4 mm. Temperatura do ar: média 21,3 °C, baixa..."
          → embedding → vizinhos: 02/07 (0,94), 19/06 (0,91), ...

A similaridade é de cosseno entre os embeddings dos resumos, e não uma medida
física. Os números citados vêm dos resumos, calculados pelo código. Para o
valor exato de um dia, a descrição manda o LLM chamar resumo_estatistico.

Documentação: docs/agente/ferramentas.md § 4.11 e docs/agente/rag.md § 8
"""
from datetime import date
from functools import partial

from pydantic import BaseModel, ConfigDict, Field

from src.agente.dias.indice import BuscaDeDias
from src.agente.dias.resumos import resumos_diarios
from src.agente.ferramentas.argumentos import PADRAO_CODIGO
from src.agente.ferramentas.base import ErroDeRegra, Ferramenta
from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes

MAXIMO_DIAS = 10
AVISO_DIAS = (
    "Semelhança entre os resumos diários (embeddings), e não uma medida física. "
    "Para o valor exato de um dia, use resumo_estatistico com data_inicio = data_fim = o dia."
)
DESCRICAO_DIAS = (
    "Encontra os dias mais parecidos com um dia de referência, na mesma estação, comparando os "
    "resumos diários (chuva, médias com rótulos baixa/típica/alta para o período e anomalias). "
    "Use para 'que dias foram parecidos com 15/06?' ou 'houve outro dia como esse?'. Devolve cada "
    "dia com o resumo e a similaridade (0 a 1). Não serve para valores exatos: para números de um "
    "dia, chame resumo_estatistico com data_inicio = data_fim = o dia."
)


class ArgumentosDiasSemelhantes(BaseModel):
    """
    Argumentos de dias_semelhantes.

    Example:
        >>> ArgumentosDiasSemelhantes(data="2026-06-15").top_k
        5
    """

    model_config = ConfigDict(extra="forbid")

    data: date = Field(description="Dia de referência, AAAA-MM-DD.")
    estacao: str | None = Field(None, pattern=PADRAO_CODIGO, description="Código da estação, ex.: EST-RJ-001. Obrigatório com mais de uma estação.")
    top_k: int = Field(5, ge=1, le=MAXIMO_DIAS, description="Quantidade de dias parecidos (1 a 10).")


def criar_ferramenta_dias_semelhantes(consulta: ConsultaDados, busca: BuscaDeDias) -> Ferramenta:
    """
    A ferramenta dias_semelhantes ligada aos dados e ao índice dos dias.

    Example:
        >>> class SemDias:
        ...     def vizinhos(self, conteudo, estacao, dia, top_k): return []
        >>> criar_ferramenta_dias_semelhantes(None, SemDias()).nome
        'dias_semelhantes'
    """
    return Ferramenta("dias_semelhantes", DESCRICAO_DIAS, ArgumentosDiasSemelhantes, partial(dias_semelhantes, consulta, busca), limite_itens=MAXIMO_DIAS)


def dias_semelhantes(consulta: ConsultaDados, busca: BuscaDeDias, argumentos: ArgumentosDiasSemelhantes) -> dict:
    """
    Os dias mais parecidos com o dia pedido.

    O resumo do dia é recalculado com as medições da estação (o mesmo cálculo da
    indexação), para servir de consulta.

    Returns:
        {"estacao", "data_referencia", "resumo_referencia", "dias": [{"data", "similaridade", "resumo"}], "aviso"}.

    Raises:
        ErroDeRegra: mais de uma estação sem o argumento estacao, estação
            inexistente ou dia sem medições.

    Example:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from src.agente.dias.indice import abrir_busca_de_dias, indexar_dias
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo, medicoes_de_exemplo
        >>> from src.agente.rag.embeddings import EmbedderSimulado
        >>> medicoes = medicoes_de_exemplo([7.0, 7.2, 7.0], horas=[0, 24, 48])   # 01, 02 e 03/06
        >>> pasta = Path(tempfile.mkdtemp())
        >>> _ = indexar_dias(medicoes, EmbedderSimulado(), pasta)
        >>> busca = abrir_busca_de_dias(EmbedderSimulado(), pasta)
        >>> resultado = dias_semelhantes(consulta_de_exemplo(medicoes), busca, ArgumentosDiasSemelhantes(data="2026-06-01", top_k=1))
        >>> resultado["dias"][0]["data"], resultado["dias"][0]["similaridade"]
        ('2026-06-03', 1.0)
    """
    estacao = consulta.resolver_estacao(argumentos.estacao)
    resumos = {r.dia: r for r in resumos_diarios(consulta.medicoes(FiltroMedicoes(estacao=estacao)))}
    referencia = resumos.get(argumentos.data)
    if referencia is None:
        periodo = f"{min(resumos):%d/%m/%Y} a {max(resumos):%d/%m/%Y}" if resumos else "nenhum"
        raise ErroDeRegra(f"sem medições em {argumentos.data:%d/%m/%Y} na estação {estacao}; dias com dados: {periodo}")
    vizinhos = busca.vizinhos(referencia.conteudo, estacao, argumentos.data.isoformat(), argumentos.top_k)
    return {
        "estacao": estacao,
        "data_referencia": argumentos.data.isoformat(),
        "resumo_referencia": referencia.conteudo,
        "dias": [{"data": t.secao, "similaridade": round(t.similaridade, 3), "resumo": t.texto.split("\n", 1)[-1]} for t in vizinhos],
        "aviso": AVISO_DIAS,
    }
