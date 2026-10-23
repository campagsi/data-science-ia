"""
Dias semelhantes (Fase 9): resumos diários, índice separado, ferramenta e perfis numéricos.

Sem rede e sem banco: dados falsos (dados_falsos_agente.py) e embedder simulado.
Nos dados falsos, 01 e 03/06 são iguais, e 02/06 tem o pico de pH (9,9 às 06:00).
"""
import logging
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from dados_falsos_agente import montar_consulta
from src.agente.contratos import ChamadaFerramenta, ResultadoFerramenta
from src.agente.dias.indice import PASTA_DIAS, abrir_busca_de_dias, indexar_dias
from src.agente.dias.perfis import agrupar_perfis, perfis_diarios, vizinhos_por_perfil
from src.agente.dias.resumos import resumos_diarios
from src.agente.fabrica import busca_de_dias_da_config, criar_agente
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.ferramentas.consulta_dados import FiltroMedicoes
from src.agente.guardrails.saida import numeros_sem_origem
from src.agente.llm.base import RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.agente.prompts import montar_system_prompt
from src.agente.rag.embeddings import EmbedderSimulado
from src.agente.rag.indexador import indexar
from src.config import ConfigAgente


def medicao(dia: int, codigo: str, valor: float, hora: int = 12, estacao: str = "EST-1") -> dict:
    """Uma medição no formato de get_medicoes() (nome e unidade pelo código)."""
    nomes = {"TIP-CHU": ("Precipitação", "mm"), "TIP-TMP": ("Temperatura do ar", "°C"), "TIP-VEN": ("Velocidade do vento", "km/h")}
    return {
        "estacao_codigo": estacao, "estacao": f"Estação {estacao}", "codigo_registro": f"R-{estacao}-{dia}-{hora}-{codigo}",
        "data_hora": datetime(2026, 6, dia, hora), "codigo_parametro": codigo, "parametro": nomes[codigo][0],
        "unidade_medida": nomes[codigo][1], "valor": valor,
    }


def todas(consulta) -> list[dict]:
    """Todas as medições da consulta."""
    return consulta.medicoes(FiltroMedicoes())


# --- Resumos ------------------------------------------------------------------------------


def test_resumo_traz_chuva_media_com_rotulo_e_anomalias_do_dia():
    consulta, _ = montar_consulta()

    resumos = {r.dia: r for r in resumos_diarios(todas(consulta))}

    assert resumos[date(2026, 6, 2)].texto.splitlines()[0] == "02/06/2026, estação EST-1"
    assert resumos[date(2026, 6, 2)].conteudo.startswith("Sem chuva: 0 mm no dia. pH: média")
    assert resumos[date(2026, 6, 2)].conteudo.endswith("1 anomalia: 1 de pH.")
    assert resumos[date(2026, 6, 1)].conteudo == resumos[date(2026, 6, 3)].conteudo  # dias iguais, mesmo texto
    assert "Sem anomalias." in resumos[date(2026, 6, 1)].conteudo


def test_tercis_rotulam_o_dia_em_relacao_aos_outros_da_estacao():
    medicoes = [medicao(dia, "TIP-TMP", 15.0 + dia) for dia in range(1, 7)]

    rotulos = [r.conteudo.split(", ")[1].split(" para")[0] for r in resumos_diarios(medicoes)]

    assert rotulos == ["baixa", "baixa", "típica", "típica", "alta", "alta"]


@pytest.mark.parametrize("chuva, rotulo", [(0.0, "Sem chuva"), (5.0, "Chuva fraca"), (5.1, "Chuva moderada"), (25.0, "Chuva moderada"), (25.1, "Chuva forte")])
def test_faixas_do_acumulado_de_chuva(chuva, rotulo):
    medicoes = [medicao(1, "TIP-CHU", chuva / 2, hora=6), medicao(1, "TIP-CHU", chuva / 2, hora=18)]

    assert resumos_diarios(medicoes)[0].conteudo.startswith(f"{rotulo}:")


def test_vento_e_resumido_pelo_maximo():
    medicoes = [medicao(1, "TIP-VEN", 10.0, hora=6), medicao(1, "TIP-VEN", 42.5, hora=15)]

    assert "Velocidade do vento: máxima 42,5 km/h" in resumos_diarios(medicoes)[0].conteudo


def test_numeros_do_resumo_tem_origem_para_a_pol03():
    resumo = resumos_diarios([medicao(1, "TIP-TMP", 21.3), medicao(1, "TIP-CHU", 12.4)])[0]
    resultado = ResultadoFerramenta.ok("c1", {"dias": [{"data": "2026-06-01", "resumo": resumo.conteudo}]})

    assert numeros_sem_origem("Em 01/06 choveu 12,4 mm e a média foi 21,3 °C.", [resultado]) == []


