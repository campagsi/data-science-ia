import argparse
import sys
from datetime import date, timedelta
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
from src.models import ParametroModel
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
    Executa a ingestão (python main.py --ingestao) e devolve o resumo.

    O lote percorre duas partes, nesta ordem:

        Coleta (API)
          │
          ├─ Parte A: data lake ── _processar_no_data_lake()
          │    Bronze  lote como chegou, conferido pelo contrato (JSON)
          │    Silver  tratado, anonimizado e validado registro a registro (Parquet)
          │    Gold    modelo estrela para o Power BI (Parquet)
          │
          └─ Parte B: banco relacional (Azure SQL, 3FN) ── _gravar_no_banco()
               log de rejeitados → filtro dos válidos → gravação idempotente

    A parte B não refaz o tratamento: ela recebe da Silver o resultado da
    validação de cada registro. Por isso nenhum registro chega ao banco sem
    ter sido anonimizado e validado, e nada do que é recusado se perde: tudo
    vai para o log de rejeitados.
    """
    settings = load_config()

    # 1. Coleta: busca o lote bruto (lista de dicionários) na API configurada
    #    em FONTE_DADOS, com novas tentativas para queda de conexão, 5xx e 429
    #    e limite de requisições por minuto. Lote vazio encerra aqui, sem criar
    #    arquivos no data lake e sem tocar no banco.
    raw_data = DataClient(settings).fetch_data()
    if not raw_data:
        resumo = dict.fromkeys(_CAMPOS_RESUMO, 0)
        registrar_resumo(**resumo)
        return resumo

    # Parte A (etapas 2 a 4): tratamento e validação, nas camadas do data lake.
    resultados_validacao, parametros = _processar_no_data_lake(
        raw_data, settings.fonte_dados
    )

    # Parte B (etapas 5 a 7): log, filtro e gravação no banco relacional.
    validacao, gravacao = _gravar_no_banco(resultados_validacao, parametros, settings)

    # 8. Resumo da execução no log (e retorno da função). "Banco + rejeitados"
    #    fecha com o recebido: recebidos = rejeitados_na_normalizacao
    #    + registros_validos + registros_invalidos.
    resumo = {
        "recebidos": len(raw_data),
        # Quem não chegou à validação: recusado pelo contrato na Bronze,
        # registro_codigo repetido removido na Silver ou recusado na normalização.
        "rejeitados_na_normalizacao": len(raw_data) - len(resultados_validacao),
        "registros_validos": validacao["registros_validos"],
        "registros_invalidos": validacao["registros_invalidos"],
        "itens_descartados": validacao["itens_invalidos"],
        "leituras_gravadas": gravacao["leituras_gravadas"],
        "leituras_substituidas": gravacao["leituras_removidas"],
        "itens_gravados": gravacao["itens_gravados"],
    }
    registrar_resumo(**resumo)
    return resumo


def _processar_no_data_lake(
    raw_data: list[dict[str, Any]], fonte_dados: str
) -> tuple[list[dict[str, Any]], dict[str, ParametroModel]]:
    """
    Parte A da ingestão: passa o lote pelas camadas Bronze, Silver e Gold,
    gravadas em data_lake/ (src/ingestion/extracao_dados.py).

    Devolve o que a parte B precisa:
    - o resultado da validação de cada registro, no formato de
      ValidationService.validate_data(): valido, campos_nulos,
      itens_invalidos, motivos e o registro já anonimizado e sem os itens
      descartados;
    - os parâmetros aceitos (código → ParametroModel, com id e faixa).
    """
    # Por quê: importado aqui, e não no topo. O módulo chama a API de ingestão
    # já na importação; no topo, nenhum outro modo do main.py (análise, agente)
    # funcionaria com a API parada.
    from src.ingestion.extracao_dados import Extracao_Dados

    extracao = Extracao_Dados(fonte_dados=fonte_dados, diretorio_base="data_lake")

    # 2. Bronze: cada registro é conferido pelo contrato (DataContract: campos
    #    obrigatórios e tipos). Os aceitos são gravados como chegaram em
    #    data_lake/bronze/dados_bronze.json, ainda com CPF, nome e e-mail em
    #    claro (por isso data_lake/ fica fora do Git). Os recusados vão já para
    #    o log de rejeitados.
    recusados_no_contrato = extracao.extrair_dados_bronze(raw_data)
    registrar_resultados_validacao(resultados=recusados_no_contrato, nivel="Registro")

    # 3. Silver: lê a Bronze e prepara o lote para o banco, nesta ordem:
    #    a. remove registro_codigo repetido (fica a última ocorrência);
    #    b. normaliza e anonimiza (NormalizationService): texto vazio vira
    #       None, números e datas são convertidos, cada registro vira
    #       cabeçalho + itens (um por parâmetro), CPF e nome viram hash
    #       (HMAC-SHA256) e o e-mail é criptografado (src/security.py). Valor
    #       que não pode ser convertido é rejeitado e logado, sem derrubar o
    #       lote; medição vazia segue como None para a validação decidir;
    #    c. cadastra em Parametros os parâmetros novos do lote (sem faixa) e
    #       lê as siglas de Estados, que a validação usa como referência;
    #    d. valida cada registro (ValidationService.validate_data): campo
    #       vital nulo, estado inexistente ou cadastro divergente rejeita a
    #       leitura; medição nula ou fora da faixa descarta só o item.
    #    Os registros válidos são gravados em data_lake/silver/dados_silver.parquet.
    #    Volta o resultado de TODOS os registros, válidos e inválidos.
    resultados_validacao, parametros = extracao.extrair_dados_silver("dados_bronze.json")

    # 4. Gold: a partir da Silver, monta as dimensões (estação, parâmetro,
    #    tempo) e a tabela fato de medições em data_lake/gold/, consumidas
    #    pela API do Power BI. Não participa da gravação no banco.
    extracao.extrair_dados_gold("dados_silver.parquet")

    return resultados_validacao, parametros


def _gravar_no_banco(
    resultados_validacao: list[dict[str, Any]],
    parametros: dict[str, ParametroModel],
    settings: Settings,
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Parte B da ingestão: grava no banco relacional o que a validação aprovou.

    O schema não é criado aqui: ele é mantido por sql/ddl_banco_relacional.sql
    e sql/migrations/. Devolve as contagens da validação e da gravação.
    """
    # 5. Log de rejeitados: uma linha por motivo de cada leitura recusada e uma
    #    por medição descartada, em logs/. CPF, nome e e-mail nunca aparecem.
    validacao = registrar_resultados_validacao(resultados=resultados_validacao)

    # 6. Filtro: só os registros com valido=True, já sem os itens descartados.
    registros_validos = ValidationService.registros_validos(resultados_validacao)

    # 7. Gravação idempotente, numa única transação, na ordem das chaves
    #    estrangeiras (LeituraRepository.save_readings):
    #    - Estados: só leitura (as 27 siglas vêm de sql/dml_populacao.sql);
    #    - Municipios, Operadores e Estacoes: MERGE pelo código, ou seja,
    #      insere o que é novo e atualiza o que já existe;
    #    - Leituras e Leitura_Itens: apaga as leituras já gravadas da mesma
    #      estação + dia (ou do mesmo codigo_registro) e insere o lote de novo.
    #    Reexecutar o mesmo período não duplica nada; se qualquer etapa falhar,
    #    o rollback desfaz o lote inteiro e o banco fica como estava.
    database = DatabaseConnection(settings.azure_sql_connectionstring)
    gravacao = LeituraRepository(database).save_readings(
        registros_validos, parametros, settings.fonte_dados
    )
    return validacao, gravacao


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
    from src.agente.manutencao import atualizar_documentacao
    from src.config import load_config_indice

    return atualizar_documentacao(load_config_indice())


