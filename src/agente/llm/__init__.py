"""
Clientes de LLM do agente.

Conceito
--------
O orquestrador conhece só a interface LLMClient (base.py). Cada fornecedor
tem um adaptador que traduz o formato interno para o seu formato de tool use
e de volta. O LLMRoteirizado (roteirizado.py) devolve respostas pré-definidas,
para testes e estudo sem rede e sem chave.

Documentação: docs/agente/arquitetura.md § 4
"""
from src.agente.llm.base import ErroProvedorLLM, LLMClient, RespostaLLM
from src.agente.llm.roteirizado import EntradaLLM, LLMRoteirizado, RoteiroEsgotado

__all__ = [
    "EntradaLLM",
    "ErroProvedorLLM",
    "LLMClient",
    "LLMRoteirizado",
    "RespostaLLM",
    "RoteiroEsgotado",
]
