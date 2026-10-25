"""
Adaptador da OpenAI (Chat Completions) para a interface LLMClient (DA11).

Conceito
--------
Adaptador (padrão Adapter): o agente fala um formato interno (Mensagem,
ChamadaFerramenta, RespostaLLM), e cada fornecedor tem o seu. O adaptador
traduz nos dois sentidos, e o resto do agente não sabe qual LLM está do outro lado:

    interno                              Chat Completions da OpenAI
    system prompt                    →   {"role": "system", "content": ...} (primeira mensagem)
    Mensagem.usuario("pH?")          →   {"role": "user", "content": "pH?"}
    Mensagem.assistente(chamadas)    →   {"role": "assistant", "tool_calls": [{"id", "function": {"name", "arguments"}}]}
    Mensagem.ferramenta(resultados)  →   um {"role": "tool", "tool_call_id", "content"} por resultado
    Mensagem.sistema (correção POL-03) → {"role": "system", ...} no meio da conversa

Diferenças em relação à Anthropic, que o adaptador absorve:

- os argumentos da ferramenta chegam como TEXTO JSON ("{\\"parametros\\": [...]}"), e não
  como dict. Um JSON quebrado vira um argumento inválido, que o registro devolve
  ao LLM como erro de validação (POL-06), sem derrubar a pergunta;
- "proibir ferramentas" na resposta forçada (POL-07) é tool_choice="none";
- não há blocos de raciocínio para devolver intactos (Mensagem.bruto fica vazio);
- o cache de prompt é automático acima de ~1.024 tokens de prefixo igual.

Erro do SDK vira ErroProvedorLLM só com o TIPO do erro (POL-10: a mensagem
original pode ter detalhes do pedido).

Documentação: docs/agente/arquitetura.md § 4 e docs/agente/bibliotecas.md (openai)
"""
import json
from collections.abc import Sequence
from typing import Any

import openai

from src.agente.contratos import ChamadaFerramenta, Mensagem, ResultadoFerramenta
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM

_MOTIVOS = {"stop": "fim", "tool_calls": "ferramentas", "function_call": "ferramentas", "length": "limite_tokens", "content_filter": "recusa"}
# Modelos de raciocínio aceitam reasoning_effort; os outros recusam o parâmetro.
_PREFIXOS_RACIOCINIO = ("gpt-5", "o1", "o3", "o4")


class ClienteOpenAI:
    """
    LLMClient para os modelos da OpenAI, pelo SDK oficial openai.

    Args:
        api_key: chave da OpenAI (OPENAI_API_KEY). Só fica no cliente do SDK.
        modelo: ex.: "gpt-4.1-mini" (AGENTE_LLM_MODELO).
        max_tokens: teto de tokens por resposta (AGENTE_MAX_TOKENS_SAIDA).
        esforco: "low", "medium" ou "high" (AGENTE_ESFORCO). Só vale para modelos de raciocínio.
        timeout_segundos: tempo limite por tentativa (AGENTE_TIMEOUT_SEGUNDOS).
        max_retries: novas tentativas automáticas do SDK em 429, 5xx e falha de rede.
        cliente: cliente do SDK já pronto (os testes passam um falso, sem rede).

    Example:
        >>> from types import SimpleNamespace as N
        >>> class Falso:
        ...     class chat:
        ...         class completions:
        ...             @staticmethod
        ...             def create(**parametros):
        ...                 mensagem = N(content="Olá!", tool_calls=None, refusal=None)
        ...                 return N(choices=[N(message=mensagem, finish_reason="stop")], usage=N(prompt_tokens=10, completion_tokens=3))
        >>> llm = ClienteOpenAI("chave", "gpt-4.1-mini", cliente=Falso())
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
        self.__cliente = cliente or openai.OpenAI(api_key=api_key, timeout=timeout_segundos, max_retries=max_retries)

    @classmethod
    def de_config(cls, cfg) -> "ClienteOpenAI":
        """
        Cria o cliente a partir de ConfigAgente (load_config_agente()).

        Example:
            >>> from src.config import ConfigAgente
            >>> ClienteOpenAI.de_config(ConfigAgente("openai", "gpt-4.1-mini", openai_api_key="sk-x")).modelo
            'gpt-4.1-mini'
        """
        return cls(
            api_key=cfg.openai_api_key,
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
        Uma chamada ao Chat Completions.

        Raises:
            ErroProvedorLLM: qualquer erro do SDK, só com o TIPO do erro na mensagem.
        """
        try:
            resposta = self.__cliente.chat.completions.create(**self.parametros_do_pedido(system, mensagens, ferramentas, permitir_ferramentas))
        except openai.APIError as erro:
            # Cuidado: "from None" corta o encadeamento com a exceção original (POL-10).
            raise ErroProvedorLLM(type(erro).__name__) from None
        return resposta_da_openai(resposta)

    def parametros_do_pedido(
        self,
        system: str,
        mensagens: Sequence[Mensagem],
        ferramentas: Sequence[dict[str, Any]],
        permitir_ferramentas: bool = True,
    ) -> dict[str, Any]:
        """
        Parâmetros do Chat Completions para uma chamada.

        Example:
            >>> llm = ClienteOpenAI("chave", "gpt-4.1-mini", cliente=object())
            >>> p = llm.parametros_do_pedido("system", [Mensagem.usuario("oi")], [{"name": "x", "description": "d", "input_schema": {"type": "object"}}], False)
            >>> p["messages"][0], p["tool_choice"], "reasoning_effort" in p, p["temperature"]
            ({'role': 'system', 'content': 'system'}, 'none', False, 0)
        """
        parametros: dict[str, Any] = {
            "model": self.modelo,
            "max_completion_tokens": self.max_tokens,
            "messages": mensagens_para_openai(system, mensagens),
        }
        if self.modelo.startswith(_PREFIXOS_RACIOCINIO) and "chat" not in self.modelo:
            parametros["reasoning_effort"] = self.esforco
        else:
            # Por quê: com temperatura 0, a mesma pergunta leva à mesma escolha de ferramenta
            # e a quase a mesma resposta (o padrão, 1,0, variava entre recusar e responder).
            # Os modelos de raciocínio não aceitam o parâmetro.
            parametros["temperature"] = 0
        if ferramentas:
            parametros["tools"] = ferramentas_para_openai(ferramentas)
            parametros["tool_choice"] = "auto" if permitir_ferramentas else "none"
        return parametros


