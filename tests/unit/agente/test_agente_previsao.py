"""
Previsão (Fase 10): atributos sem vazamento, validação temporal, baselines,
regra de aceite, integridade do modelo (POL-12) e a ferramenta prever.

Sem banco e sem rede: séries sintéticas e os dados falsos do conftest (EST-1,
01 a 03/06/2026, temperatura com ciclo diário).
"""
import json
import logging
from datetime import date

import numpy as np
import pandas as pd
import pytest

from dados_falsos_agente import montar_consulta
from src.agente.contratos import ChamadaFerramenta
from src.agente.fabrica import criar_agente, modelo_previsao_da_config
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.llm.base import RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.agente.prompts import montar_system_prompt
from src.config import ConfigAgente
from src.previsao import treino
from src.previsao.atributos import linhas_completas, montar_atributos
from src.previsao.baselines import mae_e_rmse, previsoes_dos_baselines
from src.previsao.persistencia import ARQUIVO_METADADOS, ARQUIVO_MODELO, carregar_modelo, salvar_modelo
from src.previsao.relatorio import AVISO_SINTETICOS, montar_relatorio_treino
from src.previsao.treino import avaliar_horizonte, treinar


def serie_sintetica(dias: int = 30, ruido: float = 0.3, persistencia: float = 0.9, semente: int = 0) -> pd.Series:
    """Temperatura com ciclo diário e ruído persistente (AR(1)), de 30 em 30 minutos."""
    indice = pd.date_range("2026-06-01", periods=48 * dias, freq="30min")
    ciclo = 22 + 6 * np.sin(2 * np.pi * (indice.hour + indice.minute / 60 - 9) / 24)
    aleatorio, anomalia, ruidos = np.random.default_rng(semente), 0.0, []
    for _ in indice:
        anomalia = persistencia * anomalia + aleatorio.normal(0, ruido)
        ruidos.append(anomalia)
    return pd.Series(ciclo + np.array(ruidos), index=indice, name="TIP-TMP")


def medicoes_da_serie(serie: pd.Series, estacao: str = "EST-1") -> list[dict]:
    """A série no formato de get_medicoes()."""
    return [
        {"estacao_codigo": estacao, "codigo_parametro": serie.name, "data_hora": instante.to_pydatetime(), "valor": float(valor)}
        for instante, valor in serie.items()
    ]


# --- Atributos e baselines ------------------------------------------------------------------


@pytest.mark.parametrize("horas", [1, 6, 24])
def test_nenhum_atributo_usa_o_instante_previsto_ou_posterior(horas):
    """Sem vazamento temporal: trocar todo o futuro de t não muda os atributos de t."""
    serie = serie_sintetica(dias=5)
    t = serie.index[150]
    futuro_trocado = serie.copy()
    futuro_trocado[futuro_trocado.index > t] = 999.0

    original, _ = montar_atributos(serie, horas)
    alterado, y = montar_atributos(futuro_trocado, horas)

    pd.testing.assert_series_equal(original.loc[t], alterado.loc[t])
    assert y[t] == 999.0  # o alvo, sim, é o futuro (t + horas)


def test_lacuna_e_preenchida_so_com_o_passado():
    serie = serie_sintetica(dias=3)
    serie.iloc[100] = np.nan

    X, _ = montar_atributos(serie, 1)

    assert X["lag_0"].iloc[100] == serie.iloc[99]  # forward fill, nunca a média com o vizinho futuro


def test_baselines_e_metricas_calculados_a_mao():
    X = pd.DataFrame({"lag_0": [20.0, 22.0, 24.0], "sazonal": [21.0, 23.0, 23.0]})
    real = [21.0, 23.0, 26.0]

    previsoes = previsoes_dos_baselines(X)

    assert mae_e_rmse(real, previsoes["ingenuo"]) == {"mae": 1.3333, "rmse": 1.4142}  # erros 1, 1 e 2
    assert mae_e_rmse(real, previsoes["ingenuo_sazonal"]) == {"mae": 1.0, "rmse": 1.7321}  # erros 0, 0 e 3


def test_horizonte_fora_de_1_a_24_horas_e_recusado():
    with pytest.raises(ValueError, match="fora de 1 a 24"):
        montar_atributos(serie_sintetica(dias=2), 25)


# --- Validação temporal e regra de aceite -------------------------------------------------


