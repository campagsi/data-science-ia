"""
Adaptador do Claude com um cliente do SDK falso (sem rede e sem chave).

Confere o pedido montado (modelo, limites, ferramentas estritas, tool_choice,
mensagens) e a conversão da resposta (texto, tool_use, tokens, motivo), além
da conversão dos erros do SDK (POL-10).
"""
from types import SimpleNamespace as N

import anthropic
import httpx2
import pytest

from src.agente.contratos import ChamadaFerramenta, Mensagem, ResultadoFerramenta
from src.agente.llm.base import ErroProvedorLLM, LLMClient
from src.agente.llm.cliente_anthropic import (
    MAXIMO_OPCIONAIS_ESTRITOS,
    ClienteAnthropic,
    ferramentas_para_api,
    mensagens_para_api,
    schema_estrito,
)


class SDKFalso:
    """Imita anthropic.Anthropic: guarda os parâmetros e devolve (ou lança) o que o teste mandar."""

    def __init__(self, resposta=None, erro=None) -> None:
        """Guarda a resposta ou o erro a devolver."""
        self.recebido = None
        self.__resposta = resposta
        self.__erro = erro
        self.messages = self

    def create(self, **parametros):
        """Messages API falsa."""
        self.recebido = parametros
        if self.__erro:
            raise self.__erro
        return self.__resposta


def resposta_texto(texto="Ok.", stop_reason="end_turn"):
    """Resposta da API só com texto."""
    return N(content=[N(type="text", text=texto)], stop_reason=stop_reason, usage=N(input_tokens=100, output_tokens=10))


def cliente(resposta=None, erro=None) -> tuple[ClienteAnthropic, SDKFalso]:
    """ClienteAnthropic com o SDK falso."""
    sdk = SDKFalso(resposta or resposta_texto(), erro)
    return ClienteAnthropic("sk-ant-teste", "claude-haiku-5-5", max_tokens=16000, esforco="low", cliente=sdk), sdk


def test_cumpre_a_interface():
    assert isinstance(cliente()[0], LLMClient)


def test_pedido_tem_modelo_limites_esforco_e_cache_sem_amostragem():
    llm, sdk = cliente()

    llm.gerar("system prompt", [Mensagem.usuario("pH?")], [])

    assert sdk.recebido["model"] == "claude-haiku-5-5"
    assert (sdk.recebido["max_tokens"], sdk.recebido["output_config"]) == (16000, {"effort": "low"})
    assert sdk.recebido["system"] == "system prompt"
    assert sdk.recebido["cache_control"] == {"type": "ephemeral"}
    assert not {"temperature", "top_p", "top_k", "tools", "tool_choice"} & set(sdk.recebido)


def test_resposta_forcada_mantem_as_ferramentas_e_proibe_o_uso(registro):
    llm, sdk = cliente()

    llm.gerar("s", [Mensagem.usuario("pH?")], registro.especificacoes(), permitir_ferramentas=False)

    assert sdk.recebido["tool_choice"] == {"type": "none"}
    assert [t["name"] for t in sdk.recebido["tools"]] == list(registro.nomes())


def test_catalogo_atual_vai_em_modo_estrito_sem_restricoes_sem_suporte(registro):
    ferramentas = ferramentas_para_api(registro.especificacoes())

    estritas = [f["name"] for f in ferramentas if f.get("strict")]
    # As 6 ferramentas descritivas cabem nos tetos; as de inferência, que vêm depois, não.
    assert estritas[:6] == ["panorama_dados", "listar_parametros", "resumo_estatistico", "listar_anomalias", "serie_temporal", "perfil_horario"]
    ferramentas = [f for f in ferramentas if f.get("strict")]
    texto = str([f["input_schema"] for f in ferramentas])
    for palavra in ("maximum", "minimum", "maxLength", "minLength", "maxItems", "pattern"):
        assert f"'{palavra}'" not in texto
    limite = next(f for f in ferramentas if f["name"] == "listar_anomalias")["input_schema"]["properties"]["limite"]
    assert "Restrições:" in limite["description"]
    assert "mínimo 1" in limite["description"] and "máximo 50" in limite["description"]


