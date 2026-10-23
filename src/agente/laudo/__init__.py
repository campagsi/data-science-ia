"""
Laudo de anomalias em JSON (Fase 11): few-shot, saída estruturada e validação.

    contexto.py   as anomalias do período e o contexto vizinho de cada uma
    contrato.py   LaudoAnomalia (Pydantic, extra="forbid") e a validação da resposta
    gerador.py    prompt few-shot, uma chamada por anomalia, CSV e Markdown sinalizados como IA

Uso: python main.py --laudo --inicio 2026-06-01 --fim 2026-06-30 (relatorios/).

Documentação: docs/agente/seguranca-e-prompts.md § 9
"""
