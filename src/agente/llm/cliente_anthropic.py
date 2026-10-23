"""
Adaptador do Claude (Anthropic): traduz o formato interno para a API e de volta.

Conceito
--------
Adaptador (padrão de projeto "Adapter"): o orquestrador fala só o formato
interno (Mensagem, ChamadaFerramenta, ResultadoFerramenta). Este módulo é o
ÚNICO que conhece o SDK anthropic, e faz a tradução nos dois sentidos:

    interno                        API da Anthropic (Messages API)
    Mensagem("usuario")        →   {"role": "user", "content": "..."}
    Mensagem("assistente")     →   {"role": "assistant", "content": [blocos]}
    Mensagem("ferramenta")     →   {"role": "user", "content": [tool_result, ...]}
    Mensagem("sistema")        →   {"role": "system", "content": "..."} (no meio da conversa)
    bloco tool_use             ←   ChamadaFerramenta
    usage, stop_reason         ←   tokens e motivo da parada

Trocar de fornecedor (DA1) é escrever outro adaptador, sem mexer no orquestrador.

Cuidados do Claude Haiku 5.5 (modelo da DA9):

- o raciocínio interno (blocos "thinking") vem ligado por padrão e precisa voltar
  INTACTO junto com os resultados das ferramentas. Por isso a resposta guarda
  os blocos originais em RespostaLLM.bruto, e o adaptador os reenvia como vieram;
- mudar o system, as ferramentas ou as mensagens anteriores no meio de uma
  pergunta invalida esses blocos (erro 400). A resposta forçada mantém as
  ferramentas e só as proíbe, com tool_choice {"type": "none"};
- temperature, top_p e top_k fora do padrão dão erro 400, então não são enviados;
- não existe fallback do servidor para recusas: uma recusa vira motivo_parada="recusa".

Modo estrito (strict: true, política POL-06): o Claude só gera argumentos válidos
para o schema. A API não aceita algumas restrições no modo estrito (minimum,
maximum, minLength, maxLength, maxItems, pattern) e tem tetos por pedido (24
parâmetros opcionais, 16 com anyOf, 20 ferramentas). Por isso schema_estrito()
leva essas restrições para a descrição, e o Pydantic continua validando tudo
do nosso lado. Se o catálogo passar dos tetos, o strict é desligado com um aviso no log.

Onde estudar: documentação de tool use da Anthropic e docs/agente/bibliotecas.md § 4.1
"""
import json
from collections.abc import Sequence
from typing import Any

import anthropic

from src.agente.contratos import ChamadaFerramenta, Mensagem, ResultadoFerramenta
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM
from src.logger import logger

# Tetos do modo estrito por pedido (documentação de structured outputs da Anthropic).
MAXIMO_FERRAMENTAS_ESTRITAS = 20
MAXIMO_OPCIONAIS_ESTRITOS = 24
MAXIMO_UNIOES_ESTRITAS = 16

# Restrições de JSON Schema que o modo estrito não aceita, e como descrevê-las em texto.
_SEM_SUPORTE_ESTRITO = {
    "minimum": "mínimo {}",
    "maximum": "máximo {}",
    "exclusiveMinimum": "maior que {}",
    "exclusiveMaximum": "menor que {}",
    "multipleOf": "múltiplo de {}",
    "minLength": "pelo menos {} caracteres",
    "maxLength": "no máximo {} caracteres",
    "maxItems": "no máximo {} itens",
    "pattern": "formato {}",
}

_MOTIVOS = {"end_turn": "fim", "tool_use": "ferramentas", "max_tokens": "limite_tokens", "refusal": "recusa"}


