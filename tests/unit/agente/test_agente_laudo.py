"""
Laudo de anomalias em JSON (Fase 11): contrato, contexto, geração com o LLM roteirizado e exportação.

Sem rede e sem chave: o LLM é o roteirizado. Os dados falsos do conftest têm
uma anomalia de pH (9,9 às 06:00 de 02/06/2026).
"""
import csv
import logging
from datetime import date, datetime

import pytest

from dados_falsos_agente import montar_consulta
from src.agente.ferramentas.consulta_dados import FiltroMedicoes
from src.agente.laudo.contexto import AnomaliaComContexto, anomalias_com_contexto
from src.agente.laudo.contrato import validar_resposta
from src.agente.laudo.gerador import SYSTEM_LAUDO, exportar_laudos, gerar_laudo, gerar_laudos
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.config import ConfigAgente

VALIDO = '{"registro": "REG-1", "causa_provavel": "falha_sensor", "severidade": 3, "justificativa": "Pico isolado sem chuva."}'


def anomalia(registro: str = "REG-1", zscore: float | None = 4.0, dia: int = 10, texto: str = "Anomalia: Turbidez = 480 NTU.") -> AnomaliaComContexto:
    """Anomalia pronta, sem passar pela análise."""
    return AnomaliaComContexto(registro, "EST-1", "TIP-TUR", "Turbidez", "NTU", datetime(2026, 6, dia, 3), 480.0, "IQR+ZSCORE", zscore, texto)


# --- Contrato -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, politica, motivo",
    [
        ("Acho que foi falha do sensor.", "POL-06", "json_ausente"),
        ('{"registro": "REG-1", "causa_provavel": ', "POL-06", "json_ausente"),
        ('{"registro": "REG-1", causa: falha}', "POL-06", "json_invalido"),
        (VALIDO.replace(', "justificativa": "Pico isolado sem chuva."', ""), "POL-06", "campos:justificativa"),
        (VALIDO.replace('"severidade": 3', '"severidade": 6'), "POL-06", "campos:severidade"),
        (VALIDO.replace("falha_sensor", "defeito"), "POL-06", "campos:causa_provavel"),
        (VALIDO.replace("}", ', "confianca": 0.9}'), "POL-06", "campos:confianca"),
        (VALIDO.replace("Pico isolado sem chuva.", "x" * 401), "POL-06", "campos:justificativa"),
        (VALIDO.replace("REG-1", "REG-2"), "POL-06", "registro_trocado"),
        (VALIDO.replace("Pico isolado sem chuva.", "Pico de 999 NTU."), "POL-03", "numeros_sem_origem:1"),
    ],
)
def test_resposta_fora_do_contrato_e_descartada(texto, politica, motivo):
    validacao = validar_resposta(texto, "REG-1", contexto="Anomalia: Turbidez = 480 NTU.")

    assert (validacao.valido, validacao.politica, validacao.motivo) == (False, politica, motivo)


def test_json_entre_cercas_e_numero_do_contexto_sao_aceitos():
    texto = "```json\n" + VALIDO.replace("Pico isolado sem chuva.", "Pico de 480 NTU sem chuva.") + "\n```"

    validacao = validar_resposta(texto, "REG-1", contexto="Anomalia: Turbidez = 480 NTU.")

    assert validacao.valido and validacao.laudo.justificativa == "Pico de 480 NTU sem chuva."


# --- Contexto -------------------------------------------------------------------------------


def test_contexto_tem_vizinhos_mesma_leitura_e_chuva():
    consulta, _ = montar_consulta()
    medicoes = consulta.medicoes(FiltroMedicoes())

    [pico] = [a for a in anomalias_com_contexto(medicoes, medicoes) if a.parametro == "TIP-PH"]
    linhas = pico.texto.splitlines()

    assert (pico.data_hora, pico.valor, pico.alerta) == (datetime(2026, 6, 2, 6), 9.9, "IQR+ZSCORE")
    assert linhas[0].startswith("Anomalia: pH = 9,9 pH em 02/06/2026 06:00")
    assert linhas[1] == "Mesmo parâmetro, 2 h antes e depois: " + "; ".join(
        f"{h:02d}:{m:02d} = {7 if h % 2 == 0 else 7.2:g}".replace(".", ",") for h, m in ((4, 0), (4, 30), (5, 0), (5, 30), (6, 30), (7, 0), (7, 30), (8, 0))
    ) + "."
    assert linhas[2].startswith("Outros parâmetros da mesma leitura: Precipitação 0 mm; Temperatura do ar")
    assert linhas[3] == "Chuva acumulada nas 3 h anteriores (inclui a leitura): 0 mm."


def test_anomalia_na_borda_usa_a_margem_para_os_vizinhos():
    """Pico às 00:30 do dia 2: os vizinhos de 2 h antes estão no dia 1, fora do período pedido."""

    def turbidez(dia: int, hora: int, minuto: int, valor: float) -> dict:
        """Uma medição de turbidez."""
        return {"estacao_codigo": "EST-1", "estacao": "Estação 1", "codigo_registro": f"R-{dia}-{hora:02d}{minuto:02d}",
                "data_hora": datetime(2026, 6, dia, hora, minuto), "codigo_parametro": "TIP-TUR", "parametro": "Turbidez",
                "unidade_medida": "NTU", "valor": valor}

    dia_1 = [turbidez(1, 23, m, 5.0) for m in (0, 30)]
    dia_2 = [turbidez(2, h, m, 480.0 if (h, m) == (0, 30) else 5.0 + h) for h in range(3) for m in (0, 30)]

    com_margem = anomalias_com_contexto(dia_2, dia_1 + dia_2)[0]
    sem_margem = anomalias_com_contexto(dia_2, dia_2)[0]

    assert "23:00 = 5; 23:30 = 5; 00:00 = 5" in com_margem.texto
    assert "23:00" not in sem_margem.texto
    assert anomalias_com_contexto([], []) == []


