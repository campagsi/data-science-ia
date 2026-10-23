"""
Exemplo 10 — Laudo few-shot de anomalias, validado com Pydantic.

Demonstra: três anomalias sintéticas de turbidez passam pelo mesmo caminho do
python main.py --laudo (contexto → prompt few-shot → JSON → contrato):

    A. pico isolado de 480 NTU às 03:00, sem chuva        → esperado: falha_sensor
    B. subida gradual até 95 NTU depois de 18 mm de chuva  → esperado: evento_real
    C. 60 NTU sem vizinhos (lacuna de 4 h)                 → esperado: inconclusivo

Sem chave (padrão), o LLM é roteirizado com respostas que mostram o que o
contrato faz com cada erro (em ordem de data): A válida, C com um número
inventado na justificativa (POL-03) e B com o campo errado ("nivel" no lugar
de "severidade", a lição do ia_gen_2.py). Com --real, responde o LLM do .env.

Como rodar:  python -m src.agente.exemplos.e10_laudo_json           (sem chave, sem custo)
             python -m src.agente.exemplos.e10_laudo_json --real    (o LLM do .env, alguns centavos)
Observe:     (1) o contexto enviado de cada anomalia; (2) os descartes com a
             política e o motivo, sem o texto do LLM; (3) com --real, se a causa
             bate com o esperado.

Documentação: docs/agente/seguranca-e-prompts.md § 9
"""
import sys
from datetime import datetime, timedelta

from src.agente.laudo.contexto import anomalias_com_contexto
from src.agente.laudo.gerador import gerar_laudos
from src.agente.llm.base import RespostaLLM
from src.agente.llm.roteirizado import LLMRoteirizado

ESPERADO = {"REG-A-03": "falha_sensor", "REG-B-15": "evento_real", "REG-C-09": "inconclusivo"}


def medicoes_sinteticas() -> list[dict]:
    """Um dia de turbidez e chuva a cada 30 min, com as três anomalias descritas no topo."""
    linhas = []
    for ponto in range(48):
        instante = datetime(2026, 6, 10) + timedelta(minutes=30 * ponto)
        hora = instante.hour + instante.minute / 60
        if 7 <= hora < 9 or 9 < hora <= 11:
            continue  # C: lacuna em volta das 09:00
        turbidez, chuva = 5.0 + ponto % 3, 0.0
        if instante.hour == 3 and instante.minute == 0:
            turbidez = 480.0  # A
        if 12 <= hora <= 15:
            turbidez, chuva = {12: 20.0, 13: 41.0, 14: 70.0, 15: 95.0}.get(int(hora), 30.0), 3.0  # B
        if hora == 9:
            turbidez = 60.0  # C
        bloco = "A" if hora < 6 else "B" if hora >= 12 else "C"
        registro = f"REG-{bloco}-{instante.hour:02d}" if instante.minute == 0 else f"REG-{bloco}-{instante.hour:02d}m"
        for codigo, nome, unidade, valor in (("TIP-TUR", "Turbidez", "NTU", turbidez), ("TIP-CHU", "Precipitação", "mm", chuva)):
            linhas.append({
                "estacao_codigo": "EST-1", "estacao": "Estação sintética", "codigo_registro": registro, "data_hora": instante,
                "codigo_parametro": codigo, "parametro": nome, "unidade_medida": unidade, "valor": valor,
            })
    return linhas


def main(argv: list[str]) -> None:
    """Gera os laudos das três anomalias e mostra o contexto, o resultado e os descartes."""
    medicoes = medicoes_sinteticas()
    # Só a turbidez: nas leituras de B, a chuva também é anômala (3 mm a cada 30 min, num dia seco).
    anomalias = [a for a in anomalias_com_contexto(medicoes, medicoes) if a.registro in ESPERADO and a.parametro == "TIP-TUR"]
    if "--real" in argv:
        from src.agente.fabrica import llm_da_config
        from src.config import load_config_agente

        llm = llm_da_config(load_config_agente())
    else:
        llm = LLMRoteirizado([  # em ordem de data: A, C, B
            RespostaLLM(texto='{"registro": "REG-A-03", "causa_provavel": "falha_sensor", "severidade": 3, "justificativa": "Pico isolado de 480 NTU sem chuva."}'),
            RespostaLLM(texto='{"registro": "REG-C-09", "causa_provavel": "inconclusivo", "severidade": 2, "justificativa": "Sem vizinhos; o normal seria 12 NTU."}'),
            RespostaLLM(texto='```json\n{"registro": "REG-B-15", "causa_provavel": "evento_real", "nivel": 2, "justificativa": "Subida gradual após chuva."}\n```'),
        ])
    for resultado in gerar_laudos(llm, anomalias):
        a, v = resultado.anomalia, resultado.validacao
        print(f"--- {a.registro} (esperado: {ESPERADO[a.registro]})\n{a.texto}")
        if v.valido:
            print(f"✔ {v.laudo.causa_provavel}, severidade {v.laudo.severidade}: {v.laudo.justificativa}\n")
        else:
            print(f"✘ descartado pela {v.politica}: {v.motivo}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
