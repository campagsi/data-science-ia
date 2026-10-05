import pytest

import src.logger as log
from src.models import ParametroModel
from src.repository.parametro_repository import ParametroRepository
from src.services.normalization_service import NormalizationService
from src.services.parametro_service import ParametroService
from src.services.validation_service import ValidationService


class ParametroRepositoryEmMemoria:
    """Imita a tabela Parametros: IDENTITY e INSERT que ignora código existente."""

    def __init__(self, *parametros):
        self.linhas = {}
        self.insercoes = 0
        self.create_many(list(parametros))
        self.insercoes = 0

    def get_all(self):
        return [p.model_copy() for p in sorted(self.linhas.values(), key=lambda p: p.codigo_parametro)]

    def create_many(self, parametros):
        for parametro in parametros:
            if parametro.codigo_parametro not in self.linhas:
                self.linhas[parametro.codigo_parametro] = parametro.model_copy(
                    update={"id_parametro": len(self.linhas) + 1}
                )
                self.insercoes += 1
        return len(parametros)


PH = ParametroModel(codigo_parametro="TIP-PH", nome="pH", unidade_medida="pH", valor_minimo=0, valor_maximo=14)
UMIDADE = ParametroModel(codigo_parametro="TIP-UMI", nome="Umidade relativa do ar", unidade_medida="%",
                         valor_minimo=0, valor_maximo=100)


@pytest.fixture(autouse=True)
def _ambiente(seguranca, logs_temporarios):
    """Rejeições e cadastros são registrados nos logs temporários."""


@pytest.fixture
def repositorio():
    return ParametroRepositoryEmMemoria(PH, UMIDADE)


def _descoberto(campo, unidade):
    return {"campo": campo, "unidade_medida": unidade}


def test_parametros_ja_cadastrados_nao_sao_inseridos_de_novo(repositorio):
    aceitos = ParametroService(repositorio).sincronizar(
        {"TIP-PH": _descoberto("ph", "pH"), "TIP-UMI": _descoberto("umidade", "%")}
    )

    assert set(aceitos) == {"TIP-PH", "TIP-UMI"}
    assert repositorio.insercoes == 0
    assert aceitos["TIP-PH"].id_parametro == 1


def test_parametro_novo_e_cadastrado_sem_faixa(repositorio, logs_temporarios):
    aceitos = ParametroService(repositorio).sincronizar({"TIP-SAL": _descoberto("salinidade", "PSU")})

    novo = aceitos["TIP-SAL"]
    assert (novo.nome, novo.unidade_medida, novo.valor_minimo, novo.valor_maximo) == (
        "Salinidade", "PSU", None, None,
    )
    assert novo.id_parametro == 3
    assert set(aceitos) == {"TIP-PH", "TIP-UMI", "TIP-SAL"}
    assert any(
        "[INFO] - Novo parâmetro cadastrado: TIP-SAL (Salinidade, PSU), sem faixa de valores." in linha
        for linha in logs_temporarios("pipeline")
    )


def test_aceite_fase_7_segunda_execucao_nao_cadastra_de_novo(repositorio):
    descobertos = {"TIP-SAL": _descoberto("salinidade", "PSU")}

    ParametroService(repositorio).sincronizar(descobertos)
    ParametroService(repositorio).sincronizar(descobertos)

    assert repositorio.insercoes == 1
    assert len(repositorio.linhas) == 3


@pytest.mark.parametrize(
    ("codigo", "descoberto", "motivo"),
    [
        ("TIP-SAL", _descoberto("salinidade", None), "unidade de medida ausente"),
        ("TIP-PH2", _descoberto("ph", "pH"), "nome Ph já cadastrado para o código TIP-PH"),
        ("TIP-PH", _descoberto("ph", "mol/L"), "unidade mol/L diferente da cadastrada (pH)"),
        ("TIP-" + "X" * 60, _descoberto("x", "u"), "código, nome ou unidade acima do tamanho permitido"),
    ],
)
def test_parametro_que_nao_pode_ser_usado_e_rejeitado_com_error(
    repositorio, logs_temporarios, codigo, descoberto, motivo
):
    aceitos = ParametroService(repositorio).sincronizar({codigo: descoberto})

    assert codigo not in aceitos
    assert repositorio.insercoes == 0
    linha = logs_temporarios("rejeitados")[0]
    assert "[ERROR] - etapa=parametro nivel=parametro" in linha
    assert f'motivo="{motivo}"' in linha


def test_unidade_com_maiusculas_diferentes_e_a_mesma_unidade(repositorio):
    aceitos = ParametroService(repositorio).sincronizar({"TIP-PH": _descoberto("ph", "PH")})

    assert "TIP-PH" in aceitos


def test_dois_codigos_novos_com_o_mesmo_nome_no_lote(repositorio):
    aceitos = ParametroService(repositorio).sincronizar(
        {"TIP-SAL": _descoberto("salinidade", "PSU"), "TIP-SAL2": _descoberto("salinidade", "g/kg")}
    )

    assert "TIP-SAL" in aceitos
    assert "TIP-SAL2" not in aceitos


def test_faixas_no_formato_da_validacao(repositorio):
    aceitos = ParametroService(repositorio).sincronizar({})

    assert ParametroService.faixas(aceitos) == {"TIP-PH": (0.0, 14.0), "TIP-UMI": (0.0, 100.0)}


def test_medicoes_de_parametro_rejeitado_sao_descartadas_na_validacao(repositorio, registro_bruto):
    registro_bruto.update(salinidade=35.1, salinidade_tipo_codigo="TIP-SAL")  # sem unidade
    normalizados = NormalizationService().normalize([registro_bruto])
    aceitos = ParametroService(repositorio).sincronizar(
        NormalizationService.descobrir_parametros(normalizados)
    )

    resultado = ValidationService(
        faixas=ParametroService.faixas(aceitos), parametros_validos=set(aceitos)
    ).validate_data(normalizados)[0]

    invalidos = {item["campo"]: item for item in resultado["itens_invalidos"]}
    assert invalidos["salinidade"]["etapa"] == "parametro"
    # TIP-PH e TIP-UMI estão no repositório de teste; os outros 9 do payload são
    # cadastrados como novos, então as medições deles seguem válidas.
    assert "salinidade" not in {item["campo"] for item in resultado["registro"]["itens"]}
    assert "ph" in {item["campo"] for item in resultado["registro"]["itens"]}
    assert log.contar_rejeicoes()["parametro"] == 1


def test_repositorio_insere_sem_duplicar_codigo():
    executados = []

    class DatabaseFalso:
        def execute_many(self, sql, params):
            executados.append((sql, params))
            return len(params)

    ParametroRepository(DatabaseFalso()).create_many([PH])

    sql, params = executados[0]
    assert "WHERE NOT EXISTS" in sql
    assert params == [("TIP-PH", "pH", "pH", 0.0, 14.0, "TIP-PH")]
