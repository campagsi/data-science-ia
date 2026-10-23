"""
Avaliação do agente pela linha de comando.

    python -m src.agente.avaliacao                              # golden set completo (LLM real, banco e índice)
    python -m src.agente.avaliacao --categoria documentacao     # só uma categoria
    python -m src.agente.avaliacao --so-recuperacao             # sem LLM e sem banco: hit@4 e MRR do índice
    python -m src.agente.avaliacao --lote                       # seleção de ferramentas pela Batch API
    python -m src.agente.avaliacao --modelo claude-sonnet-5-5   # comparação pontual de modelo

Conceito
--------
Três modos, do mais barato ao mais completo, para não gastar tokens à toa:

    --so-recuperacao   sem LLM e sem banco: só a busca na documentação (grátis)
    --lote             uma chamada por pergunta, pela Batch API (metade do preço)
    (padrão)           o laço completo do agente, pergunta a pergunta

Custo: a avaliação completa faz ~52 perguntas ao LLM (com o Haiku, na ordem de
US$ 0,50 a 1,00; o --lote custa metade e mede só a seleção). O --so-recuperacao
não custa nada. O relatório vai para relatorios/ (fora do Git).

Documentação: docs/agente/avaliacao.md § 6
"""
import argparse
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from src.agente.avaliacao.golden import CATEGORIAS, GOLDEN_PADRAO, carregar_golden
from src.agente.avaliacao.recuperacao import ResultadoRecuperacao, avaliar_recuperacao, busca_do_recuperador
from src.agente.avaliacao.relatorio import montar_relatorio
from src.config import FORNECEDORES_REAIS, RAIZ_PROJETO, load_config_agente, load_config_indice
from src.logger import configurar_logs, logger


def ler_argumentos(argv: list[str]) -> argparse.Namespace:
    """
    Opções da linha de comando.

    Example:
        >>> args = ler_argumentos(["--categoria", "documentacao", "--so-recuperacao"])
        >>> args.categoria, args.so_recuperacao, args.lote
        ('documentacao', True, False)
    """
    parser = argparse.ArgumentParser(prog="python -m src.agente.avaliacao", description="Avaliação do agente com o golden set")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PADRAO, help="arquivo JSON do golden set")
    parser.add_argument("--saida", type=Path, help="arquivo do relatório (padrão: relatorios/avaliacao_agente_<data>.md)")
    parser.add_argument("--categoria", choices=CATEGORIAS, help="avalia só uma categoria")
    parser.add_argument("--modelo", help="troca o modelo do LLM só nesta avaliação (ex.: claude-sonnet-5-5)")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--so-recuperacao", action="store_true", help="só hit@k e MRR do índice, sem LLM e sem banco")
    modo.add_argument("--lote", action="store_true", help="só a seleção de ferramentas, pela Batch API (50%% de desconto)")
    return parser.parse_args(argv)


def recuperacao_do_indice(casos, cfg_indice) -> tuple[ResultadoRecuperacao | None, str]:
    """
    hit@4 e MRR do índice salvo (o mesmo que o agente usa), e a descrição do índice.

    Returns:
        (resultado, descrição). Sem índice ou com índice de outro modelo: (None, motivo).

    Example:
        >>> import tempfile
        >>> from src.config import ConfigIndice
        >>> recuperacao_do_indice([], ConfigIndice(dir_indice=Path(tempfile.mkdtemp())))
        (None, 'sem índice (rode python main.py --indexar)')
    """
    # Por quê: import aqui para --help e os testes não carregarem o onnxruntime.
    from src.agente.rag.embeddings import EmbedderFastembed
    from src.agente.rag.recuperador import Recuperador
    from src.agente.rag.vector_store import abrir_indice

    store = abrir_indice(cfg_indice.vetores, cfg_indice.dir_indice)
    if store is None:
        return None, "sem índice (rode python main.py --indexar)"
    if store.modelo != cfg_indice.embeddings_modelo:
        return None, f"índice de outro modelo ({store.modelo})"
    recuperador = Recuperador(EmbedderFastembed(cfg_indice.embeddings_modelo, cfg_indice.dir_indice / "modelos"), store)
    descricao = f"{len(store)} trechos ({cfg_indice.vetores})"
    return avaliar_recuperacao(casos, busca_do_recuperador(recuperador), nome=f"índice do agente, limiar {recuperador.limiar}"), descricao


