import threading

import pytest

from src.agente.conversa import Conversa, Conversas


def test_historico_comeca_vazio():
    assert Conversa("c-1", max_turnos=3).mensagens == ()


def test_historico_alterna_usuario_e_assistente():
    conversa = Conversa("c-1", max_turnos=3)
    conversa.registrar("pH médio em junho?", "7,38.")

    assert [(m.papel, m.texto) for m in conversa.mensagens] == [
        ("usuario", "pH médio em junho?"),
        ("assistente", "7,38."),
    ]


def test_historico_mantem_so_os_ultimos_turnos():
    conversa = Conversa("c-1", max_turnos=10)
    for i in range(15):
        conversa.registrar(f"pergunta {i}", f"resposta {i}")

    assert conversa.turnos == 10
    assert conversa.mensagens[0].texto == "pergunta 5"
    assert conversa.mensagens[-1].texto == "resposta 14"


def test_max_turnos_invalido():
    with pytest.raises(ValueError):
        Conversa("c-1", max_turnos=0)


def test_conversas_com_ids_diferentes_nao_se_misturam():
    conversas = Conversas(max_turnos=10)
    conversas.obter("a").registrar("pH em junho?", "7,38.")
    conversas.obter("b").registrar("Turbidez em julho?", "4,1 NTU.")

    assert [m.texto for m in conversas.obter("a").mensagens] == ["pH em junho?", "7,38."]
    assert [m.texto for m in conversas.obter("b").mensagens] == ["Turbidez em julho?", "4,1 NTU."]


def test_sem_id_cria_conversa_nova_a_cada_chamada():
    conversas = Conversas()

    assert conversas.obter().id != conversas.obter().id
    assert len(conversas) == 2


def test_limite_turnos_vale_para_cada_conversa():
    conversas = Conversas(max_turnos=2)
    conversa = conversas.obter("a")
    for i in range(5):
        conversa.registrar(f"p{i}", f"r{i}")

    assert conversas.obter("a").turnos == 2


@pytest.mark.parametrize("conversa_id", ["", "com espaço", "a" * 65, "ana@ex.com", "../x"])
def test_id_fora_do_formato_e_recusado(conversa_id):
    with pytest.raises(ValueError, match="conversa_id inválido"):
        Conversas().obter(conversa_id)


def test_conversa_usada_ha_mais_tempo_e_descartada_no_limite():
    conversas = Conversas(max_conversas=2)
    conversas.obter("a").registrar("p", "r")
    conversas.obter("b")
    conversas.obter("a")  # "a" passa a ser a mais recente
    conversas.obter("c")  # descarta "b"

    assert len(conversas) == 2
    assert conversas.obter("a").turnos == 1
    assert conversas.obter("b").turnos == 0  # recriada vazia


def test_descartar_esquece_a_conversa():
    conversas = Conversas()
    conversas.obter("a").registrar("p", "r")
    conversas.descartar("a")
    conversas.descartar("inexistente")

    assert conversas.obter("a").turnos == 0


def test_acesso_concorrente_nao_perde_turnos_nem_conversas():
    conversas = Conversas(max_turnos=1000, max_conversas=1000)
    compartilhada = conversas.obter("compartilhada")
    barreira = threading.Barrier(8)

    def trabalhar(indice: int) -> None:
        barreira.wait()
        for i in range(50):
            compartilhada.registrar(f"p{indice}-{i}", "r")
            conversas.obter(f"t{indice}-{i}")

    threads = [threading.Thread(target=trabalhar, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert compartilhada.turnos == 400
    assert len(conversas) == 401
