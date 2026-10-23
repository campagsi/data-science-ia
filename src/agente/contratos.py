"""
Contratos trocados entre as camadas do agente.

Conceito
--------
Um contrato é o formato combinado entre quem produz e quem consome um dado.
O orquestrador, os adaptadores de LLM e as ferramentas só se comunicam por
estes tipos. Por isso, trocar o fornecedor do LLM não muda o orquestrador: o
adaptador traduz Mensagem, ChamadaFerramenta e ResultadoFerramenta para o
formato do fornecedor (blocos tool_use/tool_result na Anthropic) e de volta.

Os tipos são imutáveis (dataclass com frozen=True). Uma mensagem já enviada
ao LLM não pode ser alterada por engano por outra parte do código, e o
histórico de uma conversa passa a ser um registro confiável do que aconteceu.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_2.py (saída estruturada)
Documentação: docs/agente/arquitetura.md § 4
"""
import json
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

Papel = Literal["usuario", "assistente", "ferramenta", "sistema"]
TipoFonte = Literal["ferramenta", "documento"]

PAPEIS: tuple[str, ...] = get_args(Papel)
TIPOS_FONTE: tuple[str, ...] = get_args(TipoFonte)


@dataclass(frozen=True)
class ChamadaFerramenta:
    """
    Pedido do LLM para executar uma ferramenta.

    O LLM não executa nada. Ele devolve o nome da ferramenta e os argumentos,
    e o código do agente valida e executa.

    Args:
        id: identificador dado pelo provedor. Volta no ResultadoFerramenta
            para o LLM saber a qual pedido o resultado responde.
        nome: nome da ferramenta, ex.: "resumo_estatistico".
        argumentos: argumentos como vieram do LLM, ainda não validados.

    Raises:
        ValueError: se id ou nome estiverem vazios.

    Example:
        >>> chamada = ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})
        >>> chamada.nome
        'resumo_estatistico'
        >>> chamada.nome = "outra"
        Traceback (most recent call last):
        ...
        dataclasses.FrozenInstanceError: cannot assign to field 'nome'
    """

    id: str
    nome: str
    # Cuidado: frozen impede trocar o campo, mas o dict continua mutável.
    # Ninguém deve alterar os argumentos depois de recebidos do LLM.
    argumentos: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Recusa chamada sem id ou sem nome."""
        if not self.id:
            raise ValueError("ChamadaFerramenta exige um id")
        if not self.nome:
            raise ValueError("ChamadaFerramenta exige o nome da ferramenta")


@dataclass(frozen=True)
class ResultadoFerramenta:
    """
    O que a ferramenta devolveu, ou o erro, enviado de volta ao LLM.

    Um erro de ferramenta não interrompe o agente: ele volta ao LLM, que pode
    corrigir os argumentos ou explicar o problema ao usuário.

    Args:
        chamada_id: id da ChamadaFerramenta respondida.
        sucesso: True se a ferramenta executou.
        dados: retorno da ferramenta (JSON compacto).
        erro: mensagem curta e sem dados sensíveis. Obrigatória quando sucesso=False.

    Raises:
        ValueError: se sucesso e erro forem incoerentes.

    Example:
        >>> ResultadoFerramenta.ok("c1", {"media": 7.3}).dados
        {'media': 7.3}
        >>> ResultadoFerramenta.falha("c1", "data_fim anterior a data_inicio").sucesso
        False
    """

    chamada_id: str
    sucesso: bool
    dados: dict[str, Any] = field(default_factory=dict)
    erro: str | None = None

    def __post_init__(self) -> None:
        """Confere a coerência entre sucesso e erro."""
        if not self.sucesso and not self.erro:
            raise ValueError("ResultadoFerramenta sem sucesso exige a mensagem de erro")
        if self.sucesso and self.erro:
            raise ValueError("ResultadoFerramenta com sucesso não pode ter erro")

    @classmethod
    def ok(cls, chamada_id: str, dados: dict[str, Any]) -> "ResultadoFerramenta":
        """Resultado de uma execução bem-sucedida."""
        return cls(chamada_id=chamada_id, sucesso=True, dados=dados)

    @classmethod
    def falha(cls, chamada_id: str, erro: str) -> "ResultadoFerramenta":
        """Resultado de uma execução com erro (argumento inválido, regra violada...)."""
        return cls(chamada_id=chamada_id, sucesso=False, erro=erro)


@dataclass(frozen=True)
class Mensagem:
    """
    Uma mensagem da conversa no formato interno, independente do fornecedor.

    Cada papel tem um formato:

    - usuario: só texto (a pergunta);
    - assistente: texto e/ou pedidos de ferramenta (chamadas);
    - ferramenta: só os resultados das chamadas da mensagem anterior;
    - sistema: instrução do orquestrador no meio da conversa, só texto
      (ex.: o pedido de correção da política POL-03).

    Args:
        papel: "usuario", "assistente", "ferramenta" ou "sistema".
        texto: conteúdo em texto.
        chamadas: pedidos de ferramenta (só no papel assistente).
        resultados: resultados das ferramentas (só no papel ferramenta).
        bruto: blocos originais do fornecedor (só no papel assistente), que
            o adaptador devolve INTACTOS na chamada seguinte. Opaco para o
            resto do código. Ex.: os blocos de raciocínio ("thinking") do
            Claude, que a API exige de volta sem nenhuma alteração.

    Raises:
        ValueError: se o conteúdo não combinar com o papel.

    Example:
        >>> Mensagem.usuario("Qual o pH médio em junho?").papel
        'usuario'
        >>> pedido = Mensagem.assistente(chamadas=[ChamadaFerramenta("c1", "panorama_dados")])
        >>> type(pedido.chamadas).__name__, len(pedido.chamadas)
        ('tuple', 1)
        >>> Mensagem("usuario", chamadas=[ChamadaFerramenta("c1", "panorama_dados")])
        Traceback (most recent call last):
        ...
        ValueError: só o assistente pede ferramentas
    """

    papel: Papel
    texto: str = ""
    chamadas: tuple[ChamadaFerramenta, ...] = ()
    resultados: tuple[ResultadoFerramenta, ...] = ()
    # compare=False e repr=False: os blocos do fornecedor não fazem parte do
    # significado da mensagem e poluiriam a comparação e a impressão.
    bruto: tuple[Any, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        """Converte listas em tuplas e confere se o conteúdo combina com o papel."""
        # Por quê: aceitar listas é mais cômodo para quem cria a mensagem, mas a
        # tupla é que garante a imutabilidade. object.__setattr__ é o jeito de
        # ajustar um campo dentro de uma dataclass frozen.
        object.__setattr__(self, "chamadas", tuple(self.chamadas))
        object.__setattr__(self, "resultados", tuple(self.resultados))
        object.__setattr__(self, "bruto", tuple(self.bruto))

        if self.papel not in PAPEIS:
            raise ValueError(f"papel inválido: {self.papel!r}")
        if self.chamadas and self.papel != "assistente":
            raise ValueError("só o assistente pede ferramentas")
        if self.resultados and self.papel != "ferramenta":
            raise ValueError("só a mensagem de ferramenta leva resultados")
        if self.papel == "ferramenta" and not self.resultados:
            raise ValueError("mensagem de ferramenta exige ao menos um resultado")
        if self.papel == "usuario" and not self.texto.strip():
            raise ValueError("mensagem do usuário exige texto")
        if self.papel == "assistente" and not self.texto and not self.chamadas:
            raise ValueError("mensagem do assistente exige texto ou chamadas")
        if self.bruto and self.papel != "assistente":
            raise ValueError("só a mensagem do assistente leva blocos do fornecedor")
        if self.papel == "sistema" and not self.texto.strip():
            raise ValueError("mensagem de sistema exige texto")

    @classmethod
    def usuario(cls, texto: str) -> "Mensagem":
        """Pergunta do usuário."""
        return cls(papel="usuario", texto=texto)

    @classmethod
    def assistente(cls, texto: str = "", chamadas=(), bruto=()) -> "Mensagem":
        """Resposta do LLM: texto final e/ou pedidos de ferramenta, com os blocos originais do fornecedor."""
        return cls(papel="assistente", texto=texto, chamadas=tuple(chamadas), bruto=tuple(bruto))

    @classmethod
    def sistema(cls, texto: str) -> "Mensagem":
        """Instrução do orquestrador no meio da conversa (canal do operador, não do usuário)."""
        return cls(papel="sistema", texto=texto)

    @classmethod
    def ferramenta(cls, resultados) -> "Mensagem":
        """Resultados das ferramentas pedidas na mensagem anterior do assistente."""
        return cls(papel="ferramenta", resultados=tuple(resultados))


@dataclass(frozen=True)
class Fonte:
    """
    Origem de uma informação usada na resposta, mostrada ao usuário.

    As fontes são montadas pelo código a partir do que foi realmente
    executado, nunca pelo LLM. Assim, uma fonte não pode ser inventada.

    Args:
        tipo: "ferramenta" ou "documento".
        descricao: ex.: 'resumo_estatistico(parametros=["TIP-PH"])' ou
            "docs/analise-estatistica.md § Anomalias".

    Example:
        >>> Fonte.de_chamada(ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})).descricao
        'resumo_estatistico(parametros=["TIP-PH"])'
    """

    tipo: TipoFonte
    descricao: str

    def __post_init__(self) -> None:
        """Confere o tipo e a descrição da fonte."""
        if self.tipo not in TIPOS_FONTE:
            raise ValueError(f"tipo de fonte inválido: {self.tipo!r}")
        if not self.descricao:
            raise ValueError("Fonte exige a descrição")

    @classmethod
    def de_chamada(cls, chamada: ChamadaFerramenta) -> "Fonte":
        """Fonte do tipo ferramenta, descrita pela chamada executada."""
        return cls(tipo="ferramenta", descricao=formatar_chamada(chamada))


@dataclass(frozen=True)
class RespostaAgente:
    """
    Resposta final do agente para uma pergunta.

    Args:
        texto: resposta em Markdown, redigida pelo LLM.
        conversa_id: conversa à qual a pergunta pertence. Serve para continuar
            a conversa ("e em julho?").
        fontes: ferramentas e documentos usados (montados pelo código).
        tokens_entrada: soma dos tokens de entrada de todas as chamadas ao LLM.
        tokens_saida: soma dos tokens de saída.
        latencia_ms: tempo total da pergunta em milissegundos.
        falhou: True se o provedor do LLM falhou e o texto é a mensagem amigável
            de erro. A interface web usa para responder HTTP 503.

    Example:
        >>> resposta = RespostaAgente("O pH médio foi 7,30.", "c-1", fontes=[Fonte("documento", "docs/x.md")])
        >>> resposta.fontes[0].tipo, resposta.tokens_entrada
        ('documento', 0)
    """

    texto: str
    conversa_id: str
    fontes: tuple[Fonte, ...] = ()
    tokens_entrada: int = 0
    tokens_saida: int = 0
    latencia_ms: int = 0
    falhou: bool = False

    def __post_init__(self) -> None:
        """Converte as fontes em tupla e recusa números negativos."""
        object.__setattr__(self, "fontes", tuple(self.fontes))
        if min(self.tokens_entrada, self.tokens_saida, self.latencia_ms) < 0:
            raise ValueError("tokens e latência não podem ser negativos")


def formatar_chamada(chamada: ChamadaFerramenta) -> str:
    """
    Descrição legível de uma chamada, usada nas fontes e no log.

    Os valores saem em JSON (aspas duplas, acentos preservados), na ordem
    em que o LLM enviou os argumentos.

    Args:
        chamada: chamada executada.

    Returns:
        Texto no formato nome(arg=valor, ...).

    Example:
        >>> formatar_chamada(ChamadaFerramenta("c1", "listar_anomalias",
        ...                                    {"parametro": "TIP-PH", "limite": 5}))
        'listar_anomalias(parametro="TIP-PH", limite=5)'
        >>> formatar_chamada(ChamadaFerramenta("c2", "panorama_dados"))
        'panorama_dados()'
    """
    argumentos = ", ".join(
        f"{nome}={json.dumps(valor, ensure_ascii=False, default=str)}"
        for nome, valor in chamada.argumentos.items()
    )
    return f"{chamada.nome}({argumentos})"
