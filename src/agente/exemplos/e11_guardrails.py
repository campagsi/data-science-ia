"""
Exemplo 11 — Os guardrails em ação.

Demonstra: cada guardrail da Fase 3 sendo acionado, com a linha de log que ele
gera ("guardrail=POL-xx", política POL-13). O LLM é roteirizado para provocar
cada situação:

    POL-05  pergunta longa demais         → recusada antes do LLM
    POL-02  CPF na pergunta               → mascarado antes do LLM e do log
    POL-07  LLM pedindo ferramentas sem parar → resposta forçada sem ferramentas
    POL-03  número inventado              → pedido de correção, depois aviso
    POL-11  recusa do modelo              → mensagem padrão
    POL-10  falha do provedor             → mensagem amigável, log só com o tipo do erro

Como rodar:  python -m src.agente.exemplos.e11_guardrails
Observe:     as linhas WARNING "Agente: guardrail=..." no console. Os arquivos
             de log vão para uma pasta temporária, e não para logs/.

Documentação: docs/agente/guardrails-e-owasp.md § 8 e § 9
"""
import tempfile
from pathlib import Path

from src.agente.contratos import ChamadaFerramenta
from src.agente.fabrica import criar_agente
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.guardrails.entrada import PerguntaInvalida
from src.agente.llm.base import ErroProvedorLLM, RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.config import ConfigAgente
from src.logger import configurar_logs


def agente(roteiro: list, **limites):
    """Agente offline com o roteiro dado."""
    return criar_agente(ConfigAgente("simulado", **limites), LLMRoteirizado(roteiro), consulta_de_exemplo())


def secao(titulo: str) -> None:
    """Separa as demonstrações no console."""
    print(f"\n=== {titulo} ===")


def main() -> None:
    """Aciona cada guardrail e mostra o resultado."""
    configurar_logs("agente", pasta=Path(tempfile.mkdtemp(prefix="e11_logs_")))

    secao("POL-05: pergunta longa demais")
    try:
        agente([]).perguntar("x" * 1001)
    except PerguntaInvalida as erro:
        print("Recusada:", erro)

    secao("POL-02: CPF na pergunta")
    print(agente([RespostaLLM(texto="Não tenho acesso a dados pessoais.")]).perguntar("Meu CPF é 529.982.247-25").texto)

    secao("POL-07: LLM pedindo ferramentas sem parar (limite de 2)")
    pedidos = [RespostaLLM(chamadas=[ChamadaFerramenta(f"c{i}", "listar_parametros", {})], motivo_parada="ferramentas") for i in range(2)]
    print(agente([*pedidos, RespostaLLM(texto="Respondo com o que tenho.")], max_ferramentas=2).perguntar("Tudo!").texto)

    secao("POL-03: número inventado")
    print(agente([RespostaLLM(texto="O pH médio foi 6,1."), RespostaLLM(texto="O pH médio foi 6,1.")]).perguntar("pH médio?").texto)

    secao("POL-11: recusa do modelo")
    print(agente([RespostaLLM(motivo_parada="recusa")]).perguntar("Pedido fora do escopo").texto)

    secao("POL-10: falha do provedor")
    print(agente([ErroProvedorLLM("APIConnectionError")]).perguntar("pH?").texto)


if __name__ == "__main__":
    main()
