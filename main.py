import argparse
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any

from src.cli.console_app import Console_APP
from src.config import Settings, load_config
from src.database.connection import DatabaseConnection
from src.ingestion.data_client import DataClient
from src.logger import (
    configurar_logs,
    logger,
    registrar_anomalias,
    registrar_resultados_validacao,
    registrar_resumo,
)
from src.repository.leitura_repository import LeituraRepository
from src.security import configurar_seguranca
from src.services.analytics_service import AnaliticsService
from src.services.report_service import ReportService
from src.services.validation_service import ValidationService

# Chaves do resumo da ingestão, na ordem em que aparecem no log.
_CAMPOS_RESUMO = (
    "recebidos",
    "rejeitados_na_normalizacao",
    "registros_validos",
    "registros_invalidos",
    "itens_descartados",
    "leituras_gravadas",
    "leituras_substituidas",
    "itens_gravados",
)


def run_pipeline() -> dict[str, int]:
    """
    Executa a ingestão: coleta, normalização, cadastro de parâmetros, validação
    e gravação idempotente no banco. Devolve o resumo da execução.

    Nenhum registro chega ao banco sem passar pela validação (etapa 5), e nada
    do que é recusado se perde: tudo vai para o log de rejeitados (etapa 6).
    """
    # 1. Coleta: busca o lote bruto (JSON) na API configurada em FONTE_DADOS,
    #    com novas tentativas para queda de conexão, 5xx e 429 e limite de
    #    requisições por minuto. Lote vazio encerra aqui, sem tocar no banco.
    settings = load_config()
    raw_data = DataClient(settings).fetch_data()
    if not raw_data:
        resumo = dict.fromkeys(_CAMPOS_RESUMO, 0)
        registrar_resumo(**resumo)
        return resumo

    # Por quê: importado aqui, e não no topo. O módulo chama a API de ingestão
    # já na importação; no topo, nenhum outro modo do main.py (análise, agente)
    # funcionaria com a API parada.
    from src.ingestion.extracao_dados import Extracao_Dados

    # Realiza a extração dos dados para camada Bronze, salvando o arquivo em JSON
    extracao_dados = Extracao_Dados(
        fonte_dados=settings.fonte_dados, diretorio_base="data_lake"
    )
    log = extracao_dados.extrair_dados_bronze(raw_data)
    registrar_resultados_validacao(resultados=log, nivel="Registro")
    # validacao = registrar_resultados_validacao(resultados=normalized_data_silver)
    # 2. Tratamento: texto vazio vira None, números e datas são convertidos,
    #    cada registro vira cabeçalho + itens (um por parâmetro) e CPF, nome e
    #    e-mail do operador são anonimizados. Valor que não pode ser convertido
    #    é rejeitado e logado aqui, sem derrubar o lote; medição vazia segue
    #    como None para a validação decidir.
    # normalized_data = NormalizationService().normalize(raw_data)

    # Realia a extração dos dados para a camada silver a partir dos dados extraidos pela camda bronze
    normalized_data_silver, parametros = extracao_dados.extrair_dados_silver(
        "dados_bronze.json"
    )

    # Realiza a extração de dados para a camada gold a partir dos dados extraidos pela camada silver
    extracao_dados.extrair_dados_gold("dados_silver.parquet")

    # O schema é mantido por sql/ddl_banco_relacional.sql e sql/migrations/.
    database = DatabaseConnection(settings.azure_sql_connectionstring)

    # 3. Parâmetros: os encontrados no lote (*_tipo_codigo) e ainda não
    #    cadastrados são inseridos em Parametros, sem faixa. Volta o mapa
    #    código → parâmetro aceito, com id e faixa de valores.
    # parametros = ParametroService(ParametroRepository(database)).sincronizar(
    #     NormalizationService.descobrir_parametros(normalized_data_silver)
    # )

    # 4. Referência: siglas de Estados, para conferir o estado de cada leitura.
    # siglas = {estado.sigla for estado in EstadoRepository(database).get_all()}

    # 5. Validação, antes de qualquer gravação. Não grava nem loga: devolve um
    #    resultado por registro (valido, campos_nulos, itens_invalidos, motivos).
    #    - completude: campo vital nulo rejeita a leitura; medição nula descarta
    #      só o item; leitura sem nenhuma medição válida é rejeitada;
    #    - acurácia: valor fora da faixa do parâmetro descarta só o item;
    #    - referência e validade: estado inexistente ou sigla inválida;
    #    - unicidade: registro repetido no lote e cadastro divergente.
    # resultados = ValidationService(
    #     faixas=ParametroService.faixas(parametros),
    #     siglas_estados=siglas,
    #     parametros_validos=set(parametros),
    # ).validate_data(normalized_data)

    # 6. Log de rejeitados a partir dos resultados: uma linha por leitura
    #    recusada e uma por medição descartada (sem dado pessoal).
    validacao = registrar_resultados_validacao(resultados=normalized_data_silver)

    # 7. Filtro: só os registros com valido=True, já sem os itens descartados.
    validated_data = ValidationService.registros_validos(normalized_data_silver)

    # 8. Gravação idempotente, numa única transação: municípios, operadores e
    #    estações por MERGE; leituras e itens substituindo as partições
    #    estação + dia. Reexecutar o mesmo período não duplica; se algo falhar,
    #    nada do lote fica gravado.
    gravacao = LeituraRepository(database).save_readings(
        validated_data, parametros, settings.fonte_dados
    )

    # 9. Resumo da execução no log (e retorno da função).
    resumo = {
        "recebidos": len(raw_data),
        "rejeitados_na_normalizacao": len(raw_data) - len(normalized_data_silver),
        "registros_validos": validacao["registros_validos"],
        "registros_invalidos": validacao["registros_invalidos"],
        "itens_descartados": validacao["itens_invalidos"],
        "leituras_gravadas": gravacao["leituras_gravadas"],
        "leituras_substituidas": gravacao["leituras_removidas"],
        "itens_gravados": gravacao["itens_gravados"],
    }
    registrar_resumo(**resumo)
    return resumo


