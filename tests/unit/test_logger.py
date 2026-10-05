import logging
import re

import pytest

import src.logger as log

LINHA = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - \[(INFO|WARNING|ERROR|CRITICAL)\] - .+$"
)


@pytest.fixture
def arquivos(tmp_path):
    caminhos = log.configurar_logs(tmp_path)
    yield caminhos
    # Fecha os arquivos para o tmp_path poder ser removido no Windows.
    for nome in (log.NOME_LOGGER_REJEITADOS, ""):
        for handler in list(logging.getLogger(nome or None).handlers):
            handler.close()
            logging.getLogger(nome or None).removeHandler(handler)


def _ler(caminho):
    for handler in logging.getLogger().handlers + log.logger_rejeitados.handlers:
        handler.flush()
    return caminho.read_text(encoding="utf-8").splitlines()


def test_configurar_logs_cria_os_dois_arquivos(arquivos, tmp_path):
    assert arquivos["pipeline"].parent == tmp_path
    assert arquivos["pipeline"].name.startswith("pipeline_")
    assert arquivos["rejeitados"].name.startswith("rejeitados_")
    assert arquivos["pipeline"].exists()
    assert arquivos["rejeitados"].exists()


def test_log_da_execucao_segue_o_formato(arquivos):
    log.logger.info("Iniciando ingestão")

    linhas = _ler(arquivos["pipeline"])

    assert linhas and LINHA.match(linhas[-1])
    assert linhas[-1].endswith("- [INFO] - Iniciando ingestão")


def test_rejeicao_vai_so_para_o_arquivo_de_rejeitados(arquivos):
    log.registrar_rejeicao(
        "acuracia", "item", "ph", "fora da faixa 0–14", registro="REG-1", valor=17.0
    )

    rejeitados = _ler(arquivos["rejeitados"])

    assert len(rejeitados) == 1
    assert LINHA.match(rejeitados[0])
    assert rejeitados[0].endswith(
        '- [WARNING] - etapa=acuracia nivel=item registro=REG-1 campo=ph valor=17.0 motivo="fora da faixa 0–14"'
    )
    assert not any("etapa=" in linha for linha in _ler(arquivos["pipeline"]))


def test_rejeicao_de_parametro_sem_registro_com_severidade_error(arquivos):
    log.registrar_rejeicao(
        "parametro", "parametro", "salinidade", "unidade de medida ausente",
        severidade=logging.ERROR,
    )

    linha = _ler(arquivos["rejeitados"])[0]

    assert "- [ERROR] - etapa=parametro nivel=parametro campo=salinidade" in linha
    assert "registro=" not in linha


@pytest.mark.parametrize("campo", sorted(log.CAMPOS_PESSOAIS))
def test_valor_de_campo_pessoal_nunca_vai_para_o_log(arquivos, campo):
    log.registrar_rejeicao("completude", "leitura", campo, "teste", valor="87360421969")

    linha = _ler(arquivos["rejeitados"])[0]

    assert "87360421969" not in linha
    assert f"campo={campo}" in linha


def test_contagem_de_rejeicoes_por_nivel_e_reiniciada(arquivos, tmp_path):
    log.registrar_rejeicao("completude", "leitura", "estacao_codigo", "nulo")
    log.registrar_rejeicao("completude", "item", "ph", "nulo")
    log.registrar_rejeicao("completude", "item", "umidade", "nulo")

    assert log.contar_rejeicoes() == {"leitura": 1, "item": 2}

    log.configurar_logs(tmp_path / "nova")
    assert log.contar_rejeicoes() == {}


def test_resumo_em_info(arquivos):
    log.registrar_resumo(recebidos=10, importados=8, rejeitados=2)

    assert _ler(arquivos["pipeline"])[-1].endswith(
        "- [INFO] - Resumo da ingestão: recebidos=10 importados=8 rejeitados=2"
    )
