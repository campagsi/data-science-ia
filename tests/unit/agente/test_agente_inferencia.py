"""
Ferramentas de inferência com dados de resultado conhecido (conftest: temperatura com
ciclo diário, pH que se repete igual nos 3 dias, chuva sempre 0).

- duas amostras iguais → não significativo, efeito desprezível;
- amostras deslocadas (dia × noite) → significativo, efeito grande;
- correlação perfeita → r = 1; valores constantes → indefinida;
- probabilidades conferidas por contagem independente.
"""
import pytest
from scipy import stats

from src.agente.contratos import ChamadaFerramenta
from src.agente.ferramentas.calculos_inferencia import comparar_amostras, interpretar_efeito
from src.agente.ferramentas.base import ErroDeRegra

from dados_falsos_agente import INICIO, LEITURAS_POR_ESTACAO, valor_ph, valor_temperatura
from datetime import timedelta


def executar(registro, nome: str, **argumentos):
    """Executa a ferramenta pelo registro."""
    return registro.executar(ChamadaFerramenta("c1", nome, argumentos))


def instantes():
    """Os horários das leituras falsas (a cada 30 min, 3 dias)."""
    return [INICIO + timedelta(minutes=30 * i) for i in range(LEITURAS_POR_ESTACAO)]


# --- comparar_periodos ---------------------------------------------------------------


def test_dia_e_noite_da_temperatura_sao_diferentes_com_efeito_grande(registro):
    resultado = executar(registro, "comparar_periodos", parametro="TIP-TMP",
                         inicio_a="2026-06-01", fim_a="2026-06-03", turno_a="dia",
                         inicio_b="2026-06-01", fim_b="2026-06-03", turno_b="noite")

    dados = resultado.dados
    assert resultado.sucesso
    assert (dados["a"]["n"], dados["b"]["n"]) == (72, 72)
    assert dados["significativo"] and dados["p_valor"] == "<0.001"
    assert (dados["efeito_interpretacao"], dados["sentido"], dados["unidade"]) == ("grande", "A maior que B", "°C")


def test_p_valor_e_efeito_conferem_com_o_scipy(registro):
    dia = [valor_temperatura(i) for i in instantes() if 6 <= i.hour < 18]
    noite = [valor_temperatura(i) for i in instantes() if not 6 <= i.hour < 18]
    esperado = stats.mannwhitneyu(dia, noite, alternative="two-sided")

    dados = executar(registro, "comparar_periodos", parametro="TIP-TMP",
                     inicio_a="2026-06-01", fim_a="2026-06-03", turno_a="dia",
                     inicio_b="2026-06-01", fim_b="2026-06-03", turno_b="noite").dados

    assert dados["efeito"] == round(2 * esperado.statistic / (72 * 72) - 1, 3)


def test_dias_com_o_mesmo_padrao_nao_sao_diferentes(registro):
    dados = executar(registro, "comparar_periodos", parametro="TIP-TMP",
                     inicio_a="2026-06-01", fim_a="2026-06-01", inicio_b="2026-06-03", fim_b="2026-06-03").dados

    assert not dados["significativo"]
    assert (dados["efeito"], dados["efeito_interpretacao"]) == (0.0, "desprezível")


@pytest.mark.parametrize(
    "argumentos, trecho",
    [
        ({"inicio_a": "2026-06-03", "fim_a": "2026-06-01", "inicio_b": "2026-06-01", "fim_b": "2026-06-02"}, "fim anterior ao início"),
        ({"inicio_a": "2026-06-01", "fim_a": "2026-06-02", "inicio_b": "2026-06-01", "fim_b": "2026-06-02"}, "são iguais"),
        ({"inicio_a": "2026-06-01", "fim_a": "2026-06-02", "inicio_b": "2026-06-03", "fim_b": "2026-06-03", "turno_a": "tarde"}, "turno_a"),
    ],
)
def test_comparacao_com_argumentos_invalidos(registro, argumentos, trecho):
    resultado = executar(registro, "comparar_periodos", parametro="TIP-TMP", **argumentos)

    assert not resultado.sucesso and trecho in resultado.erro