# --- Índice -------------------------------------------------------------------------------


def test_indice_dos_dias_e_idempotente_e_so_revetoriza_o_dia_que_mudou(tmp_path):
    consulta, _ = montar_consulta()
    medicoes = todas(consulta)

    primeira = indexar_dias(medicoes, EmbedderSimulado(), tmp_path)
    segunda = indexar_dias(medicoes, EmbedderSimulado(), tmp_path)
    com_chuva = [{**m, "valor": 3.0} if m["codigo_parametro"] == "TIP-CHU" and m["data_hora"].date() == date(2026, 6, 3) else m for m in medicoes]
    terceira = indexar_dias(com_chuva, EmbedderSimulado(), tmp_path)

    assert (primeira.arquivos, primeira.chunks, primeira.inseridos) == (1, 3, 3)
    assert (segunda.inseridos, segunda.removidos) == (0, 0)
    assert (terceira.inseridos, terceira.removidos) == (1, 1)


def test_indice_dos_dias_fica_separado_do_da_documentacao(tmp_path):
    consulta, _ = montar_consulta()
    indexar(EmbedderSimulado(), tmp_path)
    indexar_dias(todas(consulta), EmbedderSimulado(), tmp_path)

    vizinhos = abrir_busca_de_dias(EmbedderSimulado(), tmp_path).vizinhos("regra IQR da precipitação e LGPD", "EST-1", "2026-06-01", 10)

    assert (tmp_path / PASTA_DIAS).is_dir()
    assert {t.arquivo for t in vizinhos} == {"dias/EST-1"}  # nenhum documento vem na busca de dias


def test_indice_de_outro_modelo_nao_e_usado(tmp_path):
    consulta, _ = montar_consulta()
    indexar_dias(todas(consulta), EmbedderSimulado(dimensoes=256), tmp_path)

    outro = EmbedderSimulado(dimensoes=256)
    outro.modelo = "outro-modelo"  # mesmo cálculo, outro nome: o índice não serve

    assert abrir_busca_de_dias(outro, tmp_path) is None


# --- Ferramenta ---------------------------------------------------------------------------


def test_dias_parecidos_excluem_o_proprio_dia_e_outras_estacoes(tmp_path):
    consulta, _ = montar_consulta(n_estacoes=2)
    indexar_dias(todas(consulta), EmbedderSimulado(), tmp_path)
    registro = criar_registro(consulta, dias=abrir_busca_de_dias(EmbedderSimulado(), tmp_path))

    resultado = registro.executar(ChamadaFerramenta("c1", "dias_semelhantes", {"data": "2026-06-01", "estacao": "EST-2"}))

    assert resultado.sucesso, resultado.erro
    assert [d["data"] for d in resultado.dados["dias"]] == ["2026-06-03", "2026-06-02"]
    assert resultado.dados["dias"][0]["similaridade"] == 1.0 and resultado.dados["estacao"] == "EST-2"
    assert "resumo_estatistico" in resultado.dados["aviso"]


@pytest.mark.parametrize(
    "argumentos, mensagem",
    [
        ({"data": "2026-06-01"}, "informe o argumento estacao"),
        ({"data": "2026-07-01", "estacao": "EST-1"}, "dias com dados: 01/06/2026 a 03/06/2026"),
        ({"data": "2026-06-01", "estacao": "EST-9"}, "estação inexistente"),
        ({"data": "2026-06-01", "estacao": "EST-1", "top_k": 11}, "top_k"),
        ({"data": "2026-06-01", "estacao": "EST-1", "parametro": "TIP-PH"}, "parametro"),
    ],
)
def test_erros_da_ferramenta_voltam_ao_llm_como_texto(tmp_path, argumentos, mensagem):
    consulta, _ = montar_consulta(n_estacoes=2)
    indexar_dias(todas(consulta), EmbedderSimulado(), tmp_path)
    registro = criar_registro(consulta, dias=abrir_busca_de_dias(EmbedderSimulado(), tmp_path))

    resultado = registro.executar(ChamadaFerramenta("c1", "dias_semelhantes", argumentos))

    assert not resultado.sucesso and mensagem in resultado.erro


