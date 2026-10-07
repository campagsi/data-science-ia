"""Coerência dos scripts SQL com o payload da API, sem precisar de banco."""
import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DML = (RAIZ / "sql" / "dml_populacao.sql").read_text(encoding="utf-8-sig")
DDL = (RAIZ / "sql" / "ddl_banco_relacional.sql").read_text(encoding="utf-8-sig")

ESTADOS = dict(re.findall(r"\('([A-Z]{2})',\s*N'([^']+)'\)", DML))
PARAMETROS = {
    codigo: {"nome": nome, "unidade": unidade, "minimo": minimo, "maximo": maximo}
    for codigo, nome, unidade, minimo, maximo in re.findall(
        r"\('(TIP-[A-Z]+)',\s*N'([^']+)',\s*N'([^']+)',\s*(-?\d+|NULL),\s*(-?\d+|NULL)\)", DML
    )
}

# Nomes de unidade fora do padrão <param>_unidade_medida no payload.
UNIDADE_ALTERNATIVA = {
    "oxigenio_dissolvido": "oxigenio_dissolvido_medida",
    "velocidade_vento": "velocidade_unidade_medida",
}


@pytest.fixture(scope="module")
def dataset():
    return json.loads((RAIZ / "src" / "api" / "data_set.json").read_text(encoding="utf-8"))


def test_dml_cadastra_as_27_unidades_federativas():
    assert len(ESTADOS) == 27
    assert len(set(ESTADOS.values())) == 27
    assert ESTADOS["SP"] == "São Paulo"


def test_dml_cobre_os_estados_do_dataset(dataset):
    siglas = {registro["cidade_estado"] for registro in dataset if registro.get("cidade_estado")}

    assert siglas <= ESTADOS.keys()


def test_dml_cadastra_todos_os_parametros_do_dataset_com_a_mesma_unidade(dataset):
    """
    Percorre todos os registros: um parâmetro novo no data_set.json faz este
    teste falhar, lembrando de incluí-lo no DML com nome legível e faixa.
    Na ingestão, um parâmetro fora do DML não bloqueia a carga: é cadastrado
    automaticamente (fase 7 do TODO).
    """
    encontrados = {
        (campo.removesuffix("_tipo_codigo"), valor)
        for registro in dataset
        for campo, valor in registro.items()
        if campo.endswith("_tipo_codigo") and valor is not None
    }

    assert len(encontrados) == 11
    for nome_campo, codigo in encontrados:
        assert codigo in PARAMETROS, f"{codigo} ({nome_campo}) não está no dml_populacao.sql"
        campo_unidade = UNIDADE_ALTERNATIVA.get(nome_campo, f"{nome_campo}_unidade_medida")
        unidades = {r.get(campo_unidade) for r in dataset if r.get(campo_unidade)}
        assert unidades == {PARAMETROS[codigo]["unidade"]}, codigo


def test_dml_tem_nomes_de_parametro_unicos_e_faixas_coerentes():
    nomes = [p["nome"] for p in PARAMETROS.values()]
    assert len(nomes) == len(set(nomes))  # UQ_Parametros_Nome

    for codigo, parametro in PARAMETROS.items():
        if "NULL" not in (parametro["minimo"], parametro["maximo"]):
            assert int(parametro["minimo"]) < int(parametro["maximo"]), codigo


def test_ph_respeita_a_faixa_do_enunciado():
    assert (PARAMETROS["TIP-PH"]["minimo"], PARAMETROS["TIP-PH"]["maximo"]) == ("0", "14")


def test_dml_e_idempotente_por_merge():
    assert "INSERT INTO" not in DML.upper().replace("WHEN NOT MATCHED BY TARGET THEN\n    INSERT", "")
    assert DML.upper().count("MERGE DBO.") == 2


def test_ddl_remove_tabelas_filhas_antes_das_maes():
    ordem = re.findall(r"DROP TABLE IF EXISTS dbo\.(\w+);", DDL)

    assert ordem.index("Leitura_Itens") < ordem.index("Leituras")
    assert ordem.index("Leituras") < ordem.index("Estacoes") < ordem.index("Municipios")
    assert ordem.index("Leituras") < ordem.index("Operadores") < ordem.index("Municipios")
    assert ordem.index("Municipios") < ordem.index("Estados")