def test_periodo_sem_dados_traz_aviso_e_cobertura(registro):
    dados = executar(registro, "comparar_periodos", parametro="TIP-TMP",
                     inicio_a="2026-06-01", fim_a="2026-06-01", inicio_b="2025-01-01", fim_b="2025-01-31").dados

    assert (dados["aviso"], dados["n_b"]) == ("sem medições no recorte", 0)
    assert dados["cobertura"]


def test_amostra_pequena_e_recusada():
    with pytest.raises(ErroDeRegra, match="mínimo 5"):
        comparar_amostras([1, 2, 3], [4, 5, 6, 7, 8])


def test_faixas_do_tamanho_de_efeito():
    assert [interpretar_efeito(e) for e in (0.0, 0.29, 0.3, 0.5, -0.8)] == ["desprezível", "pequeno", "médio", "grande", "grande"]


# --- correlacao ----------------------------------------------------------------------


def test_correlacao_pareia_pela_leitura_e_confere_com_o_scipy(registro):
    temperatura = [valor_temperatura(i) for i in instantes()]
    ph = [valor_ph(i) for i in instantes()]
    esperado = stats.spearmanr(temperatura, ph)

    par = executar(registro, "correlacao", parametros=["TIP-TMP", "TIP-PH"]).dados["pares"][0]

    assert (par["a"], par["b"], par["n"]) == ("TIP-TMP", "TIP-PH", 144)
    assert par["r"] == round(esperado.statistic, 3)


def test_correlacao_com_valores_constantes_e_indefinida(registro):
    pares = executar(registro, "correlacao", parametros=["TIP-TMP", "TIP-CHU"], metodo="pearson").dados["pares"]

    assert (pares[0]["r"], pares[0]["interpretacao"]) == (None, "indefinida (valores constantes)")


def test_correlacao_de_tres_parametros_traz_os_tres_pares(registro):
    pares = executar(registro, "correlacao", parametros=["TIP-TMP", "TIP-PH", "TIP-CHU"]).dados["pares"]

    assert [(p["a"], p["b"]) for p in pares] == [("TIP-TMP", "TIP-PH"), ("TIP-TMP", "TIP-CHU"), ("TIP-PH", "TIP-CHU")]


@pytest.mark.parametrize("parametros, trecho", [(["TIP-TMP"], "parametros"), (["TIP-TMP", "TIP-TMP"], "repetidos"), (["TIP-TMP", "TIP-XYZ"], "inexistente")])
def test_correlacao_com_parametros_invalidos(registro, parametros, trecho):
    resultado = executar(registro, "correlacao", parametros=parametros)

    assert not resultado.sucesso and trecho in resultado.erro


# --- probabilidade_evento ------------------------------------------------------------


def test_probabilidade_simples_e_condicional_por_contagem_independente(registro):
    leituras = [(valor_ph(i), valor_temperatura(i)) for i in instantes()]
    casos = sum(1 for ph, _ in leituras if ph > 7.1)
    com_condicao = [(ph, t) for ph, t in leituras if t >= 25]
    casos_juntos = sum(1 for ph, _ in com_condicao if ph > 7.1)

    dados = executar(registro, "probabilidade_evento", evento_parametro="TIP-PH", evento_operador=">", evento_valor=7.1,
                     condicao_parametro="TIP-TMP", condicao_operador=">=", condicao_valor=25).dados

    assert (dados["casos_evento"], dados["n_evento"]) == (casos, 144)
    assert dados["p_evento"] == round(casos / 144, 3)
    assert (dados["n_condicao"], dados["casos_evento_e_condicao"]) == (len(com_condicao), casos_juntos)
    assert dados["p_evento_dado_condicao"] == round(casos_juntos / len(com_condicao), 3)
    assert dados["unidades"] == {"TIP-PH": "pH", "TIP-TMP": "°C"}


def test_condicao_incompleta_e_recusada(registro):
    resultado = executar(registro, "probabilidade_evento", evento_parametro="TIP-PH", evento_operador=">", evento_valor=7, condicao_parametro="TIP-TMP")

    assert not resultado.sucesso and "condição precisa" in resultado.erro