def test_time_series_split_treina_sempre_antes_da_validacao_com_gap(monkeypatch):
    dobras = []

    class Gravador:
        """Modelo falso que anota os instantes vistos no fit e no predict."""

        def fit(self, X, y):
            """Guarda o último instante do treino."""
            self.fim_treino = X.index.max()
            return self

        def predict(self, X):
            """Anota (fim do treino, início da validação) e prevê o lag_0."""
            dobras.append((self.fim_treino, X.index.min()))
            return X["lag_0"].to_numpy()

    monkeypatch.setattr(treino, "candidatos", lambda: {"Gravador": Gravador})

    avaliar_horizonte(serie_sintetica(dias=20), "EST-1", "TIP-TMP", 6, dobras=4, dias_de_teste=5)

    validacoes = dobras[:4]
    assert all(inicio - fim > pd.Timedelta(hours=6) for fim, inicio in validacoes)  # gap = horizonte
    assert [inicio for _, inicio in validacoes] == sorted(inicio for _, inicio in validacoes)


def test_modelo_vence_os_baselines_e_e_publicado():
    avaliacao = avaliar_horizonte(serie_sintetica(), "EST-1", "TIP-TMP", 6, dobras=3, dias_de_teste=7)

    assert avaliacao.aprovado and avaliacao.pipeline is not None
    assert avaliacao.validacao["modelo"]["mae"] < min(avaliacao.validacao["ingenuo"]["mae"], avaliacao.validacao["ingenuo_sazonal"]["mae"])
    assert set(avaliacao.teste) == {"modelo", "ingenuo", "ingenuo_sazonal"}


def test_ciclo_perfeito_o_sazonal_e_imbativel_e_o_horizonte_nao_e_publicado():
    """Regra de aceite: sem ruído, "a mesma hora de ontem" acerta tudo (MAE 0)."""
    avaliacao = avaliar_horizonte(serie_sintetica(ruido=0.0), "EST-1", "TIP-TMP", 6, dobras=3, dias_de_teste=7)

    assert avaliacao.validacao["ingenuo_sazonal"]["mae"] == 0.0
    assert not avaliacao.aprovado and avaliacao.pipeline is None


def test_poucos_dados_nao_geram_avaliacao():
    assert treinar(medicoes_da_serie(serie_sintetica(dias=5))) == []


# --- Persistência (POL-12) ----------------------------------------------------------------


@pytest.fixture(scope="module")
def avaliacoes():
    """Treino real e pequeno: TIP-TMP da EST-1 em 1 e 6 h."""
    return treinar(medicoes_da_serie(serie_sintetica()), horizontes=(1, 6), dobras=3, dias_de_teste=7)


def test_modelo_salvo_carrega_com_o_hash_e_a_versao(avaliacoes, tmp_path):
    salvar_modelo(avaliacoes, tmp_path)
    metadados = json.loads((tmp_path / ARQUIVO_METADADOS).read_text(encoding="utf-8"))

    modelo = carregar_modelo(tmp_path)

    assert modelo is not None and "EST-1|TIP-TMP|6" in metadados["aprovados"]
    assert set(metadados["avaliacoes"]) == {"EST-1|TIP-TMP|1", "EST-1|TIP-TMP|6"}  # aprovadas ou não, todas registradas
    assert len(metadados["sha256"]) == 64 and metadados["versao_sklearn"]


def test_arquivo_do_modelo_alterado_e_recusado(avaliacoes, tmp_path, caplog):
    salvar_modelo(avaliacoes, tmp_path)
    with open(tmp_path / ARQUIVO_MODELO, "ab") as arquivo:
        arquivo.write(b"adulterado")

    with caplog.at_level(logging.WARNING):
        assert carregar_modelo(tmp_path) is None
    assert "guardrail=POL-12" in caplog.text and "sha256_diferente" in caplog.text


