"""
Gravação das entidades do modelo 3FN a partir dos registros válidos.

Cada função grava uma entidade de forma idempotente e devolve o mapa
"chave natural → id" usado pela etapa seguinte. São chamadas, nesta ordem e
na mesma transação, por LeituraRepository.save_readings().
"""
from src.config import load_config
from src.database import DatabaseConnection
from src.ingestion.data_client import DataClient
from src.models import (
    EstacaoModel,
    LeituraItemModel,
    LeituraModel,
    MunicipioModel,
    OperadorModel,
    ParametroModel,
)
from src.repository.estacao_repository import EstacaoRepository
from src.repository.leitura_repository import LeituraRepository
from src.repository.municipio_repository import MunicipioRepository
from src.repository.operador_repository import OperadorRepository


def importar_municipios(
    registros: list[dict], estados: dict[str, int], database: DatabaseConnection
) -> dict[tuple[str, str], int]:
    """
    Grava os municípios do lote. estados: sigla → id_estado.

    Devolve (municipio, sigla do estado) → id_municipio.
    """
    chaves = {(r["municipio"], r["cidade_estado"]) for r in registros}
    repositorio = MunicipioRepository(database)
    repositorio.merge_many(
        [MunicipioModel(nome=nome, estado_id=estados[sigla]) for nome, sigla in sorted(chaves)]
    )

    # A collation do banco não diferencia maiúsculas: a busca também não.
    ids = {(m.nome.casefold(), m.estado_id): m.id_municipio for m in repositorio.get_all()}
    return {(nome, sigla): ids[(nome.casefold(), estados[sigla])] for nome, sigla in chaves}


def importar_operadores(
    registros: list[dict], municipios: dict[tuple[str, str], int], database: DatabaseConnection
) -> dict[str, int]:
    """Grava os operadores (já anonimizados). Devolve codigo_operador → id_operador."""
    operadores: dict[str, OperadorModel] = {}
    for r in registros:
        # A validação garante dados iguais para o mesmo código no lote.
        operadores.setdefault(
            r["operador_codigo"],
            OperadorModel(
                codigo_operador=r["operador_codigo"],
                nome_hash=r["nome_hash"],
                cpf_hash=r["cpf_hash"],
                municipio_id=municipios[(r["municipio"], r["cidade_estado"])],
                email_criptografado=r["email_criptografado"],
            ),
        )

    repositorio = OperadorRepository(database)
    repositorio.merge_many(list(operadores.values()))
    ids = {o.codigo_operador: o.id_operador for o in repositorio.get_all()}
    return {codigo: ids[codigo] for codigo in operadores}


def importar_estacoes(
    registros: list[dict], municipios: dict[tuple[str, str], int], database: DatabaseConnection
) -> dict[str, int]:
    """Grava as estações. Devolve codigo_estacao → id_estacao."""
    estacoes: dict[str, EstacaoModel] = {}
    for r in registros:
        estacoes.setdefault(
            r["estacao_codigo"],
            EstacaoModel(
                codigo_estacao=r["estacao_codigo"],
                nome=r["estacao_nome"],
                municipio_id=municipios[(r["municipio"], r["cidade_estado"])],
                latitude=r["estacao_latitude"],
                longitude=r["estacao_longitude"],
            ),
        )

    repositorio = EstacaoRepository(database)
    repositorio.merge_many(list(estacoes.values()))
    ids = {e.codigo_estacao: e.id_estacao for e in repositorio.get_all()}
    return {codigo: ids[codigo] for codigo in estacoes}


def importar_leituras(
    registros: list[dict],
    operadores: dict[str, int],
    estacoes: dict[str, int],
    parametros: dict[str, ParametroModel],
    fonte: str,
    database: DatabaseConnection,
) -> dict[str, int]:
    """
    Grava os cabeçalhos e as medições, substituindo as partições afetadas
    (estação + dia). Os registros já chegam só com os itens válidos.
    """
    leituras = []
    itens = []
    for r in registros:
        leituras.append(
            LeituraModel(
                codigo_registro=r["registro_codigo"],
                operador_id=operadores[r["operador_codigo"]],
                estacao_id=estacoes[r["estacao_codigo"]],
                data_hora=r["data_hora_ciclo"],
                fonte=fonte,
            )
        )
        itens += [
            LeituraItemModel(
                codigo_registro=r["registro_codigo"],
                parametro_id=parametros[item["codigo_parametro"]].id_parametro,
                valor=item["valor"],
            )
            for item in r["itens"]
        ]

    return LeituraRepository(database).substituir_leituras(leituras, itens)


def importar_dados() -> list[dict]:
    """Mantém a fachada pública de ingestão sem executar persistência."""
    settings = load_config()
    return DataClient(settings).fetch_data()


if __name__ == "__main__":
    from src.logger import configurar_logs, logger

    configurar_logs("coleta")
    dados = importar_dados()
    logger.info(f"Dados recebidos da API: {len(dados)} registros.")
