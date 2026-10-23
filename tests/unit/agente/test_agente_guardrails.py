"""
Guardrails isolados, sem LLM: entrada (POL-05/POL-02), orçamento (POL-07),
saída (POL-03), catálogo de políticas e log (POL-13), máscara de texto livre
(src/security.py) e system prompt.
"""
import logging
from datetime import date, datetime

import pytest

from src.agente.contratos import ResultadoFerramenta
from src.agente.guardrails.entrada import TAMANHO_MAXIMO_PERGUNTA, PerguntaInvalida, preparar_pergunta
from src.agente.guardrails.orcamento import OrcamentoPergunta
from src.agente.guardrails.politicas import POLITICAS, registrar_acionamento
from src.agente.guardrails.saida import acrescentar_aviso, extrair_numeros, numeros_sem_origem
from src.agente.prompts import formatar_cobertura, montar_system_prompt
from src.logger import ETAPAS, registrar_chamada_ferramenta, registrar_falha_llm
from src.security import contem_dado_pessoal, cpf_valido, mascarar_texto_livre

# --- Máscara de texto livre (POL-02) ------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("CPF 529.982.247-25", "CPF [CPF]"),
        ("CPF 52998224725", "CPF [CPF]"),
        ("email Ana.Silva+obs@empresa.com.br", "email [EMAIL]"),
        ("tel (21) 98765-4321", "tel [TELEFONE]"),
        ("tel +55 21 3456-7890", "tel [TELEFONE]"),
        ("tel 21987654321", "tel [TELEFONE]"),
        # Pontuação de fim de frase logo depois do dado (bug achado pelo exemplo e06).
        ("Meu CPF é 529.982.247-25. Qual o pH?", "Meu CPF é [CPF]. Qual o pH?"),
        ("Ligue (21) 98765-4321, por favor.", "Ligue [TELEFONE], por favor."),
        ("CPF: 529.982.247-25;", "CPF: [CPF];"),
    ],
)
def test_mascara_troca_dados_pessoais(texto, esperado):
    assert mascarar_texto_livre(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "pH médio 7,38 em 1.402 medições",
        "9.806 leituras de 01/04/2026 a 23/10/2026",
        "registro REG-RJ-001-03106 às 06:00",
        "turbidez 104582 itens e 2026-10-23T23:30:00",
        "número 123.456.789-00 com dígitos que não fecham",
        "código longo 1.529.982.247-25.3 não é CPF",
    ],
)
def test_mascara_preserva_medicoes_datas_e_codigos(texto):
    assert mascarar_texto_livre(texto) == texto


def test_cpf_valido_confere_os_digitos():
    assert cpf_valido("529.982.247-25")
    assert not cpf_valido("529.982.247-24")
    assert not cpf_valido("000.000.000-00")
    assert contem_dado_pessoal("meu e-mail é a@b.com")


# --- Entrada (POL-05) ----------------------------------------------------------------


def test_pergunta_e_limpa_e_mascarada():
    preparada = preparar_pergunta("\tQual o pH?​ CPF 529.982.247-25\n")

    assert preparada.texto == "Qual o pH?  CPF [CPF]"
    assert preparada.mascarada


def test_pergunta_no_limite_de_tamanho_passa_e_acima_nao():
    assert len(preparar_pergunta("x" * TAMANHO_MAXIMO_PERGUNTA).texto) == TAMANHO_MAXIMO_PERGUNTA
    with pytest.raises(PerguntaInvalida, match="1001 caracteres"):
        preparar_pergunta("x" * (TAMANHO_MAXIMO_PERGUNTA + 1))


# --- Orçamento (POL-07) --------------------------------------------------------------


def test_orcamento_por_chamadas_tokens_e_prazo():
    agora = [0.0]
    orcamento = OrcamentoPergunta(max_chamadas=3, max_tokens_entrada=5000, prazo_segundos=60, relogio=lambda: agora[0])

    orcamento.registrar_chamadas(2)
    assert (orcamento.permite_ferramentas(), orcamento.restantes()) == (True, 1)
    orcamento.registrar_chamadas(1)
    assert orcamento.motivo_esgotado() == "chamadas"
    assert orcamento.permite_correcao()  # a correção não usa ferramenta

    orcamento.registrar_tokens(5000, 10)
    assert orcamento.motivo_esgotado() == "tokens"
    assert not orcamento.permite_correcao()


def test_prazo_esgota_o_orcamento():
    agora = [0.0]
    orcamento = OrcamentoPergunta(6, 60000, prazo_segundos=180, relogio=lambda: agora[0])
    agora[0] = 180.0

    assert orcamento.motivo_esgotado() == "prazo"
    assert orcamento.milissegundos() == 180000


