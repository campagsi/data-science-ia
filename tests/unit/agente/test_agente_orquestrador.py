"""
O laço do agente com o LLM roteirizado (sem rede, sem chave, sem banco).

Cobre os casos de docs/agente/avaliacao.md § 2 e um teste por política da Fase 3:
POL-02 (máscara), POL-03 (números), POL-04 (fontes), POL-05 (entrada),
POL-07 (orçamento), POL-10 (log sem segredo), POL-11 (recusa) e POL-13 (log).
"""
import logging
from datetime import date

import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.conversa import Conversas
from src.agente.guardrails.entrada import PerguntaInvalida
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.agente.orquestrador import (
    AVISO_CORTADA,
    ERRO_LIMITE_CHAMADAS,
    MENSAGEM_FALHA_PROVEDOR,
    MENSAGEM_RECUSA,
    Agente,
)


def chamar(nome: str, id_: str = "c1", **argumentos) -> RespostaLLM:
    """Resposta do LLM pedindo uma ferramenta."""
    return RespostaLLM(chamadas=[ChamadaFerramenta(id_, nome, argumentos)], motivo_parada="ferramentas", tokens_entrada=1000, tokens_saida=50)


def responder(texto: str, **extras) -> RespostaLLM:
    """Resposta final do LLM."""
    return RespostaLLM(texto=texto, tokens_entrada=1200, tokens_saida=80, **extras)


class Relogio:
    """Relógio controlado pelo teste."""

    def __init__(self) -> None:
        """Começa no instante zero."""
        self.agora = 0.0

    def __call__(self) -> float:
        """Instante atual em segundos."""
        return self.agora


def montar(registro, consulta, roteiro, **limites) -> tuple[Agente, LLMRoteirizado]:
    """Agente com o LLM roteirizado e os dados falsos do conftest."""
    llm = LLMRoteirizado(roteiro)
    agente = Agente(llm, registro, Conversas(), consulta.cobertura, hoje=lambda: date(2026, 10, 21), **limites)
    return agente, llm


# --- Laço -----------------------------------------------------------------------


def test_resposta_direta_sem_ferramenta(registro, consulta):
    agente, llm = montar(registro, consulta, [responder("Posso responder sobre as medições das estações.")])

    resposta = agente.perguntar("O que você faz?")

    assert resposta.texto == "Posso responder sobre as medições das estações."
    assert (resposta.fontes, len(llm.chamadas_recebidas)) == ((), 1)
    assert llm.chamadas_recebidas[0].permitir_ferramentas


def test_uma_ferramenta_resultado_volta_ao_llm_e_vira_fonte(registro, consulta):
    agente, llm = montar(registro, consulta, [
        chamar("resumo_estatistico", parametros=["TIP-TMP"]),
        responder("A temperatura máxima foi 32 °C."),
    ])

    resposta = agente.perguntar("Qual a temperatura máxima?")

    ultima = llm.chamadas_recebidas[1].mensagens[-1]
    assert ultima.papel == "ferramenta" and ultima.resultados[0].sucesso
    assert ultima.resultados[0].dados["linhas"][0]["maximo"] == 32.0
    assert [f.descricao for f in resposta.fontes] == ['resumo_estatistico(parametros=["TIP-TMP"])']
    assert (resposta.tokens_entrada, resposta.tokens_saida) == (2200, 130)


def test_varias_ferramentas_em_sequencia(registro, consulta):
    agente, _ = montar(registro, consulta, [
        chamar("listar_parametros"),
        chamar("perfil_horario", "c2", parametro="TIP-TMP"),
        responder("O pico é às 12h, com média de 32 °C."),
    ])

    resposta = agente.perguntar("Em que hora a temperatura é maior?")

    assert [f.descricao.split("(")[0] for f in resposta.fontes] == ["listar_parametros", "perfil_horario"]


def test_conversa_so_cresce_para_frente_e_system_e_ferramentas_nao_mudam(registro, consulta):
    """No Haiku 5.5, editar o que já foi enviado invalida os blocos de raciocínio: cada chamada estende a anterior."""
    agente, llm = montar(registro, consulta, [chamar("listar_parametros"), chamar("panorama_dados", "c2"), responder("Há 3 parâmetros.")])

    agente.perguntar("Quais parâmetros existem?")

    primeira, segunda, terceira = llm.chamadas_recebidas
    assert segunda.mensagens[: len(primeira.mensagens)] == primeira.mensagens
    assert terceira.mensagens[: len(segunda.mensagens)] == segunda.mensagens
    assert primeira.system == segunda.system == terceira.system
    assert primeira.ferramentas == segunda.ferramentas == terceira.ferramentas


