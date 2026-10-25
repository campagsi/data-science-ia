"""
Base do agente (src/agente/manutencao.py): situação de cada artefato, gravação da
assinatura dos dados e o PainelDaBase (cache, regras de início e tarefa em segundo plano).

Sem banco e sem rede: dados de exemplo em memória e o EmbedderSimulado.
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import pytest

from src.agente import manutencao
from src.agente.ferramentas.consulta_dados import ConsultaDados
from src.agente.ferramentas.dados_exemplo import (
    CadastroEmMemoria,
    ESTACAO_EXEMPLO,
    LeiturasEmMemoria,
    PARAMETRO_EXEMPLO,
    consulta_de_exemplo,
    medicoes_de_exemplo,
)
from src.agente.manutencao import (
    ITENS,
    PainelDaBase,
    atualizar_dias,
    atualizar_documentacao,
    estado_da_base,
    estado_da_documentacao,
    estado_da_previsao,
    estado_dos_dias,
    situacao,
    treinar_previsao,
)
from src.agente.rag.embeddings import EmbedderSimulado
from src.config import ConfigIndice
from src.models.parametro_model import ParametroModel
from src.previsao.dados import PARAMETROS_ALVO
from src.previsao.persistencia import ARQUIVO_METADADOS, ARQUIVO_MODELO
from src.repository.leitura_repository import LeituraRepository


@pytest.fixture
def cfg(tmp_path):
    """Configuração com o índice numa pasta temporária."""
    return ConfigIndice(dir_indice=tmp_path)


# Por quê: o treino filtra os parâmetros com ciclo diário, que precisam existir no cadastro.
PARAMETROS_DO_TREINO = [
    ParametroModel(id_parametro=10 + indice, codigo_parametro=codigo, nome=codigo, unidade_medida="u", valor_minimo=None, valor_maximo=None)
    for indice, codigo in enumerate(PARAMETROS_ALVO)
]


def consulta_com(valores: list[float]) -> ConsultaDados:
    """ConsultaDados de exemplo com estes valores de pH e os parâmetros do treino cadastrados."""
    return ConsultaDados(
        LeiturasEmMemoria(medicoes_de_exemplo(valores)),
        CadastroEmMemoria([ESTACAO_EXEMPLO]),
        CadastroEmMemoria([{"id": 1, "nome": "Rio de Janeiro", "sigla": "RJ"}]),
        CadastroEmMemoria([PARAMETRO_EXEMPLO, *PARAMETROS_DO_TREINO]),
    )


# --- Assinatura ---------------------------------------------------------------------------


def test_assinatura_muda_com_o_conteudo_e_nao_com_a_ordem():
    base = consulta_com([7.0, 7.2]).assinatura()

    assert base == consulta_com([7.0, 7.2]).assinatura()
    assert base != consulta_com([7.0, 7.3]).assinatura()  # valor alterado
    assert base["medicoes"] == 2 and base["primeira"] == "2026-06-01T00:00:00"


def test_get_assinatura_agrega_no_banco_sem_id_nem_data_de_ingestao():
    class BancoFalso:
        """Devolve a linha agregada e guarda a consulta recebida."""

        def fetch_all(self, query, params=None):
            """Resultado de COUNT/MIN/MAX/CHECKSUM_AGG."""
            self.query = query
            return [(630212, datetime(2026, 4, 1), datetime(2026, 10, 23, 23, 30), -123456)]

    banco = BancoFalso()

    assinatura = LeituraRepository(banco).get_assinatura()

    assert assinatura == {"medicoes": 630212, "primeira": "2026-04-01T00:00:00", "ultima": "2026-10-23T23:30:00", "checksum": -123456}
    assert "CHECKSUM_AGG" in banco.query and "codigo_registro" in banco.query
    assert "id_leitura" not in banco.query.split("CHECKSUM_AGG")[1].split("FROM")[0]  # o id muda a cada reprocessamento
    assert "data_ingestao" not in banco.query


def test_get_assinatura_com_banco_vazio():
    class BancoVazio:
        """Agregação sem linhas: COUNT 0 e o resto nulo."""

        def fetch_all(self, query, params=None):
            """Linha única do agregado vazio."""
            return [(0, None, None, None)]

    assert LeituraRepository(BancoVazio()).get_assinatura() == {"medicoes": 0, "primeira": None, "ultima": None, "checksum": None}


# --- Documentação -------------------------------------------------------------------------


def corpus(raiz: Path, texto: str) -> Path:
    """Corpus mínimo: um README.md na raiz informada (texto longo o bastante para virar trecho)."""
    (raiz / "README.md").write_text(f"# Projeto\n\n{'Regra de validação das medições do projeto. ' * 4}{texto}\n", encoding="utf-8")
    return raiz


def test_documentacao_ausente_atualizada_e_desatualizada(cfg, tmp_path):
    raiz = tmp_path / "projeto"
    raiz.mkdir()
    corpus(raiz, "versão 1")
    embedder = EmbedderSimulado()

    assert estado_da_documentacao(cfg, embedder, raiz)["situacao"] == "ausente"

    from src.agente.rag.indexador import indexar

    indexar(embedder, cfg.dir_indice, raiz)
    assert estado_da_documentacao(cfg, embedder, raiz)["situacao"] == "atualizado"

    corpus(raiz, "versão 2")
    desatualizado = estado_da_documentacao(cfg, embedder, raiz)
    assert desatualizado["situacao"] == "desatualizado" and "documentação mudou" in desatualizado["motivo"]


def test_documentacao_de_outro_modelo_conta_como_ausente(cfg):
    atualizar_documentacao(cfg, EmbedderSimulado())

    assert estado_da_documentacao(cfg, EmbedderSimulado(dimensoes=64))["situacao"] == "ausente"


def test_atualizar_documentacao_registra_quando(cfg):
    atualizar_documentacao(cfg, EmbedderSimulado())

    estado = estado_da_documentacao(cfg, EmbedderSimulado())
    assert estado["situacao"] == "atualizado" and estado["atualizado_em"]


# --- Dias ---------------------------------------------------------------------------------


def test_dias_ausente_atualizado_e_desatualizado_quando_os_dados_mudam(cfg):
    embedder = EmbedderSimulado()
    antes, depois = consulta_com([7.0, 7.2]), consulta_com([7.0, 7.9])

    assert estado_dos_dias(cfg, antes.assinatura(), embedder)["situacao"] == "ausente"

    atualizar_dias(cfg, antes, embedder)
    assert estado_dos_dias(cfg, antes.assinatura(), embedder)["situacao"] == "atualizado"
    assert estado_dos_dias(cfg, consulta_com([7.0, 7.2]).assinatura(), embedder)["situacao"] == "atualizado"  # mesmos dados reingeridos

    mudou = estado_dos_dias(cfg, depois.assinatura(), embedder)
    assert mudou["situacao"] == "desatualizado" and "dados do banco mudaram" in mudou["motivo"]


def test_indice_dos_dias_sem_assinatura_gravada_conta_como_desatualizado(cfg):
    from src.agente.dias.indice import PASTA_DIAS, indexar_dias
    from src.agente.ferramentas.consulta_dados import FiltroMedicoes

    consulta = consulta_com([7.0])
    indexar_dias(consulta.medicoes(FiltroMedicoes()), EmbedderSimulado(), cfg.dir_indice)  # índice anterior a esta versão

    assert not (cfg.dir_indice / PASTA_DIAS / manutencao.ARQUIVO_ESTADO_DIAS).exists()
    assert estado_dos_dias(cfg, consulta.assinatura(), EmbedderSimulado())["situacao"] == "desatualizado"


def test_dias_e_previsao_indisponiveis_sem_banco(cfg):
    base = estado_da_base(cfg, embedder=EmbedderSimulado())  # ConfigIndice sem AGENTE_SQL_CONNECTIONSTRING

    assert base["dias"]["situacao"] == base["previsao"]["situacao"] == "indisponivel"
    assert "AGENTE_SQL_CONNECTIONSTRING" in base["dias"]["motivo"]


def test_falha_ao_ler_a_assinatura_deixa_dias_e_previsao_indisponiveis_sem_expor_a_mensagem(cfg, caplog):
    class ConsultaQuebrada:
        """O banco caiu no meio da conferência."""

        def assinatura(self):
            """Falha com uma mensagem que não pode ir para o log."""
            raise ConnectionError("Server=segredo;Password=123")

    with caplog.at_level(logging.ERROR):
        base = estado_da_base(cfg, ConsultaQuebrada(), EmbedderSimulado())

    assert base["dias"]["situacao"] == "indisponivel"
    assert "ConnectionError" in caplog.text and "segredo" not in caplog.text


def test_atualizar_sem_conexao_e_sem_consulta_falha_com_mensagem_clara(cfg):
    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        atualizar_dias(cfg, embedder=EmbedderSimulado())
    with pytest.raises(ValueError, match="AGENTE_SQL_CONNECTIONSTRING"):
        treinar_previsao(cfg)


# --- Previsão -----------------------------------------------------------------------------


def test_previsao_grava_a_assinatura_e_fica_desatualizada_quando_os_dados_mudam(cfg, tmp_path):
    consulta = consulta_com([7.0, 7.2])

    relatorio = treinar_previsao(cfg, consulta, tmp_path / "relatorios")

    metadados = json.loads((cfg.dir_indice / "modelos" / "previsao" / ARQUIVO_METADADOS).read_text(encoding="utf-8"))
    assert relatorio.exists() and metadados["assinatura_dados"] == consulta.assinatura()
    assert estado_da_previsao(cfg, consulta.assinatura())["situacao"] == "atualizado"
    assert estado_da_previsao(cfg, consulta_com([7.0, 8.0]).assinatura())["situacao"] == "desatualizado"


def test_previsao_que_o_agente_recusaria_aparece_como_desatualizada(cfg, tmp_path):
    consulta = consulta_com([7.0])
    treinar_previsao(cfg, consulta, tmp_path / "relatorios")
    pasta = cfg.dir_indice / "modelos" / "previsao"

    metadados = json.loads((pasta / ARQUIVO_METADADOS).read_text(encoding="utf-8"))
    (pasta / ARQUIVO_METADADOS).write_text(json.dumps({**metadados, "versao_sklearn": "0.1.0"}), encoding="utf-8")
    assert "scikit-learn" in estado_da_previsao(cfg, consulta.assinatura())["motivo"]

    with open(pasta / ARQUIVO_MODELO, "ab") as arquivo:
        arquivo.write(b"adulterado")
    assert "POL-12" in estado_da_previsao(cfg, consulta.assinatura())["motivo"]


def test_estado_da_base_completo_depois_de_atualizar_tudo(cfg, tmp_path):
    consulta, embedder = consulta_com([7.0, 7.2]), EmbedderSimulado()
    atualizar_documentacao(cfg, embedder)
    atualizar_dias(cfg, consulta, embedder)
    treinar_previsao(cfg, consulta, tmp_path / "relatorios")

    base = estado_da_base(cfg, consulta, embedder)

    assert {item: base[item]["situacao"] for item in ITENS} == dict.fromkeys(ITENS, "atualizado")


# --- PainelDaBase -------------------------------------------------------------------------


def pendente(*itens: str) -> dict:
    """Base com os itens informados desatualizados e o resto em dia."""
    return {item: situacao("desatualizado" if item in itens else "atualizado") for item in ITENS}


class Relogio:
    """Relógio controlado pelo teste."""

    def __init__(self):
        """Começa no zero."""
        self.agora = 0.0

    def __call__(self):
        """Tempo atual."""
        return self.agora


def test_estado_fica_em_cache_ate_o_ttl_ou_invalidar():
    chamadas, relogio = [], Relogio()
    painel = PainelDaBase(lambda: chamadas.append(1) or pendente(), lambda item: None, ttl_segundos=30, relogio=relogio)

    painel.estado()
    painel.estado()
    relogio.agora = 31
    painel.estado()
    painel.invalidar()
    painel.estado()

    assert len(chamadas) == 3
    assert painel.estado()["itens"]["dias"]["nome"] == "Dias semelhantes"


@pytest.mark.parametrize(
    ("pedido", "codigo", "trecho"),
    [
        ("todos", 400, "já está em dia"),
        (["dias"], 400, "Dias semelhantes"),
        (["xpto"], 400, "desconhecido"),
        ("dias", 400, "lista"),
        ([], 400, "lista"),
        (None, 400, "lista"),
    ],
)
def test_pedidos_recusados(pedido, codigo, trecho):
    painel = PainelDaBase(lambda: pendente(), lambda item: None)

    resposta = painel.iniciar(pedido)

    assert resposta[0] == codigo and trecho in resposta[1]


def test_todos_atualiza_so_os_pendentes_em_ordem_e_avisa_ao_concluir():
    atualizados, avisos = [], []
    painel = PainelDaBase(lambda: pendente("previsao", "documentacao"), atualizados.append)
    painel.ao_concluir = lambda: avisos.append("descartar agente")

    codigo, _ = painel.iniciar("todos")
    painel.aguardar(5)

    tarefa = painel.estado()["tarefa"]
    assert codigo == 202 and atualizados == ["documentacao", "previsao"]
    assert tarefa["executando"] is False and tarefa["concluidos"] == ["documentacao", "previsao"] and tarefa["terminou_em"]
    assert avisos == ["descartar agente"]


def test_uma_atualizacao_por_vez():
    liberar = threading.Event()
    painel = PainelDaBase(lambda: pendente("dias", "previsao"), lambda item: liberar.wait(5))

    assert painel.iniciar(["dias"])[0] == 202
    em_andamento = painel.estado()["tarefa"]
    assert painel.iniciar(["previsao"]) == (409, "Já existe uma atualização em andamento.")
    liberar.set()
    painel.aguardar(5)

    assert em_andamento["executando"] is True and em_andamento["etapa"] == "dias" and em_andamento["etapa_nome"] == "Dias semelhantes"


def test_falha_de_um_item_nao_impede_os_seguintes_nem_expoe_a_mensagem(caplog):
    def atualizar(item):
        """Falha só nos dias."""
        if item == "dias":
            raise RuntimeError("Password=segredo")

    avisos = []
    painel = PainelDaBase(lambda: pendente("dias", "previsao"), atualizar)
    painel.ao_concluir = lambda: avisos.append(1)

    with caplog.at_level(logging.INFO):
        painel.iniciar("todos")
        painel.aguardar(5)

    tarefa = painel.estado()["tarefa"]
    assert tarefa["falhas"] == ["dias"] and tarefa["concluidos"] == ["previsao"] and avisos == [1]
    assert "erro=RuntimeError" in caplog.text and "segredo" not in caplog.text


def test_tudo_falhou_nao_descarta_o_agente():
    avisos = []
    painel = PainelDaBase(lambda: pendente("dias"), lambda item: 1 / 0)
    painel.ao_concluir = lambda: avisos.append(1)

    painel.iniciar(["dias"])
    painel.aguardar(5)

    assert painel.estado()["tarefa"]["falhas"] == ["dias"] and avisos == []


def test_dados_mudaram_recalcula_e_descarta_o_agente():
    chamadas, avisos = [], []
    painel = PainelDaBase(lambda: chamadas.append(1) or pendente(), lambda item: None)
    painel.ao_concluir = lambda: avisos.append(1)
    painel.estado()

    painel.dados_mudaram()
    painel.estado()

    assert len(chamadas) == 2 and avisos == [1]


def test_main_usa_o_nucleo_e_grava_a_assinatura(monkeypatch, tmp_path):
    import main

    chamadas = []
    monkeypatch.setattr("src.config.load_config_indice", lambda: ConfigIndice(dir_indice=tmp_path, sql_connectionstring="x"))
    monkeypatch.setattr(main, "configurar_logs", lambda etapa: chamadas.append(etapa))
    monkeypatch.setattr(manutencao, "_consulta_do_banco", lambda cfg: consulta_de_exemplo())
    monkeypatch.setattr(manutencao, "_embedder", lambda cfg, embedder: EmbedderSimulado())

    main.indexar_dias()

    assert chamadas == ["indexacao"]
    assert estado_dos_dias(ConfigIndice(dir_indice=tmp_path), consulta_de_exemplo().assinatura(), EmbedderSimulado())["situacao"] == "atualizado"
