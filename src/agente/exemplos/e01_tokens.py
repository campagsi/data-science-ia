"""
Exemplo 01 — Quantos tokens custa uma pergunta ao agente.

Demonstra: o LLM cobra por token, e cada chamada reenvia tudo: o system
prompt, as especificações das ferramentas, o histórico e os resultados. Numa
pergunta com duas rodadas de ferramenta, o contexto é enviado três vezes.

Como rodar:  python -m src.agente.exemplos.e01_tokens
Observe:     (1) as especificações das ferramentas pesam mais que o system
             prompt; (2) a entrada cresce mais rápido que o número de rodadas.

Cuidado: o tiktoken é o tokenizador da OpenAI. Para o Claude (DA1), os
números são uma aproximação. O valor real vem na resposta da API
(usage.input_tokens / output_tokens). Na primeira execução, o tiktoken baixa
a codificação da internet e depois a guarda em cache.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_1.py
Documentação: docs/agente/seguranca-e-prompts.md § 8
"""
import json

# Trecho do system prompt de docs/agente/seguranca-e-prompts.md § 1. O texto
# final fica em src/agente/prompts.py, na Fase 3.
SYSTEM_PROMPT = """Você é o assistente analítico do projeto de monitoramento ambiental Data-Science-Ia.
Responde em português do Brasil a perguntas sobre as medições das estações, as
análises estatísticas, as anomalias e as regras do projeto.

REGRAS SOBRE NÚMEROS
1. Todo número sobre medições DEVE vir de uma ferramenta chamada nesta conversa.
   Nunca estime, nunca calcule de cabeça e nunca use conhecimento geral para preencher valores.
2. Sempre informe a unidade, o período e a quantidade de medições.
3. Em distribuições assimétricas, cite a mediana junto com a média."""

# Especificação de docs/agente/ferramentas.md § 1, como o LLM a recebe.
ESPECIFICACAO_RESUMO = {
    "name": "resumo_estatistico",
    "description": "Calcula estatísticas descritivas (quantidade, média, mediana, desvio padrão, "
    "variância, quartis, IQR, mínimo, máximo e número de anomalias) por estação e parâmetro, "
    "num período. Use para qualquer pergunta numérica sobre valores medidos. Não use para "
    "explicar regras (use buscar_documentacao).",
    "input_schema": {
        "type": "object",
        "properties": {
            "estacao": {"type": "string", "description": "Código da estação, ex.: EST-RJ-001. Omitir = todas."},
            "parametros": {"type": "array", "items": {"type": "string"},
                           "description": 'Códigos dos parâmetros, ex.: ["TIP-PH"]. Omitir = todos.'},
            "data_inicio": {"type": "string", "format": "date", "description": "AAAA-MM-DD. Sozinha = só esse dia."},
            "data_fim": {"type": "string", "format": "date", "description": "AAAA-MM-DD, inclusiva. Exige data_inicio."},
        },
    },
}

RESULTADO_TIPICO = {
    "filtros": {"estacao": None, "parametros": ["TIP-PH"], "data_inicio": "2026-06-01", "data_fim": "2026-06-30"},
    "linhas": [{"estacao": "Estação Integrada Guanabara Norte", "codigo": "TIP-PH", "parametro": "pH",
                "unidade": "pH", "quantidade": 1402, "media": 7.381, "mediana": 7.37, "desvio_padrao": 0.214,
                "minimo": 6.71, "maximo": 9.3, "anomalias": 11}],
}

RESPOSTA_TIPICA = (
    "Em junho de 2026, na estação Estação Integrada Guanabara Norte (EST-RJ-001), o pH médio "
    "foi 7,38 (mediana 7,37; desvio padrão 0,21; 1.402 medições). Foram sinalizadas 11 anomalias."
)

# Por quê: o catálogo completo terá de 6 a 12 ferramentas. Para a estimativa,
# todas são tratadas como do tamanho de resumo_estatistico.
FERRAMENTAS_NO_CATALOGO = 6


