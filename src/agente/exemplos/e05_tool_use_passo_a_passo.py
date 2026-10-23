"""
Exemplo 05 — Um ciclo de tool use, mensagem por mensagem.

Demonstra: o LLM não executa nada. Ele PEDE uma ferramenta; o nosso código
executa e devolve o resultado; o LLM então redige a resposta. São 4 mensagens:

    1. usuário  → a pergunta
    2. LLM      → pede resumo_estatistico(parametros=["TIP-PH"])     (roteirizado)
    3. código   → executa a ferramenta e devolve o JSON (tool_result)
    4. LLM      → redige a resposta com o número do resultado        (roteirizado)

Também mostra como cada mensagem fica no formato da API da Anthropic, que é o
que o adaptador (llm/cliente_anthropic.py) envia ao Claude.

Como rodar:  python -m src.agente.exemplos.e05_tool_use_passo_a_passo
Observe:     quem produz cada mensagem, e que o resultado da ferramenta volta
             ao LLM como DADO (tool_result), nunca no system prompt.

Sem rede, sem chave e sem banco (LLM roteirizado e dados de exemplo em memória).
Documentação: docs/agente/arquitetura.md § 5
"""
import json

from src.agente.contratos import ChamadaFerramenta, Mensagem
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.llm.base import RespostaLLM
from src.agente.llm.cliente_anthropic import mensagens_para_api
from src.agente.llm.roteirizado import LLMRoteirizado


def mostrar(numero: int, autor: str, mensagem: Mensagem) -> None:
    """Imprime uma mensagem no formato interno e no formato da API."""
    print(f"\n{numero}. [{autor}] papel={mensagem.papel}")
    print("   formato da API:", json.dumps(mensagens_para_api([mensagem])[0], ensure_ascii=False)[:300])


def main() -> None:
    """Percorre o ciclo e imprime as 4 mensagens."""
    registro = criar_registro(consulta_de_exemplo())
    llm = LLMRoteirizado([
        RespostaLLM(chamadas=[ChamadaFerramenta("toolu_1", "resumo_estatistico", {"parametros": ["TIP-PH"]})], motivo_parada="ferramentas"),
        RespostaLLM(texto="O pH médio foi 7,3, com mediana 7,3 (4 medições)."),
    ])

    pergunta = Mensagem.usuario("Qual o pH médio?")
    mostrar(1, "usuário", pergunta)

    pedido = llm.gerar("system", [pergunta], registro.especificacoes())
    mensagem_pedido = Mensagem.assistente(chamadas=pedido.chamadas)
    mostrar(2, "LLM pede a ferramenta", mensagem_pedido)

    resultados = [registro.executar(chamada) for chamada in pedido.chamadas]
    mensagem_resultado = Mensagem.ferramenta(resultados)
    mostrar(3, "nosso código executa", mensagem_resultado)

    final = llm.gerar("system", [pergunta, mensagem_pedido, mensagem_resultado], registro.especificacoes())
    mostrar(4, "LLM responde", Mensagem.assistente(final.texto))
    print("\nResposta final:", final.texto)


if __name__ == "__main__":
    main()