def gerar_relatorio(
    database: DatabaseConnection,
    codigo_estacao: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> dict[str, Any]:
    """
    Análise estatística das medições gravadas (item 3.4 do enunciado).

    Sem estação, analisa todas. Registra o relatório em INFO e cada medição
    anômala em WARNING no log da execução. Devolve o relatório estruturado.
    """
    analise = AnaliticsService(database)
    estacao_id = None
    if codigo_estacao is not None:
        estacao = analise.buscar_estacao_por_codigo(codigo_estacao)
        if estacao is None:
            raise ValueError(f"Estação não cadastrada: {codigo_estacao}")
        estacao_id = estacao.id_estacao

    relatorio = ReportService().generate_report(
        analise.calculate_metrics(
            estacao_id=estacao_id, data_inicio=data_inicio, data_fim=data_fim
        )
    )
    _exibir_resultados(relatorio)
    registrar_anomalias(relatorio["anomalias"])
    return relatorio


def iniciar_aplicacao(etapa: str) -> Settings:
    """
    Prepara logs, configuração e chaves antes de qualquer etapa da aplicação.

    etapa ("ingestao", "analise" ou "consulta") vai para o cabeçalho dos logs.
    """
    configurar_logs(etapa)
    settings = load_config()
    configurar_seguranca(settings.chave_criptografia, settings.chave_hash)
    logger.info("Configuração carregada e segurança inicializada.")
    return settings


def _exibir_resultados(resultados: dict[str, Any]) -> None:
    """Registra no log o relatório textual produzido pelo pipeline."""
    texto = ReportService().format_report(resultados)
    if texto:
        logger.info(f"Relatório da execução:\n{texto}")


def iniciar_agente():
    """
    Prepara o log (etapa "agente") e monta o agente analítico a partir do .env.

    Não exige as variáveis da ingestão: o agente tem configuração própria
    (load_config_agente) e lê o banco com o usuário só de leitura.
    """
    configurar_logs("agente")
    # Por quê: import aqui para os outros modos não carregarem o SDK do LLM.
    from src.agente import criar_agente

    agente = criar_agente()
    logger.info("Agente analítico configurado.")
    return agente


def indexar_documentacao():
    """
    Atualiza o índice da documentação do agente (python main.py --indexar).

    Idempotente: sem mudança nos documentos, a segunda execução registra
    inseridos=0 removidos=0. Na primeira vez, baixa o modelo de embeddings
    (~0,22 GB) para data/agente/modelos.
    """
    configurar_logs("indexacao")
    # Por quê: import aqui para os outros modos não carregarem o onnxruntime.
    from src.agente.rag.embeddings import EmbedderFastembed
    from src.agente.rag.indexador import indexar
    from src.config import load_config_indice

    cfg = load_config_indice()
    return indexar(EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos"), cfg.dir_indice, vetores=cfg.vetores)


def indexar_dias():
    """
    Atualiza o índice dos resumos diários do agente (python main.py --indexar-dias, Fase 9).

    Lê todas as medições com o usuário só de leitura (AGENTE_SQL_CONNECTIONSTRING),
    gera um resumo por estação e dia e sincroniza o índice em AGENTE_DIR_INDICE/dias.
    Idempotente como o --indexar: só os dias cujo resumo mudou são vetorizados.
    """
    configurar_logs("indexacao")
    # Por quê: import aqui para os outros modos não carregarem o onnxruntime.
    from src.agente.dias.indice import indexar_dias as sincronizar_dias
    from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes
    from src.agente.rag.embeddings import EmbedderFastembed
    from src.config import load_config_indice

    cfg = load_config_indice()
    if not cfg.sql_connectionstring:
        raise ValueError("A variável AGENTE_SQL_CONNECTIONSTRING deve estar configurada para o --indexar-dias.")
    medicoes = ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring)).medicoes(FiltroMedicoes())
    return sincronizar_dias(medicoes, EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos"), cfg.dir_indice, cfg.vetores)


def treinar_previsao():
    """
    Treina e avalia o modelo de previsão (python main.py --treinar-previsao, Fase 10).

    Lê as medições com o usuário só de leitura (AGENTE_SQL_CONNECTIONSTRING),
    avalia cada parâmetro × horizonte com TimeSeriesSplit contra os dois baselines,
    grava o modelo e o metadados.json em AGENTE_DIR_INDICE/modelos/previsao e o
    relatório em relatorios/.

    Returns:
        Caminho do relatório.
    """
    configurar_logs("previsao")
    from src.agente.fabrica import pasta_do_modelo_de_previsao
    from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes
    from src.config import RAIZ_PROJETO, load_config_indice
    from src.previsao.dados import PARAMETROS_ALVO
    from src.previsao.persistencia import salvar_modelo
    from src.previsao.relatorio import montar_relatorio_treino
    from src.previsao.treino import treinar

    cfg = load_config_indice()
    if not cfg.sql_connectionstring:
        raise ValueError("A variável AGENTE_SQL_CONNECTIONSTRING deve estar configurada para o --treinar-previsao.")
    consulta = ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))
    inicio = time.monotonic()
    avaliacoes = treinar(consulta.medicoes(FiltroMedicoes(parametros=PARAMETROS_ALVO)))
    salvar_modelo(avaliacoes, pasta_do_modelo_de_previsao(cfg.dir_indice))
    relatorio = RAIZ_PROJETO / "relatorios" / f"previsao_{datetime.now():%Y%m%d_%H%M%S}.md"
    relatorio.parent.mkdir(parents=True, exist_ok=True)
    relatorio.write_text(montar_relatorio_treino(avaliacoes), encoding="utf-8")
    aprovados = sum(a.aprovado for a in avaliacoes)
    logger.info(f"Treino da previsão: combinacoes={len(avaliacoes)} aprovadas={aprovados} ms={int((time.monotonic() - inicio) * 1000)} relatorio={relatorio}")
    return relatorio


