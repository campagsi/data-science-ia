"""
Catálogo das políticas de segurança do agente e o registro de cada acionamento.

Conceito
--------
Política é a REGRA ("o agente não revela dado pessoal"); guardrail é o
MECANISMO que a faz valer (a máscara de CPF, o usuário do banco só de leitura).
Toda vez que um guardrail age, isso vira uma linha de log com o id da política
(política POL-13, rastreabilidade): dá para contar, na avaliação, quantas
vezes cada proteção foi necessária e investigar os casos.

O id é conferido contra o catálogo: um guardrail não pode registrar uma
política que não existe (erro de digitação vira erro, e não log errado).

Onde estudar: docs/agente/guardrails-e-owasp.md § 1 e § 9
"""
from src.logger import registrar_guardrail

POLITICAS: dict[str, str] = {
    "POL-01": "Somente leitura",
    "POL-02": "Proteção de dados pessoais (LGPD)",
    "POL-03": "Números só de ferramentas",
    "POL-04": "Fontes verdadeiras",
    "POL-05": "Entrada controlada",
    "POL-06": "Argumentos validados",
    "POL-07": "Consumo limitado",
    "POL-08": "Dados externos não são ordens",
    "POL-09": "Saída segura na web",
    "POL-10": "Segredos protegidos",
    "POL-11": "Escopo do assunto",
    "POL-12": "Dependências confiáveis",
    "POL-13": "Rastreabilidade",
}


def registrar_acionamento(politica: str, conversa_id: str, **detalhes) -> None:
    """
    Registra no log (WARNING) que um guardrail da política agiu.

    Args:
        politica: id do catálogo, ex.: "POL-03".
        conversa_id: conversa em que aconteceu.
        **detalhes: pares curtos e sem dado pessoal, ex.: acao="correcao".

    Raises:
        ValueError: política fora do catálogo.

    Example:
        >>> registrar_acionamento("POL-99", "c-1")
        Traceback (most recent call last):
        ...
        ValueError: política desconhecida: POL-99
    """
    if politica not in POLITICAS:
        raise ValueError(f"política desconhecida: {politica}")
    registrar_guardrail(politica, conversa_id, **detalhes)
