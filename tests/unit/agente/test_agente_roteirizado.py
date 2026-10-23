import pytest

from src.agente.contratos import ChamadaFerramenta, Mensagem, ResultadoFerramenta
from src.agente.llm import ErroProvedorLLM, LLMClient, LLMRoteirizado, RespostaLLM, RoteiroEsgotado

PEDIDO = RespostaLLM(
    chamadas=[ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})],
    tokens_entrada=1200,
    tokens_saida=40,
)
FINAL = RespostaLLM(texto="O pH médio em junho foi 7,30.", tokens_entrada=1500, tokens_saida=20)


def test_roteirizado_cumpre_a_interface():
    assert isinstance(LLMRoteirizado([]), LLMClient)


def test_devolve_as_respostas_na_ordem():
    llm = LLMRoteirizado([PEDIDO, FINAL])

    assert llm.gerar("s", [Mensagem.usuario("pH?")], []) is PEDIDO
    assert llm.gerar("s", [Mensagem.usuario("pH?")], []) is FINAL
    assert llm.restantes == 0


def test_registra_o_que_recebeu_como_foto_da_lista():
    llm = LLMRoteirizado([PEDIDO, FINAL])
    mensagens = [Mensagem.usuario("pH médio em junho?")]
    especificacoes = [{"name": "resumo_estatistico"}]

    llm.gerar("system prompt", mensagens, especificacoes)
    mensagens.append(Mensagem.assistente(chamadas=PEDIDO.chamadas))
    mensagens.append(Mensagem.ferramenta([ResultadoFerramenta.ok("c1", {"media": 7.3})]))
    llm.gerar("system prompt", mensagens, [])

    primeira, segunda = llm.chamadas_recebidas
    assert primeira.system == "system prompt"
    assert len(primeira.mensagens) == 1  # não vê o que foi anexado depois
    assert primeira.ferramentas == ({"name": "resumo_estatistico"},)
    assert segunda.mensagens[-1].resultados[0].sucesso
    assert segunda.ferramentas == ()


def test_roteiro_esgotado_falha_com_mensagem_clara():
    llm = LLMRoteirizado([FINAL])
    llm.gerar("s", [], [])

    with pytest.raises(RoteiroEsgotado, match="chamado 2 vezes, mas o roteiro tinha 1"):
        llm.gerar("s", [], [])


def test_excecao_no_roteiro_simula_falha_do_provedor():
    llm = LLMRoteirizado([ErroProvedorLLM("tempo limite"), FINAL])

    with pytest.raises(ErroProvedorLLM, match="tempo limite"):
        llm.gerar("s", [], [])
    assert llm.gerar("s", [], []) is FINAL
    assert len(llm.chamadas_recebidas) == 2


def test_resposta_llm_indica_se_pediu_ferramentas():
    assert PEDIDO.pediu_ferramentas
    assert not FINAL.pediu_ferramentas
    assert isinstance(PEDIDO.chamadas, tuple)


def test_resposta_llm_recusa_tokens_negativos():
    with pytest.raises(ValueError):
        RespostaLLM(tokens_saida=-1)