LIMITE_LAUDOS = 50


def gerar_laudos_de_anomalias(estacao: str | None, inicio: date, fim: date | None, limite: int | None):
    """
    Laudos das anomalias do período com o LLM (python main.py --laudo, Fase 11).

    Uma chamada ao LLM por anomalia (as mais extremas primeiro, até o limite),
    resposta validada pelo contrato LaudoAnomalia, e o CSV e o Markdown em
    relatorios/, sinalizados como gerados por IA. Não altera o banco.

    Returns:
        Caminho do relatório Markdown.
    """
    configurar_logs("laudo")
    # Por quê: import aqui para os outros modos não carregarem o SDK do LLM.
    from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes
    from src.agente.laudo.contexto import anomalias_com_contexto
    from src.agente.laudo.gerador import exportar_laudos, gerar_laudos
    from src.agente.fabrica import llm_da_config
    from src.config import FORNECEDORES_REAIS, RAIZ_PROJETO, load_config_agente

    cfg = load_config_agente()
    if cfg.llm_fornecedor not in FORNECEDORES_REAIS:
        raise ValueError("O --laudo usa o LLM real: configure AGENTE_LLM_FORNECEDOR=anthropic ou openai.")
    fim = fim or inicio
    consulta = ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))
    periodo = consulta.medicoes(FiltroMedicoes(estacao=estacao, data_inicio=inicio, data_fim=fim))
    # Por quê: um dia de margem para os vizinhos de 2 h das anomalias nas bordas do período.
    margem = consulta.medicoes(FiltroMedicoes(estacao=estacao, data_inicio=inicio - timedelta(days=1), data_fim=fim + timedelta(days=1)))
    resultados = gerar_laudos(llm_da_config(cfg), anomalias_com_contexto(periodo, margem), LIMITE_LAUDOS if limite is None else limite)
    caminho_csv, caminho_md = exportar_laudos(resultados, RAIZ_PROJETO / "relatorios", f"laudos_{inicio}_{fim}", cfg.llm_modelo)
    logger.info(f"Laudos: csv={caminho_csv} relatorio={caminho_md}")
    return caminho_md


