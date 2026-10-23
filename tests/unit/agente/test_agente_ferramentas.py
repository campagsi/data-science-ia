"""
Ferramentas descritivas, registro e ConsultaDados, sem banco (dados falsos do conftest).

Os resultados esperados são calculados de forma independente (módulo
statistics do Python ou à mão), e não com o mesmo pandas das ferramentas.
"""
import logging
import statistics
from datetime import date, datetime

import numpy as np
import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.ferramentas.base import normalizar_json
from src.agente.ferramentas.catalogo import FERRAMENTAS_DE_DADOS, criar_registro
from src.agente.ferramentas.descritivas import criar_ferramentas_descritivas
from src.agente.ferramentas.consulta_dados import MAXIMO_RECORTES_EM_CACHE, FiltroMedicoes
from src.agente.ferramentas.registro import ERRO_INESPERADO
from src.repository.leitura_repository import LeituraRepository

from dados_falsos_agente import LEITURAS_POR_ESTACAO, PICO_PH, montar_consulta


def executar(registro, nome: str, **argumentos):
    """Executa uma ferramenta pelo registro, como o orquestrador fará."""
    return registro.executar(ChamadaFerramenta("c1", nome, argumentos))


# --- Especificações -----------------------------------------------------------


def test_especificacoes_tem_descricao_e_schema_fechado(registro):
    especificacoes = registro.especificacoes()

    assert [e["name"] for e in especificacoes] == list(FERRAMENTAS_DE_DADOS)
    for especificacao in especificacoes:
        assert len(especificacao["description"]) > 80  # o que faz, quando usar e quando não usar
        assert especificacao["input_schema"]["additionalProperties"] is False  # POL-06
        assert "title" not in str(especificacao["input_schema"])


def test_schema_mostra_os_valores_fechados_como_enum(registro):
    serie = next(e for e in registro.especificacoes() if e["name"] == "serie_temporal")
    propriedades = serie["input_schema"]["properties"]

    assert propriedades["granularidade"]["enum"] == ["hora", "dia", "semana", "mes"]
    assert set(serie["input_schema"]["required"]) == {"parametro", "data_inicio", "data_fim", "granularidade"}


# --- panorama_dados e listar_parametros ---------------------------------------


def test_panorama_mostra_estacao_cobertura_e_intervalo(registro):
    resultado = executar(registro, "panorama_dados")

    estacao = resultado.dados["estacoes"][0]
    assert resultado.sucesso
    assert (estacao["codigo"], estacao["municipio"], estacao["uf"]) == ("EST-1", "Rio de Janeiro", "RJ")
    assert estacao["primeira_leitura"] == "2026-06-01T00:00:00"
    assert estacao["ultima_leitura"] == "2026-06-03T23:30:00"
    assert (estacao["leituras"], estacao["intervalo_medio_minutos"]) == (LEITURAS_POR_ESTACAO, 30)
    assert resultado.dados["parametros_cadastrados"] == 3


def test_listar_parametros_traz_unidade_e_faixa_com_null_sem_limite(registro):
    parametros = {p["codigo"]: p for p in executar(registro, "listar_parametros").dados["parametros"]}

    assert parametros["TIP-PH"] == {"codigo": "TIP-PH", "nome": "pH", "unidade": "pH", "faixa_minima": 0.0, "faixa_maxima": 14.0}
    assert parametros["TIP-CHU"]["faixa_maxima"] is None


# --- resumo_estatistico -------------------------------------------------------


def test_resumo_estatistico_confere_com_calculo_independente(registro, junho):
    valores = [7.0] * 71 + [7.2] * 72 + [9.9]  # ver conftest: o pico substitui um 7.0

    resultado = executar(registro, "resumo_estatistico", parametros=["TIP-PH"], **junho)

    linha = resultado.dados["linhas"][0]
    assert resultado.sucesso and len(resultado.dados["linhas"]) == 1
    assert (linha["codigo"], linha["unidade"], linha["quantidade"]) == ("TIP-PH", "pH", 144)
    assert linha["media"] == round(statistics.mean(valores), 3)
    assert linha["mediana"] == round(statistics.median(valores), 3)
    assert linha["desvio_padrao"] == round(statistics.stdev(valores), 3)
    assert (linha["minimo"], linha["maximo"], linha["anomalias"]) == (7.0, 9.9, 1)
    assert resultado.dados["filtros"] == {"estacao": None, "data_inicio": "2026-06-01", "data_fim": "2026-06-03", "parametros": ["TIP-PH"]}


def test_resumo_sem_parametros_traz_todos(registro, junho):
    linhas = executar(registro, "resumo_estatistico", **junho).dados["linhas"]

    assert [l["codigo"] for l in linhas] == ["TIP-CHU", "TIP-PH", "TIP-TMP"]


def test_recorte_vazio_nao_e_erro_e_traz_a_cobertura(registro):
    resultado = executar(registro, "resumo_estatistico", data_inicio="2025-01-01")

    assert resultado.sucesso
    assert resultado.dados["linhas"] == []
    assert resultado.dados["aviso"] == "sem medições no recorte"
    assert resultado.dados["cobertura"][0]["estacao_codigo"] == "EST-1"