def tokens_entrada_acumulados(contexto_fixo: int, por_resultado: int, rodadas: int) -> int:
    """
    Tokens de entrada somados em todas as chamadas ao LLM de uma pergunta.

    A chamada k reenvia o contexto fixo mais os resultados das k-1 rodadas de
    ferramenta anteriores: soma = rodadas·fixo + resultado·rodadas·(rodadas-1)/2.

    Args:
        contexto_fixo: system prompt + especificações + histórico + pergunta.
        por_resultado: tokens de cada rodada de resultados de ferramenta.
        rodadas: chamadas ao LLM na pergunta (1 = resposta direta).

    Returns:
        Total de tokens de entrada.

    Example:
        >>> tokens_entrada_acumulados(3000, 500, rodadas=1)
        3000
        >>> tokens_entrada_acumulados(3000, 500, rodadas=2)   # 3000 + (3000 + 500)
        6500
        >>> tokens_entrada_acumulados(3000, 500, rodadas=3)   # + (3000 + 500 + 500)
        10500
    """
    if rodadas < 1:
        raise ValueError("rodadas deve ser pelo menos 1")
    return rodadas * contexto_fixo + por_resultado * rodadas * (rodadas - 1) // 2


def main() -> None:
    """Imprime os tokens de cada parte da pergunta e o total acumulado por rodada."""
    # Por quê: import aqui, e não no topo, para o módulo poder ser importado
    # (ex.: pelo teste dos doctests) mesmo sem o tiktoken instalado.
    import tiktoken

    try:
        codificacao = tiktoken.get_encoding("o200k_base")
    except Exception as erro:  # sem internet na primeira execução
        print(f"Não foi possível carregar a codificação do tiktoken ({type(erro).__name__}).")
        print("Na primeira execução, ele baixa o arquivo da internet. Conecte-se e rode de novo.")
        return

    def contar(texto: str) -> int:
        """Tokens do texto na codificação o200k_base."""
        return len(codificacao.encode(texto))

    system = contar(SYSTEM_PROMPT)
    especificacao = contar(json.dumps(ESPECIFICACAO_RESUMO, ensure_ascii=False))
    especificacoes = especificacao * FERRAMENTAS_NO_CATALOGO
    pergunta = contar("Qual foi o pH médio em junho e houve anomalias?")
    resultado = contar(json.dumps(RESULTADO_TIPICO, ensure_ascii=False))
    saida = contar(RESPOSTA_TIPICA)

    print("Tokens por parte (tiktoken o200k_base; para o Claude, é aproximado):")
    print(f"  system prompt (trecho)                {system:>6}")
    print(f"  1 especificação de ferramenta         {especificacao:>6}")
    print(f"  {FERRAMENTAS_NO_CATALOGO} especificações                      {especificacoes:>6}")
    print(f"  pergunta                              {pergunta:>6}")
    print(f"  resultado de resumo_estatistico       {resultado:>6}")
    print(f"  resposta final                        {saida:>6}")

    # Exemplo de caracteres por token: português gasta mais tokens que inglês.
    print(f"\nCaracteres por token na resposta: {len(RESPOSTA_TIPICA) / saida:.1f}")

    contexto_fixo = system + especificacoes + pergunta
    print("\nEntrada acumulada por pergunta, conforme as rodadas (o contexto é reenviado):")
    for rodadas in (1, 2, 3):
        total = tokens_entrada_acumulados(contexto_fixo, resultado, rodadas)
        print(f"  {rodadas} chamada(s) ao LLM: {total:>6} tokens de entrada")

    # Exercício (guia-estudos.md § 6, Fase 1): multiplique pelo preço por
    # milhão de tokens do modelo escolhido (página de preços da Anthropic).
    # Os preços mudam, por isso não ficam no código.
    tipico = tokens_entrada_acumulados(contexto_fixo, resultado, rodadas=2)
    print(f"\n100 perguntas típicas (2 chamadas): ~{100 * tipico:,} tokens de entrada e "
          f"~{100 * saida:,} de saída".replace(",", "."))


if __name__ == "__main__":
    main()