def test_blocos_do_fornecedor_voltam_intactos(registro, consulta):
    pedido = RespostaLLM(chamadas=[ChamadaFerramenta("c1", "listar_parametros", {})], motivo_parada="ferramentas", bruto=("bloco-thinking", "bloco-tool_use"))
    agente, llm = montar(registro, consulta, [pedido, responder("Há 3 parâmetros.")])

    agente.perguntar("Quais parâmetros existem?")

    assert llm.chamadas_recebidas[1].mensagens[-2].bruto == ("bloco-thinking", "bloco-tool_use")


def test_erro_de_ferramenta_volta_ao_llm_e_nao_vira_fonte(registro, consulta):
    agente, llm = montar(registro, consulta, [chamar("resumo_estatistico", estacao="EST-9"), responder("A estação EST-9 não existe.")])

    resposta = agente.perguntar("pH da EST-9?")

    resultado = llm.chamadas_recebidas[1].mensagens[-1].resultados[0]
    assert not resultado.sucesso and "estação inexistente" in resultado.erro
    assert resposta.fontes == ()  # POL-04: só o que trouxe informação


def test_continuacao_da_conversa_leva_o_historico(registro, consulta):
    agente, llm = montar(registro, consulta, [responder("Pergunte sobre o pH."), responder("Claro.")])

    primeira = agente.perguntar("Olá")
    agente.perguntar("E em julho?", primeira.conversa_id)

    textos = [m.texto for m in llm.chamadas_recebidas[1].mensagens]
    assert textos == ["Olá", "Pergunte sobre o pH.", "E em julho?"]


# --- POL-07: orçamento ----------------------------------------------------------


def test_limite_de_chamadas_forca_a_resposta_sem_ferramentas(registro, consulta, caplog):
    agente, llm = montar(registro, consulta, [
        chamar("listar_parametros"),
        chamar("panorama_dados", "c2"),
        responder("Resposta com o que já tenho."),
    ], max_ferramentas=2)

    with caplog.at_level(logging.WARNING):
        resposta = agente.perguntar("Conte tudo.")

    assert [e.permitir_ferramentas for e in llm.chamadas_recebidas] == [True, True, False]
    assert resposta.texto == "Resposta com o que já tenho."
    assert "guardrail=POL-07" in caplog.text and "acao=resposta_forcada motivo=chamadas" in caplog.text


def test_chamadas_alem_do_limite_na_mesma_resposta_recebem_erro(registro, consulta):
    tres = RespostaLLM(chamadas=[ChamadaFerramenta(f"c{i}", "listar_parametros", {}) for i in range(3)], motivo_parada="ferramentas")
    agente, llm = montar(registro, consulta, [tres, responder("Ok.")], max_ferramentas=2)

    agente.perguntar("Parâmetros?")

    resultados = llm.chamadas_recebidas[1].mensagens[-1].resultados
    assert [r.sucesso for r in resultados] == [True, True, False]
    assert resultados[2].erro == ERRO_LIMITE_CHAMADAS


def test_orcamento_de_tokens(registro, consulta):
    caro = RespostaLLM(chamadas=[ChamadaFerramenta("c1", "listar_parametros", {})], motivo_parada="ferramentas", tokens_entrada=70000)
    agente, llm = montar(registro, consulta, [caro, responder("Ok.")], max_tokens_pergunta=60000)

    agente.perguntar("Parâmetros?")

    assert [e.permitir_ferramentas for e in llm.chamadas_recebidas] == [True, False]


def test_prazo_da_pergunta(registro, consulta):
    relogio = Relogio()

    class LLMLento(LLMRoteirizado):
        """Cada chamada leva 100 s."""

        def gerar(self, *argumentos, **nomeados):
            """Avança o relógio e responde pelo roteiro."""
            relogio.agora += 100
            return super().gerar(*argumentos, **nomeados)

    llm = LLMLento([chamar("listar_parametros"), chamar("panorama_dados", "c2"), responder("Ok.")])
    agente = Agente(llm, registro, Conversas(), consulta.cobertura, prazo_segundos=180, relogio=relogio)

    agente.perguntar("Parâmetros?")

    assert [e.permitir_ferramentas for e in llm.chamadas_recebidas] == [True, True, False]


def test_resposta_cortada_pelo_limite_de_tokens_recebe_aviso(registro, consulta):
    agente, _ = montar(registro, consulta, [responder("Resposta pela met", motivo_parada="limite_tokens")])

    assert agente.perguntar("Explique.").texto == "Resposta pela met" + AVISO_CORTADA


# --- POL-03: números ------------------------------------------------------------


