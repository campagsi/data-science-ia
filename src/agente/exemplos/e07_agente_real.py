"""
Exemplo 07 — A mesma pergunta com o Claude de verdade.

Demonstra: o agente com o LLM real (Claude Haiku 5.5, DA9) e o banco real,
lido pelo usuário só de leitura do agente. Mostra a resposta, as fontes e o
consumo de tokens, que é o que define o custo.

Precisa no .env: AGENTE_LLM_FORNECEDOR=anthropic, AGENTE_LLM_MODELO=claude-haiku-5-5,
ANTHROPIC_API_KEY e AGENTE_SQL_CONNECTIONSTRING (docs/manual-execucao.md § 4).

Cuidado: cada execução CUSTA (por volta de US$ 0,001 por pergunta no Haiku).
Configure um limite de gasto no Console da Anthropic antes.

Como rodar:  python -m src.agente.exemplos.e07_agente_real "Qual o pH médio em junho?"
Observe:     as ferramentas escolhidas pelo LLM (nas fontes) e os tokens de
             entrada: crescem a cada rodada, porque o contexto é reenviado.
             O log da execução fica em logs/ (etapa "agente").

Documentação: docs/agente/bibliotecas.md § 4.1
"""
import sys

from src.logger import configurar_logs

PERGUNTA_PADRAO = "Qual foi o pH médio em junho de 2026 e houve anomalias?"


def main(argv: list[str]) -> None:
    """Faz a pergunta da linha de comando (ou a padrão) ao agente real."""
    configurar_logs("agente")
    from src.agente import criar_agente

    pergunta = " ".join(argv) or PERGUNTA_PADRAO
    resposta = criar_agente().perguntar(pergunta)
    print(f"\nVocê: {pergunta}\n\nAgente: {resposta.texto}\n")
    print("Fontes:", *(f"\n  • {f.descricao}" for f in resposta.fontes))
    print(f"\nTokens: {resposta.tokens_entrada} de entrada, {resposta.tokens_saida} de saída; {resposta.latencia_ms} ms")


if __name__ == "__main__":
    main(sys.argv[1:])
