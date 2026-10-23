"""
Exemplo 06 — O agente completo, offline.

Demonstra: o laço inteiro do Agente (orquestrador.py) com os guardrails, sem
rede, sem chave e sem banco. O LLM é roteirizado (as respostas são escritas
aqui) e os dados são os de exemplo em memória (pH 7,0 a 7,6 em 01/06/2026).

Três perguntas:
    1. numérica: o LLM chama resumo_estatistico e responde com o número;
    2. com CPF digitado: a pergunta chega MASCARADA ao LLM (POL-02);
    3. com número inventado: a verificação pede UMA correção ao LLM (POL-03).

Como rodar:  python -m src.agente.exemplos.e06_agente_offline
Observe:     as fontes montadas pelo código (POL-04), o que o LLM recebeu na
             pergunta 2 e a mensagem de sistema enviada na pergunta 3.

Lição (limitação da heurística da POL-03): com "7,9" no lugar de "8,4", a
verificação NÃO pede correção, porque 7,9 aparece nos resultados como limite
superior do IQR (7,45 + 1,5 × 0,3). Um número inventado que coincide com outro
valor do resultado passa. Por isso a verificação complementa, e não substitui,
o prompt e a avaliação (Fase 8).

Documentação: docs/agente/arquitetura.md § 5 e docs/agente/guardrails-e-owasp.md § 9
"""
from src.agente.contratos import ChamadaFerramenta
from src.agente.fabrica import criar_agente
from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
from src.agente.llm.base import RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado
from src.config import ConfigAgente


def pedir_resumo(id_: str) -> RespostaLLM:
    """Resposta roteirizada pedindo o resumo estatístico do pH."""
    return RespostaLLM(chamadas=[ChamadaFerramenta(id_, "resumo_estatistico", {"parametros": ["TIP-PH"]})], motivo_parada="ferramentas")


def main() -> None:
    """Faz as três perguntas e imprime respostas, fontes e o que o LLM recebeu."""
    llm = LLMRoteirizado([
        pedir_resumo("c1"), RespostaLLM(texto="O pH médio foi 7,3 (mediana 7,3; 4 medições)."),
        RespostaLLM(texto="Não tenho acesso a dados pessoais; posso falar das medições."),
        pedir_resumo("c2"), RespostaLLM(texto="O pH médio foi 8,4."), RespostaLLM(texto="O pH médio foi 7,3 (4 medições)."),
    ])
    agente = criar_agente(ConfigAgente("simulado"), llm, consulta_de_exemplo())

    for numero, pergunta in enumerate(
        ["Qual o pH médio?", "Meu CPF é 529.982.247-25. Qual o pH?", "E o pH médio, de novo?"], start=1
    ):
        antes = len(llm.chamadas_recebidas)
        resposta = agente.perguntar(pergunta)
        print(f"\n{numero}. Você: {pergunta}")
        print(f"   Agente: {resposta.texto}")
        print(f"   Fontes: {[f.descricao for f in resposta.fontes]}")
        recebido = llm.chamadas_recebidas[antes]
        print(f"   O LLM recebeu a pergunta como: {recebido.mensagens[-1].texto!r}")
        ultimas = llm.chamadas_recebidas[antes:]
        sistemas = [m.texto for e in ultimas for m in e.mensagens if m.papel == "sistema"]
        if sistemas:
            print(f"   Mensagem de sistema (POL-03): {sistemas[-1][:110]}...")


if __name__ == "__main__":
    main()
