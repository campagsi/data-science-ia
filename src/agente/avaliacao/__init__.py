"""
Avaliação do agente (Fase 8): golden set, métricas, execução, relatório e lote.

    golden.py       perguntas de referência validadas com Pydantic
    metricas.py     precisão, recall, hit@k, MRR, matriz de recusa (funções puras)
    recuperacao.py  hit@k e MRR sem LLM; TF-IDF, embeddings e híbrido (RRF) do e08
    execucao.py     espião do LLM, captura do log e conferência de cada resposta
    relatorio.py    métricas contra as metas e as falhas uma a uma
    lote.py         seleção de ferramentas pela Batch API (50% de desconto)
    __main__.py     python -m src.agente.avaliacao

Documentação: docs/agente/avaliacao.md
"""
from src.agente.avaliacao.golden import CasoGolden, carregar_golden

__all__ = ["CasoGolden", "carregar_golden"]
