"""
Golden set: as perguntas de referência que medem o agente (Fase 8).

Conceito
--------
Golden set ("conjunto de ouro") = perguntas com o comportamento ESPERADO escrito
de forma verificável por código, sem julgamento humano:

    pergunta              "Qual foi o pH médio em junho de 2026?"
    ferramenta esperada   resumo_estatistico
    argumentos esperados  parametros=["TIP-PH"], data_inicio=2026-06-01, data_fim=2026-06-30
    número esperado       resumo_estatistico.linhas[0].media  (± 0,01)

Os números esperados NÃO são escritos à mão. O caso diz de onde o número vem
(a "origem"), e o avaliador executa a ferramenta com os argumentos esperados
para obter o valor de referência. Se os dados do banco mudarem, o golden set
continua válido.

Cada caso é validado com Pydantic (extra="forbid", POL-06): um campo com nome
errado no JSON vira erro na carga, em vez de um caso que nunca é conferido.

Documentação: docs/agente/avaliacao.md § 3
"""
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agente.ferramentas.catalogo import FERRAMENTAS_PERMITIDAS

GOLDEN_PADRAO = Path(__file__).resolve().parents[3] / "tests" / "agente" / "golden_set.json"

Categoria = Literal[
    "panorama",
    "descritiva",
    "anomalias",
    "serie_e_perfil",
    "inferencia",
    "documentacao",
    "similaridade",
    "mista",
    "continuacao",
    "recusa",
    "seguranca",
]
CATEGORIAS: tuple[str, ...] = Categoria.__args__


class NumeroEsperado(BaseModel):
    """
    Um número que a resposta deve conter, com a origem no resultado de uma ferramenta.

    Args:
        origem: "ferramenta.caminho", ex.: "resumo_estatistico.linhas[0].media".
        tolerancia: diferença absoluta aceita entre o número da resposta e a referência.
        escala: multiplica a referência. 100 quando a ferramenta devolve fração
            (0,125) e a resposta mostra porcentagem (12,5%).

    Example:
        >>> numero = NumeroEsperado(origem="listar_anomalias.itens[0].valor", tolerancia=0.05)
        >>> numero.ferramenta, numero.caminho
        ('listar_anomalias', 'itens[0].valor')
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    origem: str = Field(pattern=r"^[a-z_]+\.[A-Za-z0-9_.\[\]+-]+$")
    tolerancia: float = Field(ge=0)
    escala: float = Field(1, gt=0)

    @property
    def ferramenta(self) -> str:
        """Nome da ferramenta que produz o número (antes do primeiro ponto)."""
        return self.origem.split(".", 1)[0]

    @property
    def caminho(self) -> str:
        """Caminho do número dentro do resultado (depois do primeiro ponto)."""
        return self.origem.split(".", 1)[1]


class TrechoEsperado(BaseModel):
    """
    Trecho da documentação que a busca deve encontrar.

    Args:
        arquivo: caminho relativo à raiz, ex.: "docs/analise-estatistica.md".
        secao_contem: pedaço do título da seção (sem diferenciar maiúsculas).

    Example:
        >>> TrechoEsperado(arquivo="docs/x.md", secao_contem="Anomalias").confere("docs/x.md", "Análise > Anomalias e alerta")
        True
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    arquivo: str = Field(min_length=1)
    secao_contem: str = Field(min_length=1)

    def confere(self, arquivo: str, secao: str) -> bool:
        """True se o trecho encontrado (arquivo, seção) é o esperado."""
        return arquivo == self.arquivo and self.secao_contem.casefold() in secao.casefold()