def test_numero_sem_origem_pede_uma_correcao_e_nao_edita_o_que_foi_enviado(registro, consulta, caplog):
    agente, llm = montar(registro, consulta, [
        chamar("resumo_estatistico", parametros=["TIP-TMP"]),
        responder("A máxima foi 35 °C."),
        responder("A máxima foi 32 °C."),
    ])

    with caplog.at_level(logging.WARNING):
        resposta = agente.perguntar("Qual a temperatura máxima?")

    segunda, terceira = llm.chamadas_recebidas[1:]
    assert terceira.mensagens[:-1] == segunda.mensagens  # a resposta errada não entrou no histórico
    assert terceira.mensagens[-1].papel == "sistema" and "35" in terceira.mensagens[-1].texto
    assert resposta.texto == "A máxima foi 32 °C."
    assert "guardrail=POL-03" in caplog.text and "acao=correcao numeros=1" in caplog.text


def test_numero_que_continua_sem_origem_sai_com_aviso_apos_uma_unica_correcao(registro, consulta):
    agente, llm = montar(registro, consulta, [
        chamar("resumo_estatistico", parametros=["TIP-TMP"]),
        responder("A máxima foi 35 °C."),
        responder("A máxima foi 35 °C, confirmo."),
    ])

    resposta = agente.perguntar("Qual a temperatura máxima?")

    assert len(llm.chamadas_recebidas) == 3
    assert resposta.texto.endswith("Não foi possível conferir alguns números com os resultados das ferramentas: 35.")


def test_numeros_da_pergunta_e_do_contexto_valem_como_origem(registro, consulta):
    agente, llm = montar(registro, consulta, [responder("O código EST-1 tem 144 leituras, como você citou 2 vezes.")])

    resposta = agente.perguntar("A EST-1 tem 144 leituras? Já perguntei 2 vezes.")

    assert len(llm.chamadas_recebidas) == 1 and "⚠" not in resposta.texto


# --- POL-02, POL-05, POL-10, POL-11 ----------------------------------------------


def test_pergunta_com_cpf_chega_mascarada_ao_llm_ao_historico_e_ao_log(registro, consulta, caplog):
    agente, llm = montar(registro, consulta, [responder("Não tenho acesso a dados pessoais. Escreva para ana@ex.com.")])

    with caplog.at_level(logging.INFO):
        resposta = agente.perguntar("Meu CPF é 529.982.247-25, qual o pH?")

    assert llm.chamadas_recebidas[0].mensagens[-1].texto == "Meu CPF é [CPF], qual o pH?"
    assert "529.982.247-25" not in caplog.text and "[CPF]" in caplog.text
    assert resposta.texto == "Não tenho acesso a dados pessoais. Escreva para [EMAIL]."
    assert "acao=mascara_pergunta" in caplog.text and "acao=mascara_resposta" in caplog.text


@pytest.mark.parametrize("pergunta", ["", "   ", "x" * 1001])
def test_pergunta_vazia_ou_longa_e_recusada_antes_do_llm(registro, consulta, pergunta):
    agente, llm = montar(registro, consulta, [])

    with pytest.raises(PerguntaInvalida):
        agente.perguntar(pergunta)
    assert llm.chamadas_recebidas == []


def test_falha_do_provedor_vira_mensagem_amigavel_sem_detalhe_no_log(registro, consulta, caplog):
    agente, _ = montar(registro, consulta, [ErroProvedorLLM("APITimeoutError")])

    with caplog.at_level(logging.ERROR):
        resposta = agente.perguntar("pH?")

    assert (resposta.texto, resposta.falhou) == (MENSAGEM_FALHA_PROVEDOR, True)
    assert "falha no provedor de LLM" in caplog.text and "erro=APITimeoutError" in caplog.text


def test_falha_do_provedor_nao_entra_no_historico(registro, consulta):
    agente, llm = montar(registro, consulta, [ErroProvedorLLM("APIConnectionError"), responder("Ok.")])

    primeira = agente.perguntar("pH?")
    agente.perguntar("De novo: pH?", primeira.conversa_id)

    assert [m.texto for m in llm.chamadas_recebidas[1].mensagens] == ["De novo: pH?"]


def test_recusa_do_modelo_vira_mensagem_padrao(registro, consulta, caplog):
    agente, _ = montar(registro, consulta, [responder("", motivo_parada="recusa")])

    with caplog.at_level(logging.WARNING):
        resposta = agente.perguntar("Pergunta fora do escopo")

    assert resposta.texto == MENSAGEM_RECUSA
    assert "guardrail=POL-11" in caplog.text


def test_system_prompt_traz_data_cobertura_e_regras(registro, consulta):
    agente, llm = montar(registro, consulta, [responder("Ok.")])

    agente.perguntar("Que dados você tem?")

    system = llm.chamadas_recebidas[0].system
    assert "Data de hoje: 21/10/2026." in system
    assert "EST-1 com 144 leituras de 01/06/2026 a 03/06/2026" in system
    assert "Ainda não há ferramenta de documentação" in system  # Fase 4 ainda não existe
