from dataclasses import FrozenInstanceError

import pytest

from src.agente.contratos import (
    ChamadaFerramenta,
    Fonte,
    Mensagem,
    RespostaAgente,
    ResultadoFerramenta,
    formatar_chamada,
)


def chamada(nome: str = "resumo_estatistico", **argumentos) -> ChamadaFerramenta:
    return ChamadaFerramenta("c1", nome, argumentos)


def test_contratos_sao_imutaveis():
    with pytest.raises(FrozenInstanceError):
        chamada().id = "c2"
    with pytest.raises(FrozenInstanceError):
        Mensagem.usuario("pH?").texto = "outro"
    with pytest.raises(FrozenInstanceError):
        ResultadoFerramenta.ok("c1", {}).sucesso = False


@pytest.mark.parametrize("id_, nome", [("", "x"), ("c1", "")])
def test_chamada_exige_id_e_nome(id_, nome):
    with pytest.raises(ValueError):
        ChamadaFerramenta(id_, nome)


def test_resultado_com_falha_exige_erro():
    with pytest.raises(ValueError, match="exige a mensagem de erro"):
        ResultadoFerramenta("c1", sucesso=False)


def test_resultado_com_sucesso_nao_aceita_erro():
    with pytest.raises(ValueError, match="não pode ter erro"):
        ResultadoFerramenta("c1", sucesso=True, erro="x")


def test_resultado_falha_guarda_a_mensagem():
    resultado = ResultadoFerramenta.falha("c1", "data_fim anterior a data_inicio")

    assert (resultado.sucesso, resultado.erro, resultado.dados) == (False, "data_fim anterior a data_inicio", {})


def test_mensagem_converte_listas_em_tuplas():
    mensagem = Mensagem.assistente("Vou consultar.", chamadas=[chamada()])
    resultados = Mensagem.ferramenta([ResultadoFerramenta.ok("c1", {"n": 1})])

    assert isinstance(mensagem.chamadas, tuple)
    assert isinstance(resultados.resultados, tuple)


@pytest.mark.parametrize(
    "argumentos, motivo",
    [
        ({"papel": "operador", "texto": "x"}, "papel inválido"),
        ({"papel": "sistema", "texto": " "}, "mensagem de sistema exige texto"),
        ({"papel": "usuario", "texto": "x", "bruto": ("bloco",)}, "só a mensagem do assistente leva blocos"),
        ({"papel": "usuario", "texto": "   "}, "exige texto"),
        ({"papel": "usuario", "texto": "x", "chamadas": (chamada(),)}, "só o assistente"),
        ({"papel": "assistente"}, "texto ou chamadas"),
        ({"papel": "assistente", "texto": "x", "resultados": (ResultadoFerramenta.ok("c1", {}),)}, "só a mensagem de ferramenta"),
        ({"papel": "ferramenta"}, "ao menos um resultado"),
    ],
)
def test_mensagem_recusa_conteudo_incoerente_com_o_papel(argumentos, motivo):
    with pytest.raises(ValueError, match=motivo):
        Mensagem(**argumentos)


def test_fonte_recusa_tipo_desconhecido():
    with pytest.raises(ValueError, match="tipo de fonte"):
        Fonte("site", "x")


def test_formatar_chamada_mantem_ordem_tipos_e_acentos():
    texto = formatar_chamada(
        chamada("resumo_estatistico", parametros=["TIP-PH"], data_inicio="2026-06-01", estacao=None, limite=5)
    )

    assert texto == 'resumo_estatistico(parametros=["TIP-PH"], data_inicio="2026-06-01", estacao=null, limite=5)'
    assert formatar_chamada(chamada("buscar_documentacao", consulta="precipitação")) == (
        'buscar_documentacao(consulta="precipitação")'
    )


def test_fonte_de_chamada_e_do_tipo_ferramenta():
    fonte = Fonte.de_chamada(chamada("panorama_dados"))

    assert (fonte.tipo, fonte.descricao) == ("ferramenta", "panorama_dados()")


def test_resposta_agente_converte_fontes_e_recusa_negativos():
    resposta = RespostaAgente("ok", "c-1", fontes=[Fonte("documento", "docs/x.md")], tokens_entrada=10)

    assert isinstance(resposta.fontes, tuple)
    with pytest.raises(ValueError, match="negativos"):
        RespostaAgente("ok", "c-1", latencia_ms=-1)