# --- Validação (POL-06) e regras ----------------------------------------------


@pytest.mark.parametrize(
    "nome, argumentos, trecho",
    [
        ("resumo_estatistico", {"data_inicio": "2026-06-30", "data_fim": "2026-06-01"}, "data_fim anterior a data_inicio"),
        ("resumo_estatistico", {"data_fim": "2026-06-01"}, "data_fim exige data_inicio"),
        ("resumo_estatistico", {"apagar_tudo": True}, "apagar_tudo: Extra inputs are not permitted"),
        ("serie_temporal", {"parametro": "TIP-PH", "data_inicio": "2026-06-01", "data_fim": "2026-06-03", "granularidade": "ano"}, "granularidade"),
        ("listar_anomalias", {"limite": 500}, "limite"),
        ("listar_anomalias", {"alerta": "OUTRO"}, "alerta"),
        ("resumo_estatistico", {"estacao": "est-1; DROP TABLE"}, "estacao"),
        ("panorama_dados", {"qualquer": 1}, "Extra inputs are not permitted"),
    ],
)
def test_argumento_invalido_vira_erro_para_o_llm(registro, nome, argumentos, trecho):
    resultado = executar(registro, nome, **argumentos)

    assert not resultado.sucesso
    assert resultado.erro.startswith("argumentos inválidos:")
    assert trecho in resultado.erro


def test_parametro_inexistente_sugere_listar_parametros(registro):
    resultado = executar(registro, "resumo_estatistico", parametros=["TIP-XYZ"])

    assert not resultado.sucesso
    assert resultado.erro == "parâmetro inexistente: TIP-XYZ. Use listar_parametros para ver os códigos"


def test_estacao_inexistente_lista_as_cadastradas(registro):
    resultado = executar(registro, "resumo_estatistico", estacao="EST-9")

    assert resultado.erro == "estação inexistente: EST-9. Estações cadastradas: EST-1"


def test_ferramenta_desconhecida(registro):
    resultado = executar(registro, "executar_sql", sql="DELETE FROM dbo.Leituras")

    assert not resultado.sucesso
    assert resultado.erro.startswith("ferramenta desconhecida: executar_sql.")


# --- listar_anomalias ---------------------------------------------------------


def test_anomalias_trazem_o_pico_com_total_e_alerta(registro, junho):
    resultado = executar(registro, "listar_anomalias", parametro="TIP-PH", **junho)

    item = resultado.dados["itens"][0]
    assert (resultado.dados["total"], resultado.dados["por_alerta"]) == (1, {"IQR+ZSCORE": 1})
    assert (item["data_hora"], item["valor"], item["codigo"], item["alerta"]) == (PICO_PH.isoformat(), 9.9, "TIP-PH", "IQR+ZSCORE")
    assert item["zscore"] > 3
    assert resultado.dados["base_calculo"] == "limites IQR e Z-Score calculados sobre o recorte pedido"


def test_filtro_de_alerta_e_limite(registro, junho):
    so_zscore = executar(registro, "listar_anomalias", alerta="ZSCORE", **junho).dados
    limitado = executar(registro, "listar_anomalias", limite=1, **junho).dados

    assert (so_zscore["total"], so_zscore["itens"], so_zscore["por_alerta"]) == (0, [], {"IQR+ZSCORE": 1})
    assert len(limitado["itens"]) == 1


# --- serie_temporal -----------------------------------------------------------


def test_serie_diaria_confere_com_calculo_independente(registro, junho):
    resultado = executar(registro, "serie_temporal", parametro="TIP-PH", granularidade="dia", **junho)

    pontos = resultado.dados["pontos"]
    assert resultado.dados["unidade"] == "pH"
    assert [p["inicio"] for p in pontos] == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert [p["n"] for p in pontos] == [48, 48, 48]
    assert pontos[1]["valor"] == round((23 * 7.0 + 24 * 7.2 + 9.9) / 48, 3)


def test_serie_semanal_comeca_na_segunda_feira(registro, junho):
    pontos = executar(registro, "serie_temporal", parametro="TIP-TMP", granularidade="semana", estatistica="maximo", **junho).dados["pontos"]

    assert date(2026, 6, 1).weekday() == 0  # 01/06/2026 é segunda-feira
    assert pontos == [{"inicio": "2026-06-01", "valor": 32.0, "n": 144}]


def test_serie_horaria_usa_o_limite_proprio_e_nao_o_de_linhas(registro, junho):
    """serie_temporal tem limite de 200 pontos; os 72 pontos não são cortados pelo limite de 50 linhas."""
    resultado = executar(registro, "serie_temporal", parametro="TIP-PH", granularidade="hora", **junho)

    assert len(resultado.dados["pontos"]) == 72
    assert "truncado" not in resultado.dados


def test_serie_grande_demais_e_recusada_antes_de_consultar_o_banco():
    consulta, leituras = montar_consulta()
    registro = criar_registro(consulta)

    resultado = executar(registro, "serie_temporal", parametro="TIP-PH", granularidade="hora", data_inicio="2026-06-01", data_fim="2026-06-09")

    assert resultado.erro == "a série teria até 216 pontos (máximo 200); use uma granularidade maior"
    assert leituras.chamadas == 0