def test_so_a_ferramenta_que_passa_dos_tetos_fica_sem_strict(caplog):
    pequena = {"name": "pequena", "description": "d", "input_schema": {"type": "object", "properties": {"a": {"type": "string"}}}}
    muitos = {f"p{i}": {"type": "string"} for i in range(MAXIMO_OPCIONAIS_ESTRITOS)}
    grande = {"name": "grande", "description": "d", "input_schema": {"type": "object", "properties": muitos}}

    ferramentas = ferramentas_para_api([pequena, grande, pequena | {"name": "outra"}])

    assert [f.get("strict", False) for f in ferramentas] == [True, False, True]
    assert "modo estrito desligado em grande" in caplog.text


def test_schema_estrito_tambem_limpa_listas():
    schema = {"type": "object", "properties": {"codigos": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}}}

    assert schema_estrito(schema)["properties"]["codigos"] == {
        "type": "array", "items": {"type": "string"}, "minItems": 1, "description": "Restrições: no máximo 20 itens."
    }


def test_mensagens_convertidas_nos_quatro_papeis():
    chamada = ChamadaFerramenta("toolu_1", "resumo_estatistico", {"parametros": ["TIP-PH"]})
    mensagens = [
        Mensagem.usuario("pH?"),
        Mensagem.assistente("Vou consultar.", [chamada]),
        Mensagem.ferramenta([ResultadoFerramenta.falha("toolu_1", "estação inexistente")]),
        Mensagem.sistema("Verificação automática: ..."),
    ]

    usuario, assistente, ferramenta, sistema = mensagens_para_api(mensagens)

    assert usuario == {"role": "user", "content": "pH?"}
    assert assistente["content"] == [
        {"type": "text", "text": "Vou consultar."},
        {"type": "tool_use", "id": "toolu_1", "name": "resumo_estatistico", "input": {"parametros": ["TIP-PH"]}},
    ]
    assert ferramenta["content"][0] == {"type": "tool_result", "tool_use_id": "toolu_1", "content": "estação inexistente", "is_error": True}
    assert sistema == {"role": "system", "content": "Verificação automática: ..."}


def test_blocos_originais_voltam_intactos():
    bloco_thinking = N(type="thinking", thinking="", signature="assinatura")

    convertida = mensagens_para_api([Mensagem.assistente(chamadas=[ChamadaFerramenta("t1", "x")], bruto=[bloco_thinking])])

    assert convertida[0]["content"] == [bloco_thinking]


def test_resposta_com_thinking_e_tool_use_e_tokens_do_cache():
    api = N(
        stop_reason="tool_use",
        usage=N(input_tokens=500, output_tokens=60, cache_read_input_tokens=1500, cache_creation_input_tokens=200),
        content=[N(type="thinking", thinking="", signature="s"), N(type="text", text="Vou ver."),
                 N(type="tool_use", id="toolu_9", name="panorama_dados", input={})],
    )
    llm, _ = cliente(api)

    resposta = llm.gerar("s", [Mensagem.usuario("Que dados?")], [])

    assert (resposta.texto, resposta.motivo_parada) == ("Vou ver.", "ferramentas")
    assert resposta.chamadas == (ChamadaFerramenta("toolu_9", "panorama_dados", {}),)
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (2200, 60)
    assert len(resposta.bruto) == 3


@pytest.mark.parametrize("stop_reason, motivo", [("end_turn", "fim"), ("max_tokens", "limite_tokens"), ("refusal", "recusa"), ("pause_turn", "fim")])
def test_motivo_da_parada(stop_reason, motivo):
    llm, _ = cliente(resposta_texto(stop_reason=stop_reason))

    assert llm.gerar("s", [Mensagem.usuario("x")], []).motivo_parada == motivo


@pytest.mark.parametrize("classe", [anthropic.APITimeoutError, anthropic.APIConnectionError])
def test_erro_do_sdk_vira_erro_do_provedor_so_com_o_tipo(classe):
    erro = classe(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages?chave=sk-ant-segredo"))
    llm, _ = cliente(erro=erro)

    with pytest.raises(ErroProvedorLLM) as capturado:
        llm.gerar("s", [Mensagem.usuario("x")], [])

    assert str(capturado.value) == classe.__name__
    assert capturado.value.__cause__ is None and capturado.value.__suppress_context__  # POL-10
    assert "sk-ant-segredo" not in str(capturado.value)


def test_de_config_usa_os_limites_da_configuracao():
    from src.config import ConfigAgente

    cfg = ConfigAgente("anthropic", "claude-haiku-5-5", anthropic_api_key="sk-ant-x", max_tokens_saida=8000, esforco="high")

    llm = ClienteAnthropic.de_config(cfg)

    assert (llm.modelo, llm.max_tokens, llm.esforco) == ("claude-haiku-5-5", 8000, "high")
