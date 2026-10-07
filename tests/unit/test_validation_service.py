import pytest

from src.services.normalization_service import NormalizationService
from src.services.validation_service import ValidationService

FAIXAS = {"TIP-PH": (0, 14), "TIP-UMI": (0, 100), "TIP-CHU": (0, None)}


@pytest.fixture(autouse=True)
def _ambiente(seguranca, logs_temporarios):
    """A normalização usada para montar os registros anonimiza e pode logar."""


@pytest.fixture
def registro_bruto(registro_bruto):
    """O 1º registro do dataset vem com pressão nula; aqui ele fica completo."""
    registro_bruto["pressao"] = 1013.2
    return registro_bruto


@pytest.fixture
def normalizar():
    def _normalizar(*registros):
        return NormalizationService().normalize(list(registros))

    return _normalizar


@pytest.fixture
def validar():
    def _validar(normalizados, **kwargs):
        return ValidationService(**{"faixas": FAIXAS, **kwargs}).validate_data(normalizados)

    return _validar


def _itens_invalidos(resultado):
    return {item["campo"]: item for item in resultado["itens_invalidos"]}


def test_registro_completo_e_valido(registro_bruto, normalizar, validar):
    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is True
    assert resultado["registro_codigo"] == "REG-RJ-001-00001"
    assert resultado["campos_nulos"] == []
    assert resultado["motivos"] == []
    assert len(resultado["registro"]["itens"]) == 11


def test_devolve_um_resultado_por_registro_na_mesma_ordem(registro_bruto, normalizar, validar):
    outro = dict(registro_bruto, registro_codigo="REG-2", data_hora_ciclo="2026-04-01T00:30:00")

    resultados = validar(normalizar(registro_bruto, outro))

    assert [r["registro_codigo"] for r in resultados] == ["REG-RJ-001-00001", "REG-2"]


def test_campos_nulos_lista_todos_os_campos_que_faltaram(registro_bruto, normalizar, validar):
    for campo in ("estacao_codigo", "operador_codigo", "operador_cpf"):
        registro_bruto[campo] = None

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is False
    assert resultado["campos_nulos"] == ["estacao_codigo", "operador_codigo", "cpf_hash"]
    assert resultado["motivos"] == [
        {
            "etapa": "completude",
            "campo": "estacao_codigo,operador_codigo,cpf_hash",
            "motivo": "campo vital nulo",
            "valor": None,
        }
    ]


@pytest.mark.parametrize(
    "campo",
    ["registro_codigo", "data_hora_ciclo", "cidade_estado", "estacao_latitude", "operador_email"],
)
def test_qualquer_campo_vital_nulo_invalida_o_registro(registro_bruto, normalizar, validar, campo):
    registro_bruto[campo] = None

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is False
    assert resultado["campos_nulos"]


def test_municipio_nulo_com_cidade_nome_preenchida_continua_valido(registro_bruto, normalizar, validar):
    registro_bruto["municipio"] = None

    assert validar(normalizar(registro_bruto))[0]["valido"] is True


def test_medicao_nula_descarta_so_o_item(registro_bruto, normalizar, validar):
    registro_bruto["ph"] = None

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is True
    assert _itens_invalidos(resultado)["ph"] == {
        "etapa": "completude", "campo": "ph", "motivo": "medição nula", "valor": None,
    }
    assert "ph" not in {item["campo"] for item in resultado["registro"]["itens"]}
    assert len(resultado["registro"]["itens"]) == 10


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("ph", 17.0, "fora da faixa 0 a 14"),
        ("ph", -2.0, "fora da faixa 0 a 14"),
        ("umidade", 145.0, "fora da faixa 0 a 100"),
        ("precipitacao", -8.0, "fora da faixa 0 a sem limite"),
    ],
)
def test_valor_fora_da_faixa_descarta_so_o_item(registro_bruto, normalizar, validar, campo, valor, motivo):
    registro_bruto[campo] = valor

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is True
    assert _itens_invalidos(resultado)[campo] == {
        "etapa": "acuracia", "campo": campo, "motivo": motivo, "valor": valor,
    }