def test_aceite_dia_parecido_e_numero_exato_por_resumo_estatistico(consulta, busca_dias):
    """Aceite da Fase 9: dias parecidos com resumo, e o número exato pela ferramenta de dados."""
    llm = LLMRoteirizado([
        RespostaLLM(chamadas=[ChamadaFerramenta("c1", "dias_semelhantes", {"data": "2026-06-01", "top_k": 1})], motivo_parada="ferramentas"),
        RespostaLLM(chamadas=[ChamadaFerramenta("c2", "resumo_estatistico", {"parametros": ["TIP-TMP"], "data_inicio": "2026-06-03", "data_fim": "2026-06-03"})], motivo_parada="ferramentas"),
        RespostaLLM(texto="O dia mais parecido com 01/06 foi 03/06, com temperatura média de 26 °C."),
    ])
    agente = criar_agente(ConfigAgente("simulado"), llm, consulta, dias=busca_dias)

    resposta = agente.perguntar("Que dia foi parecido com 01/06? Qual a temperatura média nele?")

    assert [f.descricao.split("(")[0] for f in resposta.fontes] == ["dias_semelhantes", "resumo_estatistico"]
    assert "⚠" not in resposta.texto  # 26 °C veio do resumo_estatistico (POL-03)
    assert "dias_semelhantes compara os RESUMOS" in llm.chamadas_recebidas[0].system


def test_system_prompt_so_fala_de_dias_com_a_ferramenta():
    com = montar_system_prompt(date(2026, 10, 21), [], ["resumo_estatistico", "dias_semelhantes"])
    sem = montar_system_prompt(date(2026, 10, 21), [], ["resumo_estatistico"])

    assert "dias_semelhantes" in com and "dias_semelhantes" not in sem


def test_fabrica_sem_indice_dos_dias_avisa_e_segue(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert busca_de_dias_da_config(ConfigAgente("anthropic", dir_indice=tmp_path), EmbedderSimulado()) is None

    assert "--indexar-dias" in caplog.text


def test_indexar_dias_exige_a_connection_string(monkeypatch):
    import main
    from src.config import ConfigIndice

    monkeypatch.setattr("src.config.load_config_indice", lambda: ConfigIndice())

    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        main.indexar_dias()


# --- Perfis numéricos ---------------------------------------------------------------------


def curva(dia: int, nivel: float, amplitude: float, falta: set[int] = frozenset(), ruido: float = 0.0) -> list[dict]:
    """48 medições de temperatura (seno ao longo do dia), com pontos faltando e ruído determinístico."""
    inicio = datetime(2026, 6, dia)
    perturbacao = np.random.default_rng(dia).normal(0, ruido, 48) if ruido else np.zeros(48)
    return [
        {"estacao_codigo": "EST-1", "codigo_parametro": "TIP-TMP", "data_hora": inicio + timedelta(minutes=30 * i),
         "valor": nivel + amplitude * float(np.sin(np.pi * i / 47)) + float(perturbacao[i])}
        for i in range(48) if i not in falta
    ]


def test_perfil_preenche_lacunas_e_descarta_dia_com_poucos_pontos():
    perfis = perfis_diarios(curva(1, 20, 5, falta={10, 11}) + curva(2, 20, 5, falta=set(range(30))))

    assert list(perfis) == [("EST-1", date(2026, 6, 1))]
    assert np.isfinite(perfis[("EST-1", date(2026, 6, 1))]).all()


def test_perfil_normalizado_compara_o_formato_e_nao_o_nivel():
    perfis = perfis_diarios(curva(1, 20, 5) + curva(2, 30, 5) + curva(3, 20, -5))

    vizinhos = vizinhos_por_perfil(perfis, "EST-1", date(2026, 6, 1), 2)

    assert vizinhos[0] == (date(2026, 6, 2), pytest.approx(0.0, abs=1e-9))  # mesmo formato, 10 °C acima
    assert vizinhos[1][0] == date(2026, 6, 3)  # formato invertido: o mais distante


def test_kmeans_escolhe_o_k_pela_silhueta_e_exige_perfis_suficientes():
    perfis = perfis_diarios([m for dia in range(1, 7) for m in curva(dia, 20, 5 if dia <= 3 else -5, ruido=0.3)])
    agrupamento = agrupar_perfis(np.array(list(perfis.values())), ks=[2, 3, 4])

    assert agrupamento.k == 2 and len(set(agrupamento.rotulos[:3])) == 1 and agrupamento.rotulos[0] != agrupamento.rotulos[5]
    assert set(agrupamento.inercias) == {2, 3, 4}
    with pytest.raises(ValueError, match="não bastam"):
        agrupar_perfis(np.zeros((2, 48)), ks=[2, 3])