def test_modelo_de_outra_versao_do_sklearn_e_recusado(avaliacoes, tmp_path, caplog):
    caminho = salvar_modelo(avaliacoes, tmp_path)
    metadados = json.loads(caminho.read_text(encoding="utf-8"))
    caminho.write_text(json.dumps({**metadados, "versao_sklearn": "0.1.0"}), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert carregar_modelo(tmp_path) is None
    assert "versao_sklearn" in caplog.text


def test_relatorio_marca_o_que_nao_supera_o_baseline_e_avisa_dos_dados_sinteticos(avaliacoes):
    reprovada = treino.AvaliacaoHorizonte("EST-1", "TIP-UMI", 1, "Ridge", False, avaliacoes[0].validacao, {}, 10, 0, ("", ""))

    texto = montar_relatorio_treino([*avaliacoes, reprovada])

    assert AVISO_SINTETICOS in texto and "✘ não supera o baseline" in texto


# --- Ferramenta prever --------------------------------------------------------------------


def executar(registro, **argumentos):
    """Chama prever pelo registro (validação, erros e truncamento, como o agente)."""
    return registro.executar(ChamadaFerramenta("c1", "prever", argumentos))


def test_prever_parte_da_ultima_leitura_e_traz_o_erro_esperado(consulta, modelo_previsao):
    resultado = executar(criar_registro(consulta, modelo_previsao=modelo_previsao), parametro="TIP-TMP", horizonte_horas=6)

    assert resultado.sucesso, resultado.erro
    dados = resultado.dados
    assert (dados["referencia"], dados["instante_previsto"], dados["previsao"], dados["unidade"]) == ("2026-06-03T23:30:00", "2026-06-04T05:30:00", 25.0, "°C")
    assert dados["erro_validacao"]["modelo"]["mae"] == 0.62 and "ingenuo_sazonal" in dados["erro_teste"]
    assert "Estimativa" in dados["aviso"] and "sintéticos" in dados["aviso"]


@pytest.mark.parametrize(
    "argumentos, mensagem",
    [
        ({"parametro": "TIP-TMP", "horizonte_horas": 1}, "não supera o baseline"),
        ({"parametro": "TIP-TMP", "horizonte_horas": 12}, "horizontes disponíveis: 6"),
        ({"parametro": "TIP-PH", "horizonte_horas": 6}, "parametro"),
        ({"parametro": "TIP-TMP", "horizonte_horas": 30}, "horizonte_horas"),
    ],
)
def test_horizonte_reprovado_ou_invalido_volta_como_erro(consulta, modelo_previsao, argumentos, mensagem):
    resultado = executar(criar_registro(consulta, modelo_previsao=modelo_previsao), **argumentos)

    assert not resultado.sucesso and mensagem in resultado.erro


def test_com_duas_estacoes_a_estacao_e_obrigatoria(modelo_previsao):
    consulta, _ = montar_consulta(n_estacoes=2)

    resultado = executar(criar_registro(consulta, modelo_previsao=modelo_previsao), parametro="TIP-TMP", horizonte_horas=6)

    assert "informe o argumento estacao" in resultado.erro


def test_lacuna_nas_ultimas_24_horas_impede_a_previsao(modelo_previsao):
    consulta, leituras = montar_consulta()
    leituras.medicoes = [m for m in leituras.medicoes if not (m["codigo_parametro"] == "TIP-TMP" and m["data_hora"].date() == date(2026, 6, 3) and m["data_hora"].hour < 12)]

    resultado = executar(criar_registro(consulta, modelo_previsao=modelo_previsao), parametro="TIP-TMP", horizonte_horas=6)

    assert not resultado.sucesso and "lacunas" in resultado.erro


def test_aceite_previsao_com_mae_e_baseline_sem_aviso_da_pol03(consulta, modelo_previsao):
    """Aceite da Fase 10: a resposta traz a previsão, o MAE e a comparação com o baseline, tudo vindo da ferramenta."""
    llm = LLMRoteirizado([
        RespostaLLM(chamadas=[ChamadaFerramenta("c1", "prever", {"parametro": "TIP-TMP", "horizonte_horas": 6})], motivo_parada="ferramentas"),
        RespostaLLM(texto="Estimativa para 04/06 às 05:30: 25 °C, com erro médio (MAE) de 0,62 °C; o ingênuo sazonal erra 0,95 °C."),
    ])
    agente = criar_agente(ConfigAgente("simulado"), llm, consulta, modelo_previsao=modelo_previsao)

    resposta = agente.perguntar("Como fica a temperatura nas próximas 6 horas?")

    assert "⚠" not in resposta.texto and resposta.fontes[0].descricao.startswith("prever(")
    assert "prever devolve uma ESTIMATIVA" in llm.chamadas_recebidas[0].system


def test_prompt_so_fala_de_previsao_com_a_ferramenta():
    assert "prever devolve" in montar_system_prompt(date(2026, 10, 21), [], ["prever"])
    assert "prever devolve" not in montar_system_prompt(date(2026, 10, 21), [], ["resumo_estatistico"])


def test_ciclo_completo_treinar_salvar_carregar_e_prever(avaliacoes, tmp_path, consulta):
    """O Pipeline real, carregado do disco, prevê a partir dos dados falsos do conftest."""
    salvar_modelo(avaliacoes, tmp_path)
    registro = criar_registro(consulta, modelo_previsao=carregar_modelo(tmp_path))

    resultado = executar(registro, parametro="TIP-TMP", horizonte_horas=6)

    assert resultado.sucesso, resultado.erro
    assert 10 < resultado.dados["previsao"] < 40 and resultado.dados["modelo"] in ("Ridge", "HistGradientBoosting")


def test_fabrica_sem_modelo_avisa_e_segue(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert modelo_previsao_da_config(ConfigAgente("anthropic", dir_indice=tmp_path)) is None
    assert "--treinar-previsao" in caplog.text


def test_treinar_previsao_exige_a_connection_string(monkeypatch):
    import main
    from src.config import ConfigIndice

    monkeypatch.setattr("src.config.load_config_indice", lambda: ConfigIndice())

    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        main.treinar_previsao()