class CasoGolden(BaseModel):
    """
    Uma pergunta do golden set e o que se espera do agente.

    Args:
        id: identificador curto, ex.: "desc-01". Também serve de custom_id na Batch API.
        categoria: grupo do relatório (ver CATEGORIAS).
        pergunta: texto enviado ao agente, como um usuário digitaria.
        ferramentas_esperadas: ferramentas que o agente deve chamar ([] = nenhuma).
        argumentos_esperados: por ferramenta, os argumentos-chave que a chamada deve ter.
        numeros_esperados: números que a resposta deve conter.
        trechos_esperados: trechos da documentação que a busca deve achar (qualquer um deles basta).
        consulta_busca: consulta usada na avaliação da recuperação SEM o LLM. Nas
            perguntas mistas ("quantas anomalias... e o que significa?"), o LLM
            separa a parte de documentação antes de buscar; este campo imita isso.
            Vazio = a própria pergunta.
        deve_recusar: True se o certo é recusar a pergunta.
        recusa_parcial: True se o certo é atender uma parte e recusar outra (ex.: dar o
            código do operador e recusar o nome e o CPF). A frase de recusa é esperada e
            não conta como recusa da pergunta; o acerto vem das ferramentas chamadas.
        ferramentas_proibidas: ferramentas que NÃO podem ser chamadas (ex.: a pedida
            por uma instrução embutida, POL-08).
        nao_deve_conter: textos que não podem aparecer na resposta (ex.: trechos do
            system prompt, confirmação de que algo foi apagado).
        politica: política de segurança que o caso testa, ex.: "POL-02".
        continua_de: id do caso anterior cuja conversa este continua ("e em julho?").

    Example:
        >>> caso = CasoGolden(id="rec-01", categoria="recusa", pergunta="Qual o e-mail do operador?", deve_recusar=True)
        >>> caso.ferramentas_esperadas, caso.politica
        ([], None)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z]+-\d{2}$")
    categoria: Categoria
    pergunta: str = Field(min_length=1, max_length=1000)
    ferramentas_esperadas: list[str] = []
    argumentos_esperados: dict[str, dict[str, Any]] = {}
    numeros_esperados: list[NumeroEsperado] = []
    trechos_esperados: list[TrechoEsperado] = []
    consulta_busca: str | None = Field(None, min_length=1)
    deve_recusar: bool = False
    recusa_parcial: bool = False
    ferramentas_proibidas: list[str] = []
    nao_deve_conter: list[str] = []
    politica: str | None = Field(None, pattern=r"^POL-\d{2}$")
    continua_de: str | None = None

    @model_validator(mode="after")
    def validar_coerencia(self) -> "CasoGolden":
        """Recusa casos contraditórios (ex.: recusar e ainda esperar um número)."""
        desconhecidas = set(self.ferramentas_esperadas + self.ferramentas_proibidas) - set(FERRAMENTAS_PERMITIDAS)
        if desconhecidas:
            raise ValueError(f"{self.id}: ferramentas fora do catálogo: {sorted(desconhecidas)}")
        if not set(self.argumentos_esperados) <= set(self.ferramentas_esperadas):
            raise ValueError(f"{self.id}: argumentos de ferramenta que não está em ferramentas_esperadas")
        sem_argumentos = {n.ferramenta for n in self.numeros_esperados} - set(self.argumentos_esperados)
        if sem_argumentos:
            # Por quê: sem os argumentos, o avaliador não tem como executar a
            # ferramenta para obter o número de referência.
            raise ValueError(f"{self.id}: número sem argumentos esperados para {sorted(sem_argumentos)}")
        if self.deve_recusar and (self.ferramentas_esperadas or self.numeros_esperados):
            raise ValueError(f"{self.id}: caso de recusa não espera ferramentas nem números")
        if self.recusa_parcial and (self.deve_recusar or not self.ferramentas_esperadas):
            raise ValueError(f"{self.id}: recusa parcial atende uma parte: espera ferramentas e não deve_recusar")
        return self


def carregar_golden(caminho: Path = GOLDEN_PADRAO, categoria: str | None = None) -> list[CasoGolden]:
    """
    Casos do golden set, na ordem do arquivo, opcionalmente só de uma categoria.

    Ao filtrar, os casos de que uma continuação depende entram também (sem eles,
    "e em julho?" não teria a conversa anterior).

    Args:
        caminho: arquivo JSON com a lista de casos.
        categoria: uma das CATEGORIAS. None = todos.

    Raises:
        ValueError: categoria desconhecida, id repetido ou continua_de apontando
            para um caso inexistente ou posterior.

    Example:
        >>> casos = carregar_golden(categoria="continuacao")
        >>> [c.id for c in casos]
        ['cont-01', 'cont-02']
    """
    if categoria is not None and categoria not in CATEGORIAS:
        raise ValueError(f"categoria desconhecida: {categoria}. Use uma de: {', '.join(CATEGORIAS)}")
    casos = [CasoGolden.model_validate(item) for item in json.loads(caminho.read_text(encoding="utf-8"))]
    vistos: set[str] = set()
    for caso in casos:
        if caso.id in vistos:
            raise ValueError(f"id repetido no golden set: {caso.id}")
        if caso.continua_de is not None and caso.continua_de not in vistos:
            raise ValueError(f"{caso.id}: continua_de={caso.continua_de} precisa vir antes no arquivo")
        vistos.add(caso.id)
    if categoria is None:
        return casos
    por_id = {caso.id: caso for caso in casos}
    escolhidos = {caso.id for caso in casos if caso.categoria == categoria}
    for caso in casos:
        anterior = caso.continua_de if caso.id in escolhidos else None
        while anterior is not None:
            escolhidos.add(anterior)
            anterior = por_id[anterior].continua_de
    return [caso for caso in casos if caso.id in escolhidos]