# --- perfil_horario -----------------------------------------------------------


def test_perfil_horario_acha_o_pico_do_meio_dia(registro, junho):
    resultado = executar(registro, "perfil_horario", parametro="TIP-TMP", **junho).dados

    assert (resultado["hora_maior_media"], resultado["hora_menor_media"]) == (12, 0)
    assert len(resultado["horas"]) == 24
    assert resultado["horas"][12] == {"hora": 12, "media": 32.0, "mediana": 32.0, "n": 6}


def test_serie_e_perfil_exigem_estacao_quando_ha_varias():
    registro = criar_registro(montar_consulta(n_estacoes=2)[0])

    sem_estacao = executar(registro, "perfil_horario", parametro="TIP-TMP")
    com_estacao = executar(registro, "perfil_horario", parametro="TIP-TMP", estacao="EST-2")

    assert sem_estacao.erro == "há 2 estações (EST-1, EST-2); informe o argumento estacao"
    assert com_estacao.sucesso


# --- Registro: truncamento e erro inesperado ----------------------------------


def test_listas_acima_do_limite_sao_cortadas_com_total(consulta):
    resultado = executar(criar_registro(consulta, max_linhas=2), "listar_parametros")

    assert len(resultado.dados["parametros"]) == 2
    assert (resultado.dados["truncado"], resultado.dados["total_parametros"]) == (True, 3)


def test_erro_inesperado_vira_mensagem_generica_e_log_sem_detalhe(caplog):
    consulta, leituras = montar_consulta()

    def falhar(**_):
        """Simula o banco fora do ar, com detalhe sensível na mensagem."""
        raise RuntimeError("Login failed; PWD=segredo-do-banco")

    leituras.get_medicoes = falhar
    with caplog.at_level(logging.ERROR):
        resultado = executar(criar_registro(consulta), "resumo_estatistico")

    assert resultado.erro == ERRO_INESPERADO
    assert "erro=RuntimeError" in caplog.text
    assert "segredo-do-banco" not in caplog.text + resultado.erro  # POL-10


def test_registrar_nome_repetido_falha(consulta):
    registro = criar_registro(consulta)

    with pytest.raises(ValueError, match="já registrada: panorama_dados"):
        registro.registrar(criar_ferramentas_descritivas(consulta)[0])


# --- ConsultaDados: cache -----------------------------------------------------


class RelogioFalso:
    """Relógio controlado pelo teste."""

    def __init__(self) -> None:
        """Começa no instante zero."""
        self.agora = 0.0

    def __call__(self) -> float:
        """Instante atual, em segundos."""
        return self.agora


def test_mesmo_recorte_consulta_o_banco_uma_vez_dentro_do_ttl():
    relogio = RelogioFalso()
    consulta, leituras = montar_consulta(relogio=relogio)
    filtro = FiltroMedicoes(parametros=("TIP-PH",))

    consulta.medicoes(filtro)
    consulta.medicoes(filtro)
    relogio.agora = 301  # passou o TTL de 300 s
    consulta.medicoes(filtro)

    assert leituras.chamadas == 2


def test_cache_guarda_poucos_recortes():
    consulta, leituras = montar_consulta()

    for dia in range(1, MAXIMO_RECORTES_EM_CACHE + 2):
        consulta.medicoes(FiltroMedicoes(data_inicio=date(2026, 6, dia)))
    consulta.medicoes(FiltroMedicoes(data_inicio=date(2026, 6, 1)))  # o mais antigo saiu do cache

    assert leituras.chamadas == MAXIMO_RECORTES_EM_CACHE + 2


def test_limpar_cache(consulta):
    consulta.medicoes(FiltroMedicoes())
    consulta.limpar_cache()
    consulta.medicoes(FiltroMedicoes())


# --- Funções de apoio e repositório -------------------------------------------


def test_normalizar_json_converte_numpy_e_nan():
    dados = {"n": np.int64(3), "media": np.float64(7.12345), "vazio": float("inf"), "quando": date(2026, 6, 1)}

    assert normalizar_json(dados) == {"n": 3, "media": 7.123, "vazio": None, "quando": "2026-06-01"}


def test_get_cobertura_agrega_no_banco():
    class BancoFalso:
        """Devolve uma linha como o SQL agregado e guarda a consulta recebida."""

        def fetch_all(self, query, params=None):
            """Resultado de MIN/MAX/COUNT por estação."""
            self.query = query
            return [("EST-RJ-001", datetime(2026, 4, 1), datetime(2026, 10, 23, 23, 30), 9806)]

    banco = BancoFalso()

    cobertura = LeituraRepository(banco).get_cobertura()

    assert cobertura == [{"estacao_codigo": "EST-RJ-001", "primeira_leitura": datetime(2026, 4, 1),
                          "ultima_leitura": datetime(2026, 10, 23, 23, 30), "leituras": 9806}]
    assert "COUNT(*)" in banco.query and "GROUP BY" in banco.query
