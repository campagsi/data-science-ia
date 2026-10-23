"""
Adaptador da OpenAI (DA11) com um SDK falso: tradução das mensagens e das
ferramentas, conversão da resposta e erros do provedor, sem rede e sem chave.
"""
import json
from types import SimpleNamespace as N

import httpx2
import openai
import pytest

from src.agente.contratos import ChamadaFerramenta, Mensagem, ResultadoFerramenta
from src.agente.fabrica import criar_agente, llm_da_config
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.llm.base import ErroProvedorLLM, LLMClient
from src.agente.llm.cliente_openai import ClienteOpenAI, mensagens_para_openai, resposta_da_openai
from src.config import ConfigAgente


class SDKFalso:
    """Imita openai.OpenAI: guarda os parâmetros e devolve as respostas em ordem (ou lança um erro)."""

    def __init__(self, respostas=(), erro=None):
        """Respostas prontas do Chat Completions."""
        self.pedidos = []
        self.__respostas = list(respostas)
        self.__erro = erro
        self.chat = N(completions=N(create=self.__criar))

    def __criar(self, **parametros):
        """Anota o pedido e devolve a próxima resposta."""
        self.pedidos.append(parametros)
        if self.__erro:
            raise self.__erro
        return self.__respostas.pop(0)


def resposta(texto=None, chamadas=(), motivo="stop", refusal=None, entrada=100, saida=20):
    """Uma resposta do Chat Completions."""
    tool_calls = [N(id=i, type="function", function=N(name=nome, arguments=argumentos)) for i, nome, argumentos in chamadas] or None
    return N(choices=[N(message=N(content=texto, tool_calls=tool_calls, refusal=refusal), finish_reason=motivo)], usage=N(prompt_tokens=entrada, completion_tokens=saida))


def test_e_um_llm_client():
    assert isinstance(ClienteOpenAI("k", "gpt-4.1-mini", cliente=SDKFalso()), LLMClient)


def test_historico_completo_vira_mensagens_do_chat_completions():
    chamada = ChamadaFerramenta("call_1", "resumo_estatistico", {"parametros": ["TIP-PH"]})
    historico = [
        Mensagem.usuario("pH médio?"),
        Mensagem.assistente("Vou consultar.", chamadas=[chamada]),
        Mensagem.ferramenta([ResultadoFerramenta.ok("call_1", {"media": 7.3}), ResultadoFerramenta.falha("call_2", "estação inexistente")]),
        Mensagem.sistema("Os números 7,2 não aparecem nos resultados."),
    ]

    convertidas = mensagens_para_openai("REGRAS", historico)

    assert [m["role"] for m in convertidas] == ["system", "user", "assistant", "tool", "tool", "system"]
    assert convertidas[2]["content"] == "Vou consultar." and json.loads(convertidas[2]["tool_calls"][0]["function"]["arguments"]) == {"parametros": ["TIP-PH"]}
    assert convertidas[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"media":7.3}'}
    assert convertidas[4]["content"] == "ERRO: estação inexistente"


def test_pedido_leva_ferramentas_e_a_resposta_forcada_as_proibe():
    sdk = SDKFalso([resposta("ok"), resposta("ok")])
    llm = ClienteOpenAI("k", "gpt-4.1-mini", max_tokens=8000, cliente=sdk)
    especificacao = {"name": "panorama_dados", "description": "Período coberto.", "input_schema": {"type": "object", "properties": {}}}

    llm.gerar("REGRAS", [Mensagem.usuario("oi")], [especificacao])
    llm.gerar("REGRAS", [Mensagem.usuario("oi")], [especificacao], permitir_ferramentas=False)

    livre, forcada = sdk.pedidos
    assert livre["tools"][0] == {"type": "function", "function": {"name": "panorama_dados", "description": "Período coberto.", "parameters": {"type": "object", "properties": {}}}}
    assert (livre["tool_choice"], forcada["tool_choice"], livre["max_completion_tokens"]) == ("auto", "none", 8000)
    assert "temperature" not in livre and "reasoning_effort" not in livre  # gpt-4.1-mini não é modelo de raciocínio


def test_modelo_de_raciocinio_recebe_o_esforco():
    sdk = SDKFalso([resposta("ok")])

    ClienteOpenAI("k", "gpt-5-mini", esforco="low", cliente=sdk).gerar("s", [Mensagem.usuario("oi")], [])

    assert sdk.pedidos[0]["reasoning_effort"] == "low"


def test_resposta_com_ferramentas_argumentos_invalidos_e_recusa():
    com_ferramentas = resposta_da_openai(resposta(chamadas=[("call_1", "listar_anomalias", '{"limite": 5}'), ("call_2", "panorama_dados", '{"quebrado')], motivo="tool_calls"))
    recusa = resposta_da_openai(resposta(refusal="Não posso ajudar com isso."))
    cortada = resposta_da_openai(resposta("texto pela metade", motivo="length"))

    assert [c.argumentos for c in com_ferramentas.chamadas] == [{"limite": 5}, {"json_invalido": '{"quebrado'}]
    assert com_ferramentas.motivo_parada == "ferramentas" and recusa.motivo_parada == "recusa" and cortada.motivo_parada == "limite_tokens"


@pytest.mark.parametrize("classe", [openai.APITimeoutError, openai.APIConnectionError])
def test_erro_do_sdk_vira_erro_do_provedor_so_com_o_tipo(classe):
    erro = classe(request=httpx2.Request("POST", "https://api.openai.com/v1/chat/completions?chave=sk-proj-segredo"))
    llm = ClienteOpenAI("k", "gpt-4.1-mini", cliente=SDKFalso(erro=erro))

    with pytest.raises(ErroProvedorLLM) as capturado:
        llm.gerar("s", [Mensagem.usuario("oi")], [])

    assert str(capturado.value) == classe.__name__ and capturado.value.__cause__ is None
    assert "sk-proj-segredo" not in str(capturado.value)


def test_fabrica_escolhe_o_adaptador_pelo_fornecedor():
    assert type(llm_da_config(ConfigAgente("openai", "gpt-4.1-mini", openai_api_key="sk-x"))).__name__ == "ClienteOpenAI"
    assert type(llm_da_config(ConfigAgente("anthropic", "claude-haiku-5-5", anthropic_api_key="sk-ant-x"))).__name__ == "ClienteAnthropic"
    with pytest.raises(ValueError, match="simulado"):
        llm_da_config(ConfigAgente("simulado"))


def test_laco_do_agente_completo_com_o_adaptador_da_openai():
    """O orquestrador não muda: ferramenta pedida → executada → resultado volta como mensagem tool → resposta."""
    sdk = SDKFalso([
        resposta(chamadas=[("call_1", "resumo_estatistico", '{"parametros": ["TIP-PH"]}')], motivo="tool_calls"),
        resposta("O pH médio foi 7,3 em 4 medições."),
    ])
    agente = criar_agente(ConfigAgente("simulado"), ClienteOpenAI("k", "gpt-4.1-mini", cliente=sdk), consulta_de_exemplo())

    resposta_final = agente.perguntar("Qual o pH médio?")

    assert resposta_final.texto == "O pH médio foi 7,3 em 4 medições." and resposta_final.tokens_entrada == 200
    mensagens = sdk.pedidos[1]["messages"]
    assert mensagens[-2]["tool_calls"][0]["id"] == "call_1" and mensagens[-1]["role"] == "tool" and mensagens[-1]["tool_call_id"] == "call_1"
