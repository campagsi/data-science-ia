from datetime import datetime

import pytest

import src.logger as log
from src.security import descriptografar_email
from src.services.normalization_service import NormalizationService

CAMPOS_PESSOAIS = ("operador_cpf", "operador_nome_completo", "operador_email")


@pytest.fixture(autouse=True)
def _ambiente(seguranca, logs_temporarios):
    """Toda normalização anonimiza e pode registrar rejeições."""


def _normalizar(*registros):
    return NormalizationService().normalize(list(registros))


def _item(registro, campo):
    return next(item for item in registro["itens"] if item["campo"] == campo)


def test_normalize_monta_cabecalho_com_tipos_convertidos(registro_bruto):
    registro_bruto["cidade_estado"] = " rj "
    registro_bruto["estacao_latitude"] = "-22.8768"

    registro = _normalizar(registro_bruto)[0]

    assert registro["registro_codigo"] == "REG-RJ-001-00001"
    assert registro["cidade_estado"] == "RJ"
    assert registro["municipio"] == "Rio de Janeiro"
    assert registro["estacao_codigo"] == "EST-RJ-001"
    assert registro["estacao_latitude"] == -22.8768
    assert registro["operador_codigo"] == "OP-RJ-001"
    assert registro["data_hora_ciclo"] == datetime(2026, 4, 1, 0, 0)


def test_normalize_usa_cidade_nome_quando_municipio_e_nulo(registro_bruto):
    registro_bruto["municipio"] = None

    assert _normalizar(registro_bruto)[0]["municipio"] == "Rio de Janeiro"


def test_normalize_gera_um_item_por_parametro_com_codigo_e_unidade(registro_bruto):
    itens = {item["campo"]: item for item in _normalizar(registro_bruto)[0]["itens"]}

    assert len(itens) == 11
    assert itens["ph"]["codigo_parametro"] == "TIP-PH"
    assert itens["ph"]["valor"] == 7.53
    assert itens["temperatura_agua"]["unidade_medida"] == "°C"
    assert itens["ph"]["data_hora_leitura"] == datetime(2026, 4, 1, 0, 2, 10)


@pytest.mark.parametrize(
    ("campo", "unidade"),
    [("oxigenio_dissolvido", "mg/L"), ("velocidade_vento", "km/h")],
)
def test_normalize_resolve_nomes_de_unidade_fora_do_padrao(registro_bruto, campo, unidade):
    assert _item(_normalizar(registro_bruto)[0], campo)["unidade_medida"] == unidade


def test_normalize_anonimiza_operador_e_remove_os_dados_originais(registro_bruto):
    registro = _normalizar(registro_bruto)[0]

    for campo in CAMPOS_PESSOAIS:
        assert campo not in registro
    assert len(registro["cpf_hash"]) == 64
    assert len(registro["nome_hash"]) == 64
    assert descriptografar_email(registro["email_criptografado"]) == registro_bruto["operador_email"]
    texto = str(registro)
    assert registro_bruto["operador_cpf"] not in texto
    assert registro_bruto["operador_nome_completo"] not in texto


def test_normalize_nao_altera_payload_original(registro_bruto):
    original = dict(registro_bruto)

    _normalizar(registro_bruto)

    assert registro_bruto == original


def test_normalize_converte_texto_vazio_para_none(registro_bruto):
    registro_bruto["estacao_codigo"] = "   "
    registro_bruto["turbidez"] = "  "

    registro = _normalizar(registro_bruto)[0]

    assert registro["estacao_codigo"] is None
    assert _item(registro, "turbidez")["valor"] is None


def test_medicao_nula_continua_como_item_para_a_completude(registro_bruto):
    registro_bruto["ph"] = None

    assert _item(_normalizar(registro_bruto)[0], "ph")["valor"] is None
    assert log.contar_rejeicoes() == {}


