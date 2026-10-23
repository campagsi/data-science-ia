"""CLI do agente (rich) e montagem pela fábrica, com o LLM roteirizado e os dados de exemplo em memória."""
from rich.console import Console

import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.fabrica import criar_agente
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.llm.base import RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.cli.agente_cli import conversar, responder_uma
from src.config import ConfigAgente


def agente_de_exemplo(roteiro, **cfg):
    """Agente montado pela fábrica, sem chave e sem banco."""
    llm = LLMRoteirizado(roteiro)
    return criar_agente(ConfigAgente("simulado", **cfg), llm, consulta_de_exemplo()), llm


def console_gravando() -> Console:
    """Console que guarda o que foi impresso."""
    return Console(record=True, width=120)


def test_responder_uma_mostra_resposta_fontes_e_tokens():
    agente, _ = agente_de_exemplo([
        RespostaLLM(chamadas=[ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})], motivo_parada="ferramentas", tokens_entrada=900),
        RespostaLLM(texto="O pH médio foi **7,3** (4 medições).", tokens_entrada=1100, tokens_saida=30),
    ])
    console = console_gravando()

    responder_uma(agente, "Qual o pH médio?", console)

    saida = console.export_text()
    assert "O pH médio foi 7,3 (4 medições)." in saida
    assert 'resumo_estatistico(parametros=["TIP-PH"])' in saida
    assert "tokens: 2000 de entrada, 30 de saída" in saida


def test_responder_uma_mostra_erro_de_pergunta_invalida():
    agente, llm = agente_de_exemplo([])
    console = console_gravando()

    assert responder_uma(agente, "   ", console) is None
    assert "Pergunta inválida: a pergunta está vazia" in console.export_text()
    assert llm.chamadas_recebidas == []


def test_chat_mantem_a_conversa_e_encerra_com_sair():
    agente, llm = agente_de_exemplo([RespostaLLM(texto="Pergunte sobre o pH."), RespostaLLM(texto="Claro.")])
    entradas = iter(["Olá", "", "E em julho?", "sair"])

    respondidas = conversar(agente, console_gravando(), ler=lambda _: next(entradas))

    assert respondidas == 2
    assert [m.texto for m in llm.chamadas_recebidas[1].mensagens] == ["Olá", "Pergunte sobre o pH.", "E em julho?"]


def test_chat_encerra_com_fim_da_entrada():
    agente, _ = agente_de_exemplo([])

    def fim(_):
        """Simula Ctrl+D."""
        raise EOFError

    assert conversar(agente, console_gravando(), ler=fim) == 0


def test_fabrica_aplica_os_limites_da_configuracao():
    agente, llm = agente_de_exemplo(
        [RespostaLLM(chamadas=[ChamadaFerramenta("c1", "listar_parametros", {})], motivo_parada="ferramentas"), RespostaLLM(texto="Ok.")],
        max_ferramentas=1,
    )

    agente.perguntar("Parâmetros?")

    assert [e.permitir_ferramentas for e in llm.chamadas_recebidas] == [True, False]


def test_fabrica_exige_llm_no_modo_simulado():
    with pytest.raises(ValueError, match="simulado é só para testes"):
        criar_agente(ConfigAgente("simulado"), consulta=consulta_de_exemplo())


def test_fabrica_exige_a_conexao_do_agente_sem_consulta_pronta():
    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        criar_agente(ConfigAgente("simulado"), llm=LLMRoteirizado([]))