def mensagens_para_openai(system: str, mensagens: Sequence[Mensagem]) -> list[dict[str, Any]]:
    """
    Converte o system prompt e o histórico interno nas mensagens do Chat Completions.

    Example:
        >>> chamada = ChamadaFerramenta("call_1", "resumo_estatistico", {"parametros": ["TIP-PH"]})
        >>> convertidas = mensagens_para_openai("regras", [Mensagem.usuario("pH?"), Mensagem.assistente(chamadas=[chamada]),
        ...                                               Mensagem.ferramenta([ResultadoFerramenta.ok("call_1", {"media": 7.3})])])
        >>> convertidas[2]["tool_calls"][0]["function"], convertidas[3]
        ({'name': 'resumo_estatistico', 'arguments': '{"parametros": ["TIP-PH"]}'}, {'role': 'tool', 'tool_call_id': 'call_1', 'content': '{"media":7.3}'})
    """
    convertidas: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for mensagem in mensagens:
        if mensagem.papel == "usuario":
            convertidas.append({"role": "user", "content": mensagem.texto})
        elif mensagem.papel == "sistema":
            convertidas.append({"role": "system", "content": mensagem.texto})
        elif mensagem.papel == "ferramenta":
            convertidas += [_resultado_para_openai(resultado) for resultado in mensagem.resultados]
        else:
            assistente: dict[str, Any] = {"role": "assistant", "content": mensagem.texto or None}
            if mensagem.chamadas:
                assistente["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {"name": c.nome, "arguments": json.dumps(c.argumentos, ensure_ascii=False)}}
                    for c in mensagem.chamadas
                ]
            convertidas.append(assistente)
    return convertidas


def _resultado_para_openai(resultado: ResultadoFerramenta) -> dict[str, Any]:
    """
    Uma mensagem "tool": os dados em JSON compacto, ou o erro.

    Conceito (POL-08): os resultados entram como DADOS da mensagem tool, nunca
    no system prompt, para um texto vindo de fora não ser tratado como instrução.
    """
    conteudo = json.dumps(resultado.dados, ensure_ascii=False, separators=(",", ":")) if resultado.sucesso else f"ERRO: {resultado.erro}"
    return {"role": "tool", "tool_call_id": resultado.chamada_id, "content": conteudo}


def ferramentas_para_openai(especificacoes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Especificações internas ({"name", "description", "input_schema"}) no formato de function tools.

    Sem o modo estrito: ele exige todo campo como obrigatório, e os argumentos
    já são validados pelo Pydantic no registro (POL-06).

    Example:
        >>> ferramentas_para_openai([{"name": "x", "description": "d", "input_schema": {"type": "object"}}])
        [{'type': 'function', 'function': {'name': 'x', 'description': 'd', 'parameters': {'type': 'object'}}}]
    """
    return [
        {"type": "function", "function": {"name": e["name"], "description": e["description"], "parameters": e["input_schema"]}}
        for e in especificacoes
    ]


def resposta_da_openai(resposta: Any) -> RespostaLLM:
    """
    Converte a resposta do Chat Completions em RespostaLLM.

    Example:
        >>> from types import SimpleNamespace as N
        >>> chamada = N(id="call_1", type="function", function=N(name="panorama_dados", arguments="{}"))
        >>> mensagem = N(content=None, tool_calls=[chamada], refusal=None)
        >>> convertida = resposta_da_openai(N(choices=[N(message=mensagem, finish_reason="tool_calls")], usage=N(prompt_tokens=900, completion_tokens=40)))
        >>> convertida.chamadas[0].nome, convertida.motivo_parada, convertida.tokens_entrada
        ('panorama_dados', 'ferramentas', 900)
    """
    escolha = resposta.choices[0]
    mensagem = escolha.message
    chamadas = [
        ChamadaFerramenta(chamada.id, chamada.function.name, _argumentos(chamada.function.arguments))
        for chamada in (mensagem.tool_calls or [])
        if chamada.type == "function"
    ]
    motivo = "recusa" if getattr(mensagem, "refusal", None) else _MOTIVOS.get(escolha.finish_reason, "fim")
    uso = resposta.usage
    return RespostaLLM(
        texto=mensagem.content or "",
        chamadas=chamadas,
        tokens_entrada=uso.prompt_tokens if uso else 0,
        tokens_saida=uso.completion_tokens if uso else 0,
        motivo_parada=motivo,
    )


def _argumentos(texto: str | None) -> dict[str, Any]:
    """
    Os argumentos em dict. JSON quebrado vira um argumento que a validação recusa (POL-06).

    Example:
        >>> _argumentos('{"top_k": 3}'), _argumentos('{"top_k": 3'), _argumentos(None)
        ({'top_k': 3}, {'json_invalido': '{"top_k": 3'}, {})
    """
    if not texto:
        return {}
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError:
        return {"json_invalido": texto[:200]}
    return valor if isinstance(valor, dict) else {"json_invalido": texto[:200]}