class ClienteAnthropic:
    """
    LLMClient para o Claude, pelo SDK oficial anthropic.

    Args:
        api_key: chave da Anthropic (ANTHROPIC_API_KEY). Só fica no cliente do SDK.
        modelo: ex.: "claude-haiku-5-5" (AGENTE_LLM_MODELO).
        max_tokens: teto de tokens por resposta, raciocínio incluído (AGENTE_MAX_TOKENS_SAIDA).
        esforco: "low", "medium" ou "high" (AGENTE_ESFORCO): profundidade do raciocínio e custo.
        timeout_segundos: tempo limite por tentativa (AGENTE_TIMEOUT_SEGUNDOS).
        max_retries: novas tentativas automáticas do SDK em 429, 5xx e falha de rede.
        cliente: cliente do SDK já pronto (os testes passam um falso, sem rede).

    Example:
        >>> class Falso:
        ...     class messages:
        ...         @staticmethod
        ...         def create(**parametros):
        ...             from types import SimpleNamespace as N
        ...             return N(content=[N(type="text", text="Olá!")], stop_reason="end_turn",
        ...                      usage=N(input_tokens=10, output_tokens=3))
        >>> llm = ClienteAnthropic("chave", "claude-haiku-5-5", cliente=Falso())
        >>> resposta = llm.gerar("system", [Mensagem.usuario("oi")], [])
        >>> resposta.texto, resposta.motivo_parada, resposta.tokens_entrada
        ('Olá!', 'fim', 10)
    """

    def __init__(
        self,
        api_key: str,
        modelo: str,
        max_tokens: int = 16000,
        esforco: str = "medium",
        timeout_segundos: float = 60,
        max_retries: int = 2,
        cliente: Any = None,
    ) -> None:
        """Guarda o modelo e os limites e cria o cliente do SDK (ou usa o recebido)."""
        self.modelo = modelo
        self.max_tokens = max_tokens
        self.esforco = esforco
        self.__cliente = cliente or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_segundos, max_retries=max_retries
        )

    @classmethod
    def de_config(cls, cfg) -> "ClienteAnthropic":
        """
        Cria o cliente a partir de ConfigAgente (load_config_agente()).

        Args:
            cfg: configuração do agente com fornecedor "anthropic".

        Returns:
            ClienteAnthropic pronto.
        """
        return cls(
            api_key=cfg.anthropic_api_key,
            modelo=cfg.llm_modelo,
            max_tokens=cfg.max_tokens_saida,
            esforco=cfg.esforco,
            timeout_segundos=cfg.timeout_segundos,
        )

    def gerar(
        self,
        system: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[dict[str, Any]],
        permitir_ferramentas: bool = True,
    ) -> RespostaLLM:
        """
        Uma chamada à Messages API.

        Raises:
            ErroProvedorLLM: qualquer erro do SDK, só com o TIPO do erro na mensagem.
        """
        parametros = self.parametros_do_pedido(system, mensagens, ferramentas, permitir_ferramentas)
        try:
            resposta = self.__cliente.messages.create(**parametros)
        except anthropic.APIError as erro:
            # Cuidado: "from None" corta o encadeamento com a exceção original,
            # cuja mensagem e request podem ter detalhes da chamada (POL-10).
            raise ErroProvedorLLM(type(erro).__name__) from None
        return resposta_da_api(resposta)

    def parametros_do_pedido(
        self,
        system: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[dict[str, Any]],
        permitir_ferramentas: bool = True,
    ) -> dict[str, Any]:
        """
        Parâmetros da Messages API para uma chamada (os mesmos no gerar() e na Batch API).

        Example:
            >>> llm = ClienteAnthropic("chave", "claude-haiku-5-5", cliente=object())
            >>> parametros = llm.parametros_do_pedido("system", [Mensagem.usuario("oi")], [])
            >>> parametros["model"], parametros["messages"], "tools" in parametros
            ('claude-haiku-5-5', [{'role': 'user', 'content': 'oi'}], False)
        """
        parametros: dict[str, Any] = {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": mensagens_para_api(mensagens),
            "output_config": {"effort": self.esforco},
            # Conceito: cache de prompt automático. O prefixo repetido (system +
            # ferramentas + histórico) é lido do cache a 10% do preço na chamada seguinte.
            "cache_control": {"type": "ephemeral"},
        }
        if ferramentas:
            parametros["tools"] = ferramentas_para_api(ferramentas)
            if not permitir_ferramentas:
                parametros["tool_choice"] = {"type": "none"}
        return parametros