# --- Geração --------------------------------------------------------------------------------


def test_laudo_usa_o_prompt_few_shot_sem_ferramentas():
    llm = LLMRoteirizado([RespostaLLM(texto=VALIDO)])

    resultado = gerar_laudo(llm, anomalia())

    entrada = llm.chamadas_recebidas[0]
    assert resultado.validacao.valido
    assert entrada.system == SYSTEM_LAUDO and "EXEMPLO 1" in entrada.system and "EXEMPLO 2" in entrada.system
    assert entrada.ferramentas == () and "Anomalia: Turbidez = 480 NTU." in entrada.mensagens[0].texto


def test_descarte_vai_para_o_log_com_a_politica_e_sem_o_texto_do_llm(caplog):
    invalido = VALIDO.replace('"severidade": 3', '"nivel": 3').replace("Pico isolado sem chuva.", "TEXTO-SECRETO-DO-LLM")

    with caplog.at_level(logging.WARNING):
        resultado = gerar_laudo(LLMRoteirizado([RespostaLLM(texto=invalido)]), anomalia())

    assert not resultado.validacao.valido
    assert "guardrail=POL-06 conversa=laudo acao=laudo_descartado registro=REG-1 motivo=campos:nivel,severidade" in caplog.text
    assert "TEXTO-SECRETO-DO-LLM" not in caplog.text


def test_falha_do_provedor_descarta_so_aquele_laudo():
    llm = LLMRoteirizado([ErroProvedorLLM("APITimeoutError"), RespostaLLM(texto=VALIDO.replace("REG-1", "REG-2"))])

    resultados = gerar_laudos(llm, [anomalia("REG-1", dia=10), anomalia("REG-2", dia=11)])

    assert [r.validacao.motivo for r in resultados] == ["falha_provedor", None]


def test_limite_pega_as_mais_extremas_e_devolve_em_ordem_de_data(caplog):
    anomalias = [anomalia("REG-A", 3.5, dia=10), anomalia("REG-B", 9.0, dia=11), anomalia("REG-C", None, dia=12), anomalia("REG-D", -6.0, dia=13)]
    respostas = [RespostaLLM(texto=VALIDO.replace("REG-1", r)) for r in ("REG-B", "REG-D")]

    with caplog.at_level(logging.INFO):
        resultados = gerar_laudos(LLMRoteirizado(respostas), anomalias, limite=2)

    assert [r.anomalia.registro for r in resultados] == ["REG-B", "REG-D"]
    assert "Laudos: anomalias=4 pedidos=2 validos=2 descartados=0" in caplog.text


# --- Exportação e aceite --------------------------------------------------------------------


def test_aceite_laudos_do_mes_validados_e_sinalizados_como_ia(tmp_path):
    """Aceite da Fase 11: laudos das anomalias de um período, todos validados e marcados como gerados por IA."""
    consulta, _ = montar_consulta()
    medicoes = consulta.medicoes(FiltroMedicoes(data_inicio=date(2026, 6, 1), data_fim=date(2026, 6, 30)))
    anomalias = anomalias_com_contexto(medicoes, medicoes)
    respostas = [
        RespostaLLM(texto=VALIDO.replace("REG-1", a.registro).replace("Pico isolado sem chuva.", "Pico isolado; contato: fulano@exemplo.com"))
        for a in anomalias
    ]

    resultados = gerar_laudos(LLMRoteirizado(respostas), anomalias)
    caminho_csv, caminho_md = exportar_laudos(resultados, tmp_path, "laudos_2026-06-01_2026-06-30", "claude-haiku-5-5")

    with caminho_csv.open(encoding="utf-8-sig") as arquivo:
        linhas = list(csv.DictReader(arquivo, delimiter=";"))
    relatorio = caminho_md.read_text(encoding="utf-8")
    assert len(anomalias) >= 1 and len(linhas) == len(anomalias)
    assert all(l["gerado_por"] == "IA (claude-haiku-5-5)" and l["causa_provavel"] == "falha_sensor" for l in linhas)
    assert "⚠ Gerado por IA (claude-haiku-5-5)" in relatorio and "não altera o indicador de alerta (D9)" in relatorio
    assert "fulano@exemplo.com" not in relatorio + caminho_csv.read_text(encoding="utf-8-sig")  # POL-02 na saída


def test_relatorio_lista_os_descartados_com_o_motivo(tmp_path):
    resultados = gerar_laudos(LLMRoteirizado([RespostaLLM(texto="não sei")]), [anomalia()])

    _, caminho_md = exportar_laudos(resultados, tmp_path, "laudos", "claude-haiku-5-5")

    assert "- REG-1: POL-06 json_ausente" in caminho_md.read_text(encoding="utf-8")


def test_comando_laudo_exige_o_llm_real(monkeypatch):
    import main

    monkeypatch.setattr("src.config.load_config_agente", lambda: ConfigAgente("simulado"))

    with pytest.raises(ValueError, match="AGENTE_LLM_FORNECEDOR=anthropic ou openai"):
        main.gerar_laudos_de_anomalias(None, date(2026, 6, 1), None, None)