# --- Saída (POL-03) ------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("A máxima foi 32 °C e a mínima 20 °C.", ["32", "20"]),  # grau é medição
        ("O 1º pico, o 2ª leitura.", []),  # ordinais
        ("1. primeiro item\n2. segundo item", []),  # numeração de lista
        ("Nos últimos 7 dias e nas 24 horas seguintes", []),  # durações
        ("Às 12h e às 06:00 de 03/06/2026 (2026-06-03)", []),  # horas e datas
        ("Estação EST-RJ-001, parâmetro TIP-PH, registro REG-RJ-001-03106", []),  # códigos
        ("Em 2026 houve -3,5 °C.", ["-3,5"]),  # ano solto ignorado; negativo fica
    ],
)
def test_extrair_numeros(texto, esperado):
    assert extrair_numeros(texto) == esperado


def test_numeros_conferem_com_arredondamento_e_separador_de_milhar():
    resultado = ResultadoFerramenta.ok("c1", {"linhas": [{"media": 7.381, "quantidade": 1402, "zscore": 10.432}]})

    assert numeros_sem_origem("Média 7,38 (7,4 arredondado; cerca de 7), 1.402 medições, Z 10,43.", [resultado]) == []
    assert numeros_sem_origem("Média 7,39.", [resultado]) == ["7,39"]


def test_porcentagem_confere_com_a_fracao_da_ferramenta():
    """Falso positivo medido na Fase 8: probabilidade_evento devolve 0.125 e o LLM escreve 12,5%."""
    probabilidade = ResultadoFerramenta.ok("c1", {"p_evento": 0.0385, "alfa": 0.05, "media_umidade": 82.41})

    assert numeros_sem_origem("Em 3,85% das leituras (α = 5 %); umidade média de 82,4%.", [probabilidade]) == []
    assert numeros_sem_origem("Subiu 12,5% em relação a maio.", [probabilidade]) == ["12,5"]
    assert numeros_sem_origem("Foram 12,5 leituras.", [ResultadoFerramenta.ok("c1", {"p_evento": 0.125})]) == ["12,5"]  # sem % não vale a escala


def test_resultado_com_erro_nao_vale_como_origem():
    falha = ResultadoFerramenta.falha("c1", "estação inexistente: EST-9")

    assert numeros_sem_origem("Foram 9 medições.", [falha]) == ["9"]


def test_aviso_lista_os_numeros():
    assert acrescentar_aviso("Texto.", ["7,2", "15", "3"]).endswith("ferramentas: 7,2, 15 e 3.")


# --- Políticas e log (POL-13, POL-10) -----------------------------------------------


def test_catalogo_tem_as_13_politicas():
    assert list(POLITICAS) == [f"POL-{n:02d}" for n in range(1, 14)]


def test_acionamento_vai_para_o_log_com_o_id(caplog):
    with caplog.at_level(logging.WARNING):
        registrar_acionamento("POL-03", "c-1", acao="correcao", numeros=2)

    assert "Agente: guardrail=POL-03 conversa=c-1 acao=correcao numeros=2" in caplog.text


def test_politica_desconhecida_e_erro():
    with pytest.raises(ValueError, match="POL-99"):
        registrar_acionamento("POL-99", "c-1")


def test_logs_do_agente(caplog):
    with caplog.at_level(logging.INFO):
        registrar_chamada_ferramenta("c-1", "resumo_estatistico", '{"parametros": ["TIP-PH"]}', True, 12)
        registrar_chamada_ferramenta("c-1", "resumo_estatistico", "{}", False, 3, "estação inexistente")
        registrar_falha_llm("c-1", "AuthenticationError")

    assert 'ferramenta=resumo_estatistico conversa=c-1 args={"parametros": ["TIP-PH"]} sucesso=sim ms=12' in caplog.text
    assert 'sucesso=nao ms=3 erro="estação inexistente"' in caplog.text
    assert "erro=AuthenticationError" in caplog.text
    assert "agente" in ETAPAS


# --- System prompt -------------------------------------------------------------------


def test_cobertura_de_varias_estacoes():
    linhas = [
        {"estacao_codigo": f"EST-{i}", "primeira_leitura": datetime(2026, 4, 1), "ultima_leitura": datetime(2026, 10, 23), "leituras": 9806}
        for i in (1, 2)
    ]

    assert formatar_cobertura(linhas).startswith("2 estações: EST-1 com 9.806 leituras de 01/04/2026 a 23/10/2026; EST-2")


def test_regras_de_documentacao_mudam_com_a_ferramenta():
    com = montar_system_prompt(date(2026, 10, 21), [], ["buscar_documentacao"])
    sem = montar_system_prompt(date(2026, 10, 21), [], ["resumo_estatistico"])

    assert "use buscar_documentacao" in com and "use buscar_documentacao" not in sem
    assert "[CPF]" in com  # regra 7: marcadores de dados já removidos