def mensagens_para_api(mensagens: Sequence[Mensagem]) -> list[dict[str, Any]]:
    """
    Converte as mensagens internas no formato da Messages API.

    Args:
        mensagens: histórico interno, na ordem.

    Returns:
        Lista de {"role", "content"}.

    Example:
        >>> resultado = ResultadoFerramenta.ok("toolu_1", {"media": 7.3})
        >>> mensagens_para_api([Mensagem.usuario("pH?"), Mensagem.ferramenta([resultado])])[1]
        {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': '{"media":7.3}', 'is_error': False}]}
    """
    convertidas = []
    for mensagem in mensagens:
        if mensagem.papel == "usuario":
            convertidas.append({"role": "user", "content": mensagem.texto})
        elif mensagem.papel == "sistema":
            convertidas.append({"role": "system", "content": mensagem.texto})
        elif mensagem.papel == "ferramenta":
            convertidas.append({"role": "user", "content": [_resultado_para_api(r) for r in mensagem.resultados]})
        else:
            convertidas.append({"role": "assistant", "content": _conteudo_do_assistente(mensagem)})
    return convertidas


def _conteudo_do_assistente(mensagem: Mensagem) -> list:
    """Blocos originais, se houver (thinking intacto); senão, texto e tool_use montados a partir da mensagem."""
    if mensagem.bruto:
        return list(mensagem.bruto)
    blocos: list[dict[str, Any]] = [{"type": "text", "text": mensagem.texto}] if mensagem.texto else []
    blocos += [
        {"type": "tool_use", "id": chamada.id, "name": chamada.nome, "input": chamada.argumentos}
        for chamada in mensagem.chamadas
    ]
    return blocos


def _resultado_para_api(resultado: ResultadoFerramenta) -> dict[str, Any]:
    """
    Um tool_result: dados em JSON compacto ou o erro marcado com is_error.

    Conceito (POL-08): os resultados entram como DADOS do tool_result, nunca no
    system prompt, para um texto vindo de fora não ser tratado como instrução.
    """
    conteudo = (
        json.dumps(resultado.dados, ensure_ascii=False, separators=(",", ":"))
        if resultado.sucesso
        else resultado.erro
    )
    return {"type": "tool_result", "tool_use_id": resultado.chamada_id, "content": conteudo, "is_error": not resultado.sucesso}