def test_medicao_nao_numerica_rejeita_so_o_item(registro_bruto, logs_temporarios):
    registro_bruto["ph"] = "sete"

    registro = _normalizar(registro_bruto)[0]

    assert len(registro["itens"]) == 10
    assert "ph" not in {item["campo"] for item in registro["itens"]}
    rejeitados = logs_temporarios("rejeitados")
    assert len(rejeitados) == 1
    assert (
        'etapa=normalizacao nivel=item registro=REG-RJ-001-00001 campo=ph valor=sete '
        'motivo="medição não numérica"'
    ) in rejeitados[0]


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("data_hora_ciclo", "01/04/2026", "data/hora não está no formato ISO"),
        ("estacao_latitude", "norte", "coordenada não numérica"),
    ],
)
def test_valor_invalido_no_cabecalho_rejeita_so_a_leitura(
    registro_bruto, logs_temporarios, campo, valor, motivo
):
    invalido = dict(registro_bruto, **{campo: valor})
    valido = dict(registro_bruto, registro_codigo="REG-OK")

    normalizados = _normalizar(invalido, valido)

    assert [r["registro_codigo"] for r in normalizados] == ["REG-OK"]
    linha = logs_temporarios("rejeitados")[0]
    assert f"nivel=leitura registro=REG-RJ-001-00001 campo={campo}" in linha
    assert f'motivo="{motivo}"' in linha


def test_registro_que_nao_e_objeto_e_rejeitado_sem_parar_o_lote(registro_bruto, logs_temporarios):
    normalizados = _normalizar(registro_bruto, "x")

    assert len(normalizados) == 1
    assert 'campo=registro motivo="registro 1 não é um objeto JSON"' in logs_temporarios("rejeitados")[0]


def test_normalize_rejeita_payload_que_nao_e_lista():
    with pytest.raises(ValueError, match="lista"):
        NormalizationService().normalize({"registro_codigo": "x"})


def test_normalize_ordena_por_data_hora_do_ciclo(registro_bruto):
    tarde = dict(registro_bruto, registro_codigo="B", data_hora_ciclo="2026-04-01T12:00:00")
    cedo = dict(registro_bruto, registro_codigo="A", data_hora_ciclo="2026-04-01T06:00:00")
    sem_data = dict(registro_bruto, registro_codigo="C", data_hora_ciclo=None)

    ordem = [r["registro_codigo"] for r in _normalizar(sem_data, tarde, cedo)]

    assert ordem == ["A", "B", "C"]


def test_parametro_novo_e_descoberto_pelo_tipo_codigo(registro_bruto):
    registro_bruto.update(
        salinidade="35.1",
        salinidade_unidade_medida="PSU",
        salinidade_tipo_codigo="TIP-SAL",
    )

    normalizados = _normalizar(registro_bruto)
    parametros = NormalizationService.descobrir_parametros(normalizados)

    assert _item(normalizados[0], "salinidade")["valor"] == 35.1
    assert parametros["TIP-SAL"] == {"campo": "salinidade", "unidade_medida": "PSU"}


def test_parametro_sem_unidade_fica_com_unidade_none(registro_bruto):
    registro_bruto.update(salinidade=35.1, salinidade_tipo_codigo="TIP-SAL")

    parametros = NormalizationService.descobrir_parametros(_normalizar(registro_bruto))

    assert parametros["TIP-SAL"]["unidade_medida"] is None


def test_parametro_sem_codigo_rejeita_o_item(registro_bruto, logs_temporarios):
    registro_bruto["ph_tipo_codigo"] = None

    registro = _normalizar(registro_bruto)[0]

    assert "ph" not in {item["campo"] for item in registro["itens"]}
    assert 'campo=ph motivo="código do parâmetro ausente"' in logs_temporarios("rejeitados")[0]


def test_campos_descartados_sao_informados_no_log(registro_bruto, logs_temporarios):
    _normalizar(registro_bruto)

    linha = next(l for l in logs_temporarios("pipeline") if "descartados" in l)
    for campo in ("cidade_codigo", "estacao_ativa", "estacao_tipo", "operador_ativo", "ph_codigo"):
        assert campo in linha
    for campo in CAMPOS_PESSOAIS:
        assert campo not in linha


def test_aceite_fase_4_dataset_completo(dataset):
    """Todo o dataset normaliza sem exceção, com 11 parâmetros e sem dados pessoais em claro."""

    normalizados = NormalizationService().normalize(dataset)

    assert len(normalizados) == len(dataset)
    assert len(NormalizationService.descobrir_parametros(normalizados)) == 11
    assert all(campo not in r for r in normalizados for campo in CAMPOS_PESSOAIS)
    datas = [r["data_hora_ciclo"] for r in normalizados]
    assert datas == sorted(datas)
    assert log.contar_rejeicoes() == {}
