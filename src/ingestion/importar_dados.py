from src.config import load_config
from src.ingestion.data_client import DataClient
from pydantic import ValidationError

from src.models import CidadeModel, EstacaoModel, LeituraModel, OperadorModel
from src.repository import (
    CidadeRepository,
    EstacaoRepository,
    LeituraRepository,
    OperadorRepository,
)

__cidades = {}
__operadores = {}
__estacoes = {}


def importar_cidades(dados):
    try:
        cidades_model_list: list[CidadeModel] = []

        for cidade in dados:
            cidade_model = CidadeModel(
                nome=cidade["cidade_nome"], estado=cidade["cidade_estado"]
            )

            if cidade_model not in cidades_model_list:
                cidades_model_list.append(cidade_model)

        CidadeRepository().create_many(cidades_model_list)
    except ValidationError as error:
        raise ValueError(
            f"Dados inválidos na importação de Cidades: {error}"
        ) from error
    except BaseException as error:
        raise RuntimeError(f"Falha ao importar Cidades: {error}") from error


def importar_operadores(dados):
    try:
        operadores_model_list: list[OperadorModel] = []

        for item in dados:
            nome = item["cidade_nome"]

            if nome not in __cidades:
                cidade = CidadeRepository().get_by_name(nome)
                __cidades[nome] = cidade

            cidade_id = __cidades[nome]["id"]

            operador_model = OperadorModel(
                codigo=item["operador_codigo"],
                nome=item["operador_nome"],
                tipo=item["operador_tipo"],
                cidade_id=cidade_id,
            )

            if operador_model not in operadores_model_list:
                operadores_model_list.append(operador_model)

        OperadorRepository().create_many(operadores_model_list)
    except ValidationError as error:
        raise ValueError(
            f"Dados inválidos na importação de Operadores: {error}"
        ) from error
    except BaseException as error:
        raise RuntimeError(f"Falha ao importar Operadores: {error}") from error


def importar_estacoes(dados):
    try:
        estacoes_model_list: list[EstacaoModel] = []

        for item in dados:
            if item["cidade_nome"] not in __cidades:
                cidade = CidadeRepository().get_by_name(item["cidade_nome"])
                __cidades[item["cidade_nome"]] = cidade

            if item["operador_codigo"] not in __operadores:
                operador = OperadorRepository().get_by_name(item["operador_nome"])
                __operadores[item["operador_codigo"]] = operador

            cidade_id = __cidades[item["cidade_nome"]]["id"]
            operador_id = __operadores[item["operador_codigo"]]["id"]

            estacao_model = EstacaoModel(
                codigo=item["estacao_codigo"],
                nome=item["estacao_nome"],
                cidade_id=cidade_id,
                operador_id=operador_id,
                latitude=item["estacao_latitude"],
                longitude=item["estacao_longitude"],
                ativa=item["estacao_ativa"],
                tipo=item["estacao_tipo"],
            )

            if estacao_model not in estacoes_model_list:
                estacoes_model_list.append(estacao_model)

        EstacaoRepository().create_many(estacoes_model_list)
    except ValidationError as error:
        raise ValueError(
            f"Dados inválidos na importação de Estações: {error}"
        ) from error
    except BaseException as error:
        raise RuntimeError(f"Falha ao importar Estações: {error}") from error


def importar_leituras(dados):
    try:
        leituras_model_list: list[LeituraModel] = []

        for item in dados:
            codigo = item["estacao_codigo"]

            if codigo not in __estacoes:
                estacao = EstacaoRepository().get_by_codigo(codigo)
                __estacoes[codigo] = estacao

            estacaoID = __estacoes[codigo]["id"]
            leitura_model = LeituraModel(
                estacao_id=estacaoID,
                data_hora=item["data_hora"],
                temperatura=item.get("temperatura"),
                umidade=item.get("umidade"),
                pressao=item.get("pressao"),
                precipitacao=item.get("precipitacao"),
                velocidade_vento=item.get("velocidade_vento"),
                direcao_vento=item.get("direcao_vento"),
                radiacao_solar=item.get("radiacao_solar"),
                temperatura_agua=item.get("temperatura_agua"),
                ph=item.get("ph"),
                oxigenio_dissolvido=item.get("oxigenio_dissolvido"),
                condutividade=item.get("condutividade"),
                turbidez=item.get("turbidez"),
                fonte=item.get("fonte"),
            )
            leituras_model_list.append(leitura_model)

        LeituraRepository().create_many(leituras_model_list)
    except ValidationError as error:
        raise ValueError(
            f"Dados inválidos na importação de Estações: {error}"
        ) from error
    except BaseException as error:
        raise RuntimeError(f"Falha ao importar Estações: {error}") from error


def importar_dados() -> list[dict]:
    """Mantém a fachada pública de ingestão sem executar persistência."""
    settings = load_config()
    return DataClient(settings).fetch_data()


if __name__ == "__main__":
    dados = importar_dados()
    print(f"Dados recebidos da API: {len(dados)} registros.")