def ler_argumentos(argv: list[str]) -> argparse.Namespace:
    """Sem argumentos abre a CLI; --ingestao carrega o banco; --analise gera o relatório; --agente e --pergunta usam o agente."""
    parser = argparse.ArgumentParser(description="Pipeline de dados ambientais")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--ingestao", action="store_true", help="coleta, valida e grava no banco"
    )
    modo.add_argument(
        "--analise",
        action="store_true",
        help="estatística e outliers das medições gravadas",
    )
    modo.add_argument(
        "--agente", action="store_true", help="chat com o agente analítico (LLM + ferramentas)"
    )
    modo.add_argument(
        "--pergunta", metavar="TEXTO", help="uma pergunta ao agente analítico, com a resposta no terminal"
    )
    modo.add_argument(
        "--indexar", action="store_true", help="atualiza o índice da documentação usado pelo agente (RAG)"
    )
    modo.add_argument(
        "--indexar-dias", action="store_true", help="atualiza o índice dos resumos diários (ferramenta dias_semelhantes)"
    )
    modo.add_argument(
        "--treinar-previsao", action="store_true", help="treina e avalia o modelo de previsão (ferramenta prever)"
    )
    modo.add_argument(
        "--laudo", action="store_true", help="laudos das anomalias do período com o LLM (exige --inicio)"
    )
    parser.add_argument(
        "--estacao", metavar="CODIGO", help="código da estação (padrão: todas)"
    )
    parser.add_argument(
        "--inicio",
        type=date.fromisoformat,
        metavar="AAAA-MM-DD",
        help="sozinha, analisa só esse dia",
    )
    parser.add_argument("--fim", type=date.fromisoformat, metavar="AAAA-MM-DD")
    parser.add_argument(
        "--limite", type=int, metavar="N", help=f"máximo de laudos (as anomalias mais extremas primeiro; padrão {LIMITE_LAUDOS}, 0 = todas)"
    )
    argumentos = parser.parse_args(argv)

    if not (argumentos.analise or argumentos.laudo) and (
        argumentos.estacao or argumentos.inicio or argumentos.fim
    ):
        parser.error("--estacao, --inicio e --fim só valem com --analise ou --laudo")
    if argumentos.laudo and not argumentos.inicio:
        parser.error("--laudo exige --inicio")
    if argumentos.limite is not None and (not argumentos.laudo or argumentos.limite < 0):
        parser.error("--limite só vale com --laudo e não pode ser negativo")
    if argumentos.fim and not argumentos.inicio:
        parser.error("--fim exige --inicio")
    if argumentos.inicio and argumentos.fim and argumentos.inicio > argumentos.fim:
        parser.error("--inicio não pode ser maior que --fim")
    return argumentos


def etapa_da_execucao(argumentos: argparse.Namespace) -> str:
    """Etapa registrada no cabeçalho dos logs (chave de src.logger.ETAPAS)."""
    if argumentos.ingestao:
        return "ingestao"
    if argumentos.analise:
        return "analise"
    if argumentos.agente or argumentos.pergunta:
        return "agente"
    if argumentos.indexar or argumentos.indexar_dias:
        return "indexacao"
    if argumentos.treinar_previsao:
        return "previsao"
    if argumentos.laudo:
        return "laudo"
    return "consulta"


if __name__ == "__main__":
    argumentos = ler_argumentos(sys.argv[1:])
    # Extracao_Dados("test").execute()
    try:
        if argumentos.indexar:
            indexar_documentacao()
            raise SystemExit(0)
        if argumentos.indexar_dias:
            indexar_dias()
            raise SystemExit(0)
        if argumentos.treinar_previsao:
            treinar_previsao()
            raise SystemExit(0)
        if argumentos.laudo:
            gerar_laudos_de_anomalias(argumentos.estacao, argumentos.inicio, argumentos.fim, argumentos.limite)
            raise SystemExit(0)
        if argumentos.agente or argumentos.pergunta:
            from src.cli.agente_cli import conversar, responder_uma

            agente = iniciar_agente()
            if argumentos.pergunta:
                responder_uma(agente, argumentos.pergunta)
            else:
                conversar(agente)
            raise SystemExit(0)
        settings = iniciar_aplicacao(etapa_da_execucao(argumentos))
        if argumentos.ingestao:
            run_pipeline()
        elif argumentos.analise:
            gerar_relatorio(
                DatabaseConnection(settings.azure_sql_connectionstring),
                argumentos.estacao,
                argumentos.inicio,
                argumentos.fim,
            )
        else:
            console_app = Console_APP()
            console_app.run()
    except SystemExit:
        raise
    except Exception as erro:
        logger.critical(f"{type(erro).__name__}: {erro}")
        raise SystemExit(1) from erro