def test_limites_da_faixa_sao_aceitos(registro_bruto, normalizar, validar):
    registro_bruto.update(ph=14, umidade=0, precipitacao=110)

    assert validar(normalizar(registro_bruto))[0]["itens_invalidos"] == []


def test_parametro_sem_faixa_nao_tem_conferencia_de_acuracia(registro_bruto, normalizar):
    registro_bruto["ph"] = 99

    resultado = ValidationService().validate_data(normalizar(registro_bruto))[0]

    assert resultado["itens_invalidos"] == []


def test_registro_sem_nenhuma_medicao_valida_e_invalido(registro_bruto, normalizar, validar):
    for chave in [c for c in registro_bruto if c.endswith("_tipo_codigo")]:
        registro_bruto[chave.removesuffix("_tipo_codigo")] = None

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is False
    assert resultado["campos_nulos"] == []
    assert resultado["motivos"][0]["motivo"] == "leitura sem medições válidas"
    assert len(resultado["itens_invalidos"]) == 11


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("estacao_latitude", -91.0), ("estacao_longitude", 181.0)],
)
def test_coordenada_fora_da_faixa_invalida_o_registro(registro_bruto, normalizar, validar, campo, valor):
    registro_bruto[campo] = valor

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["valido"] is False
    assert resultado["motivos"][0]["etapa"] == "acuracia"
    assert resultado["motivos"][0]["campo"] == campo


def test_estado_nao_cadastrado_invalida_o_registro(registro_bruto, normalizar, validar):
    resultado = validar(normalizar(registro_bruto), siglas_estados={"SP"})[0]

    assert resultado["valido"] is False
    assert resultado["motivos"][0] == {
        "etapa": "referencia", "campo": "cidade_estado",
        "motivo": "estado não cadastrado em Estados", "valor": "RJ",
    }


def test_sigla_com_formato_invalido_invalida_o_registro(registro_bruto, normalizar, validar):
    registro_bruto["cidade_estado"] = "R1"

    resultado = validar(normalizar(registro_bruto))[0]

    assert resultado["motivos"][0]["etapa"] == "validade"


def test_registro_repetido_mantem_so_a_primeira_ocorrencia(registro_bruto, normalizar, validar):
    resultados = validar(normalizar(registro_bruto, dict(registro_bruto)))

    assert [r["valido"] for r in resultados] == [True, False]
    assert resultados[1]["motivos"][0]["etapa"] == "unicidade"
    assert resultados[1]["motivos"][0]["campo"] == "registro_codigo"


@pytest.mark.parametrize(
    ("campo_alterado", "valor", "campo_codigo"),
    [
        ("estacao_nome", "Outra estação", "estacao_codigo"),
        ("operador_cpf", "11122233344", "operador_codigo"),
    ],
)
def test_codigo_com_dados_cadastrais_diferentes_no_lote_e_invalido(
    registro_bruto, normalizar, validar, campo_alterado, valor, campo_codigo
):
    conflito = dict(
        registro_bruto,
        registro_codigo="REG-2",
        data_hora_ciclo="2026-04-01T00:30:00",
        **{campo_alterado: valor},
    )

    resultados = validar(normalizar(registro_bruto, conflito))

    assert [r["valido"] for r in resultados] == [True, False]
    assert resultados[1]["motivos"][0]["campo"] == campo_codigo


def test_registros_validos_devolve_so_os_registros_aprovados(registro_bruto, normalizar, validar):
    invalido = dict(registro_bruto, registro_codigo="REG-2", estacao_codigo=None)

    resultados = validar(normalizar(registro_bruto, invalido))

    assert [r["registro_codigo"] for r in ValidationService.registros_validos(resultados)] == [
        "REG-RJ-001-00001"
    ]


def test_validacao_nao_altera_o_registro_normalizado(registro_bruto, normalizar, validar):
    registro_bruto["ph"] = None
    normalizados = normalizar(registro_bruto)

    validar(normalizados)

    assert len(normalizados[0]["itens"]) == 11


def test_resultado_nao_carrega_dado_pessoal_em_claro(registro_bruto, normalizar, validar):
    texto = str(validar(normalizar(registro_bruto)))

    for campo in ("operador_cpf", "operador_nome_completo", "operador_email"):
        assert registro_bruto[campo] not in texto
