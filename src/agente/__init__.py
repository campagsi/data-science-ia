"""
Agente analítico de dados ambientais (docs/agente).

Conceito
--------
Um agente é um laço "LLM decide → ferramenta executa → LLM lê o resultado",
repetido até haver uma resposta final. O LLM interpreta a pergunta e redige
a resposta. Os números vêm sempre das ferramentas (código Python testado), e
as explicações vêm da documentação do projeto (RAG).

Organização do pacote:

- contratos.py: tipos trocados entre as camadas (Mensagem, ChamadaFerramenta...);
- conversa.py: histórico curto de cada conversa;
- llm/: interface do LLM e as implementações (simulada e Anthropic);
- guardrails/: as políticas de segurança aplicadas em código;
- orquestrador.py: o laço do agente; prompts.py: o system prompt; fabrica.py: a montagem;
- ferramentas/: funções de dados expostas ao LLM (Fase 2);
- rag/: indexação e busca na documentação (Fase 4);
- exemplos/: scripts de estudo (docs/agente/guia-estudos.md § 5).

Ponto de entrada: criar_agente() (fabrica.py), que monta o agente a partir do .env.

Documentação: docs/agente/README.md e docs/agente/arquitetura.md
"""
from src.agente.fabrica import criar_agente

__all__ = ["criar_agente"]
