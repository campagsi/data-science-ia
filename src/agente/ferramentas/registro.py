"""
Registro das ferramentas: catálogo, validação, execução e tratamento de erros.

Conceito
--------
O registro é o ponto único por onde o agente executa uma ferramenta. Ele
aplica, para toda ferramenta, o fluxo de docs/agente/ferramentas.md § 5:

    ferramenta existe? → argumentos válidos? → executa → erro de regra?
    → erro inesperado? → retorno acima do limite? → JSON compacto

Erro NÃO interrompe o agente: vira ResultadoFerramenta(sucesso=False) com uma
mensagem curta, e o LLM pode corrigir os argumentos ou explicar ao usuário.
A mensagem de um erro inesperado (ex.: banco fora do ar) é genérica, e o
detalhe vai só para o log, sem dado sensível (políticas POL-06 e POL-10).

O limite de itens por lista (AGENTE_MAX_LINHAS) protege o custo: um retorno
de 10 mil linhas seria enviado inteiro ao LLM, e cada linha custa tokens (POL-07).

Documentação: docs/agente/ferramentas.md § 5
"""
from typing import Any

from pydantic import ValidationError

from src.agente.contratos import ChamadaFerramenta, ResultadoFerramenta
from src.agente.ferramentas.base import ErroDeRegra, Ferramenta, normalizar_json
from src.logger import logger

ERRO_INESPERADO = "erro interno ao consultar os dados; tente de novo ou reformule a pergunta"


class RegistroFerramentas:
    """
    Catálogo de ferramentas do agente.

    Args:
        max_linhas: máximo de itens por lista no retorno (AGENTE_MAX_LINHAS).

    Example:
        >>> from pydantic import BaseModel, ConfigDict
        >>> class Vazio(BaseModel):
        ...     model_config = ConfigDict(extra="forbid")
        >>> registro = RegistroFerramentas(max_linhas=2)
        >>> registro.registrar(Ferramenta("numeros", "Devolve números.", Vazio, lambda a: {"itens": [1, 2, 3]}))
        >>> registro.executar(ChamadaFerramenta("c1", "numeros")).dados
        {'itens': [1, 2], 'truncado': True, 'total_itens': 3}
        >>> registro.executar(ChamadaFerramenta("c2", "apagar")).erro
        'ferramenta desconhecida: apagar. Disponíveis: numeros'
    """

    def __init__(self, max_linhas: int = 50) -> None:
        """Cria o catálogo vazio com o limite de itens por lista."""
        if max_linhas < 1:
            raise ValueError("max_linhas deve ser pelo menos 1")
        self.__max_linhas = max_linhas
        self.__ferramentas: dict[str, Ferramenta] = {}

    def registrar(self, ferramenta: Ferramenta) -> None:
        """
        Acrescenta uma ferramenta ao catálogo.

        Raises:
            ValueError: já existe uma ferramenta com o mesmo nome.
        """
        if ferramenta.nome in self.__ferramentas:
            raise ValueError(f"ferramenta já registrada: {ferramenta.nome}")
        self.__ferramentas[ferramenta.nome] = ferramenta

    def nomes(self) -> tuple[str, ...]:
        """Nomes das ferramentas, na ordem de registro."""
        return tuple(self.__ferramentas)

    def especificacoes(self) -> list[dict[str, Any]]:
        """Especificações (nome, descrição, JSON Schema) enviadas ao LLM."""
        return [ferramenta.especificacao() for ferramenta in self.__ferramentas.values()]

    def executar(self, chamada: ChamadaFerramenta) -> ResultadoFerramenta:
        """
        Executa a chamada pedida pelo LLM, sem nunca lançar exceção.

        Args:
            chamada: nome da ferramenta e argumentos vindos do LLM.

        Returns:
            ResultadoFerramenta com os dados em JSON compacto, ou com o erro.
        """
        ferramenta = self.__ferramentas.get(chamada.nome)
        if ferramenta is None:
            disponiveis = ", ".join(self.__ferramentas) or "nenhuma"
            return ResultadoFerramenta.falha(chamada.id, f"ferramenta desconhecida: {chamada.nome}. Disponíveis: {disponiveis}")
        try:
            dados = ferramenta.executar(chamada.argumentos)
        except ValidationError as erro:
            return ResultadoFerramenta.falha(chamada.id, formatar_erros_de_validacao(erro))
        except ErroDeRegra as erro:
            return ResultadoFerramenta.falha(chamada.id, str(erro))
        except Exception as erro:
            # Cuidado: só o tipo da exceção vai para o log. A mensagem de um erro
            # de banco pode trazer detalhes da conexão (POL-10).
            logger.error("Agente: erro inesperado ferramenta=%s erro=%s", chamada.nome, type(erro).__name__)
            return ResultadoFerramenta.falha(chamada.id, ERRO_INESPERADO)
        limite = ferramenta.limite_itens or self.__max_linhas
        return ResultadoFerramenta.ok(chamada.id, truncar_listas(normalizar_json(dados), limite))


def formatar_erros_de_validacao(erro: ValidationError) -> str:
    """
    Mensagem curta com o campo e o motivo de cada erro, sem os valores recebidos.

    Args:
        erro: erro do Pydantic.

    Returns:
        Ex.: "argumentos inválidos: limite: Input should be less than or equal to 50".

    Example:
        >>> from src.agente.ferramentas.argumentos import ArgumentosAnomalias
        >>> try:
        ...     ArgumentosAnomalias(limite=99, apagar=True)
        ... except ValidationError as erro:
        ...     print(formatar_erros_de_validacao(erro))
        argumentos inválidos: limite: Input should be less than or equal to 50; apagar: Extra inputs are not permitted
    """
    partes = []
    for detalhe in erro.errors():
        campo = ".".join(str(parte) for parte in detalhe["loc"]) or "argumentos"
        partes.append(f"{campo}: {detalhe['msg'].removeprefix('Value error, ')}")
    return "argumentos inválidos: " + "; ".join(partes)


def truncar_listas(dados: dict, limite: int) -> dict:
    """
    Corta as listas do primeiro nível que passam do limite e avisa quanto havia.

    Args:
        dados: retorno já normalizado.
        limite: máximo de itens por lista.

    Returns:
        Os dados com as listas cortadas, "truncado": True e "total_<chave>"
        para cada lista cortada. Sem corte, os dados ficam iguais.

    Example:
        >>> truncar_listas({"pontos": [1, 2, 3], "unidade": "°C"}, 2)
        {'pontos': [1, 2], 'unidade': '°C', 'truncado': True, 'total_pontos': 3}
    """
    resultado = dict(dados)
    for chave, valor in dados.items():
        if isinstance(valor, list) and len(valor) > limite:
            resultado[chave] = valor[:limite]
            resultado["truncado"] = True
            resultado[f"total_{chave}"] = len(valor)
    return resultado
