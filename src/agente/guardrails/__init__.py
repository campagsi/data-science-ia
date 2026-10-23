"""
Guardrails do agente: os mecanismos que aplicam as políticas de segurança.

- politicas.py: catálogo POL-01 a POL-13 e o registro de cada acionamento (POL-13);
- entrada.py: validação e máscara da pergunta (POL-05, POL-02);
- orcamento.py: limites de chamadas, tokens e tempo por pergunta (POL-07);
- saida.py: verificação dos números e máscara da resposta (POL-03, POL-02).

Conceitos (política × guardrail, fraco × forte): docs/agente/guardrails-e-owasp.md
"""