def indexar_dias():
    """
    Atualiza o índice dos resumos diários do agente (python main.py --indexar-dias, Fase 9).

    Lê todas as medições com o usuário só de leitura (AGENTE_SQL_CONNECTIONSTRING),
    gera um resumo por estação e dia e sincroniza o índice em AGENTE_DIR_INDICE/dias.
    Idempotente como o --indexar: só os dias cujo resumo mudou são vetorizados.
    Grava a assinatura dos dados, que o painel da página /agente compara com a atual.
    """
    configurar_logs("indexacao")
    # Por quê: import aqui para os outros modos não carregarem o onnxruntime.
    from src.agente.manutencao import atualizar_dias
    from src.config import load_config_indice

    return atualizar_dias(load_config_indice())


def treinar_previsao():
    """
    Treina e avalia o modelo de previsão (python main.py --treinar-previsao, Fase 10).

    Lê as medições com o usuário só de leitura (AGENTE_SQL_CONNECTIONSTRING),
    avalia cada parâmetro × horizonte com TimeSeriesSplit contra os dois baselines,
    grava o modelo e o metadados.json (com a assinatura dos dados) em
    AGENTE_DIR_INDICE/modelos/previsao e o relatório em relatorios/.

    Returns:
        Caminho do relatório.
    """
    configurar_logs("previsao")
    from src.agente.manutencao import treinar_previsao as treinar_e_salvar
    from src.config import load_config_indice

    return treinar_e_salvar(load_config_indice())


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