def executar(argv: list[str], cfg_indice=None) -> Path:
    """
    Roda a avaliação escolhida e grava o relatório.

    Args:
        argv: opções da linha de comando (ver ler_argumentos()).
        cfg_indice: onde está o índice. None = load_config_indice() (lê o .env).

    Returns:
        Caminho do relatório gerado.

    Example:
        >>> import tempfile
        >>> from src.config import ConfigIndice
        >>> pasta = Path(tempfile.mkdtemp())
        >>> saida = executar(["--so-recuperacao", "--saida", str(pasta / "r.md")], ConfigIndice(dir_indice=pasta))
        >>> saida.read_text(encoding="utf-8").splitlines()[2].endswith("Índice: sem índice (rode python main.py --indexar)")
        True
    """
    args = ler_argumentos(argv)
    casos = carregar_golden(args.golden, args.categoria)
    cfg_indice = cfg_indice or load_config_indice()
    recuperacao, descricao_indice = recuperacao_do_indice(casos, cfg_indice)
    recuperacoes = [recuperacao] if recuperacao else []
    info = {"Golden set": f"{len(casos)} casos", "Embeddings": cfg_indice.embeddings_modelo, "Índice": descricao_indice}
    if args.so_recuperacao:
        texto = montar_relatorio([], info, recuperacoes)
    else:
        cfg = load_config_agente()
        if args.modelo:
            cfg = replace(cfg, llm_modelo=args.modelo)
        if cfg.llm_fornecedor not in FORNECEDORES_REAIS:
            raise ValueError("a avaliação com o LLM usa um fornecedor real (anthropic ou openai); sem chave, use --so-recuperacao")
        if args.lote and cfg.llm_fornecedor != "anthropic":
            raise ValueError("o --lote usa a Batch API da Anthropic; com outro fornecedor, rode a avaliação completa")
        info = {"Modelo LLM": cfg.llm_modelo, "Esforço": cfg.esforco, **info}
        texto = _com_lote(casos, cfg, info, recuperacoes) if args.lote else _completa(casos, cfg, info, recuperacoes)
    saida = args.saida or RAIZ_PROJETO / "relatorios" / f"avaliacao_agente_{datetime.now():%Y%m%d_%H%M%S}.md"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(texto, encoding="utf-8")
    logger.info(f"Avaliação: casos={len(casos)} relatorio={saida}")
    return saida


def _completa(casos, cfg, info, recuperacoes) -> str:
    """Golden set completo no agente real, com o LLM espionado."""
    from src.agente.avaliacao.execucao import LLMEspiao, Referencias, avaliar_golden
    from src.agente.fabrica import criar_agente, llm_da_config
    from src.agente.ferramentas.catalogo import criar_registro

    consulta = _consulta(cfg)
    espiao = LLMEspiao(llm_da_config(cfg))
    agente = criar_agente(cfg, espiao, consulta)
    resultados = avaliar_golden(casos, agente, espiao, Referencias(criar_registro(consulta, cfg.max_linhas)))
    return montar_relatorio(resultados, info, recuperacoes)


def _com_lote(casos, cfg, info, recuperacoes) -> str:
    """Seleção de ferramentas na primeira chamada, pela Batch API."""
    import anthropic

    from src.agente.avaliacao.lote import metricas_do_lote, pedidos_do_lote, selecionar_em_lote
    from src.agente.fabrica import recuperador_da_documentacao
    from src.agente.ferramentas.catalogo import criar_registro
    from src.agente.llm.cliente_anthropic import ClienteAnthropic
    from src.agente.prompts import montar_system_prompt

    consulta = _consulta(cfg)
    registro = criar_registro(consulta, cfg.max_linhas, recuperador_da_documentacao(cfg))
    system = montar_system_prompt(date.today(), consulta.cobertura(), registro.nomes())
    pedidos = pedidos_do_lote(casos, ClienteAnthropic.de_config(cfg), system, registro.especificacoes())
    selecao = selecionar_em_lote(pedidos, anthropic.Anthropic(api_key=cfg.anthropic_api_key))
    return montar_relatorio([], info, recuperacoes, lote=metricas_do_lote(casos, selecao))


def _consulta(cfg):
    """ConsultaDados com o usuário só de leitura do agente (POL-01)."""
    from src.agente.ferramentas.consulta_dados import ConsultaDados
    from src.database.connection import DatabaseConnection

    return ConsultaDados.do_banco(DatabaseConnection(cfg.sql_connectionstring))


if __name__ == "__main__":
    configurar_logs("avaliacao")
    executar(sys.argv[1:])