def ferramentas_para_api(especificacoes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Especificações internas no formato da API, com modo estrito nas ferramentas que cabem nos tetos.

    Os tetos (24 parâmetros opcionais, 16 com anyOf e 20 ferramentas estritas)
    valem para o pedido INTEIRO. As ferramentas recebem strict em ordem
    (guloso), enquanto o orçamento couber; as que não cabem vão sem strict,
    com aviso no log. O catálogo põe as ferramentas de dados primeiro, então
    elas ficam com a garantia. Sem strict, o Pydantic continua validando (POL-06).

    Args:
        especificacoes: {"name", "description", "input_schema"} de cada ferramenta.

    Returns:
        Ferramentas no formato da API, com "strict": True nas que couberam.

    Example:
        >>> schema = {"type": "object", "properties": {"limite": {"type": "integer", "maximum": 50,
        ...           "description": "Itens."}}, "additionalProperties": False}
        >>> ferramenta = ferramentas_para_api([{"name": "x", "description": "d", "input_schema": schema}])[0]
        >>> ferramenta["strict"], ferramenta["input_schema"]["properties"]["limite"]
        (True, {'type': 'integer', 'description': 'Itens. Restrições: máximo 50.'})
    """
    resultado, sem_strict = [], []
    estritas = opcionais = unioes = 0
    for especificacao in especificacoes:
        schema = especificacao["input_schema"]
        propriedades = schema.get("properties", {})
        mais_opcionais = len(propriedades) - len(schema.get("required", []))
        mais_unioes = sum(1 for p in propriedades.values() if "anyOf" in p or isinstance(p.get("type"), list))
        cabe = (
            estritas + 1 <= MAXIMO_FERRAMENTAS_ESTRITAS
            and opcionais + mais_opcionais <= MAXIMO_OPCIONAIS_ESTRITOS
            and unioes + mais_unioes <= MAXIMO_UNIOES_ESTRITAS
        )
        if cabe:
            estritas, opcionais, unioes = estritas + 1, opcionais + mais_opcionais, unioes + mais_unioes
            resultado.append({**especificacao, "input_schema": schema_estrito(schema), "strict": True})
        else:
            sem_strict.append(especificacao["name"])
            resultado.append(dict(especificacao))
    if sem_strict:
        logger.warning("Agente: modo estrito desligado em %s (tetos do pedido atingidos)", ", ".join(sem_strict))
    return resultado


def schema_estrito(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Cópia do schema sem as restrições que o modo estrito não aceita, descritas no texto do campo.

    O Pydantic continua aplicando todas elas na validação (POL-06).

    Example:
        >>> schema_estrito({"type": "object", "properties": {"estacao": {"anyOf": [
        ...     {"type": "string", "pattern": "^[A-Z]+$"}, {"type": "null"}], "description": "Código."}}})
        {'type': 'object', 'properties': {'estacao': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'description': 'Código. Restrições: formato ^[A-Z]+$.'}}}
    """
    copia = dict(schema)
    if "properties" in copia:
        propriedades = {}
        for nome, propriedade in copia["properties"].items():
            limpa, restricoes = _sem_restricoes(propriedade)
            if restricoes:
                descricao = limpa.get("description", "")
                limpa["description"] = f"{descricao} Restrições: {'; '.join(restricoes)}.".strip()
            propriedades[nome] = limpa
        copia["properties"] = propriedades
    return copia


def _sem_restricoes(no: Any) -> tuple[Any, list[str]]:
    """Remove, em qualquer nível, as restrições sem suporte, e devolve a descrição de cada uma."""
    if isinstance(no, list):
        itens = [_sem_restricoes(item) for item in no]
        return [item for item, _ in itens], [r for _, restricoes in itens for r in restricoes]
    if not isinstance(no, dict):
        return no, []
    limpo, restricoes = {}, []
    for chave, valor in no.items():
        if chave in _SEM_SUPORTE_ESTRITO:
            restricoes.append(_SEM_SUPORTE_ESTRITO[chave].format(valor))
        elif chave == "minItems" and valor > 1:
            restricoes.append(f"pelo menos {valor} itens")
        else:
            limpo[chave], internas = _sem_restricoes(valor)
            restricoes += internas
    return limpo, restricoes


def resposta_da_api(resposta: Any) -> RespostaLLM:
    """
    Converte a resposta da API em RespostaLLM.

    Os blocos são lidos pelo "type", nunca pela posição: no Haiku 5.5 a resposta
    pode começar com blocos "thinking". Os tokens de entrada somam os lidos e
    gravados no cache, que também contam para o orçamento.

    Example:
        >>> from types import SimpleNamespace as N
        >>> resposta = N(stop_reason="tool_use", usage=N(input_tokens=900, output_tokens=40, cache_read_input_tokens=100),
        ...              content=[N(type="thinking", thinking="", signature="x"),
        ...                       N(type="tool_use", id="toolu_1", name="panorama_dados", input={})])
        >>> convertida = resposta_da_api(resposta)
        >>> convertida.chamadas[0].nome, convertida.motivo_parada, convertida.tokens_entrada, len(convertida.bruto)
        ('panorama_dados', 'ferramentas', 1000, 2)
    """
    texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
    chamadas = [
        ChamadaFerramenta(bloco.id, bloco.name, dict(bloco.input))
        for bloco in resposta.content
        if bloco.type == "tool_use"
    ]
    uso = resposta.usage
    entrada = (
        uso.input_tokens
        + (getattr(uso, "cache_read_input_tokens", 0) or 0)
        + (getattr(uso, "cache_creation_input_tokens", 0) or 0)
    )
    return RespostaLLM(
        texto=texto,
        chamadas=chamadas,
        tokens_entrada=entrada,
        tokens_saida=uso.output_tokens,
        motivo_parada=_MOTIVOS.get(resposta.stop_reason, "fim"),
        bruto=tuple(resposta.content),
    )
