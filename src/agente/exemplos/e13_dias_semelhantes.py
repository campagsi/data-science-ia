"""
Exemplo 13 — Dias semelhantes: embedding do resumo textual × vetor numérico de 48 pontos.

Demonstra: os dois jeitos de transformar um dia em vetor (rag.md § 8) sobre 30
dias sintéticos de junho, montados para os dois discordarem de propósito:

    dias de chuva forte (3, 4, 10, 17, 18, 25): curva de temperatura achatada,
        umidade alta e turbidez alta (anomalias)
    dia 12: nublado, curva achatada, SEM chuva     → parece chuvoso só pelo formato
    dia 21: chuva forte à noite, curva normal      → parece chuvoso só pelo texto

1. vizinhos do dia 03/06 pelo TEXTO (embedding dos resumos diários);
2. vizinhos pelo PERFIL (48 pontos de temperatura normalizados, distância euclidiana);
3. KMeans dos perfis, com a silhueta e a inércia de cada k (o "cotovelo").

Como rodar:  python -m src.agente.exemplos.e13_dias_semelhantes            (modelo real de embeddings)
             python -m src.agente.exemplos.e13_dias_semelhantes --simulado (embedder simulado, sem modelo)
Observe:     (1) o texto acha o dia 21 (choveu) e não o 12; o perfil acha o 12
             (mesmo formato de curva) e não o 21; (2) a silhueta mais alta indica
             quantos "formatos de dia" existem (aqui, 2: dia normal e dia achatado).

Documentação: docs/agente/rag.md § 8
"""
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from src.agente.dias.indice import abrir_busca_de_dias, indexar_dias
from src.agente.dias.perfis import agrupar_perfis, perfis_diarios, vizinhos_por_perfil
from src.agente.dias.resumos import resumos_diarios
from src.agente.rag.embeddings import EmbedderSimulado

DIAS_DE_CHUVA = {3, 4, 10, 17, 18, 25}
DIA_NUBLADO, DIA_CHUVA_NOTURNA = 12, 21
NOMES = {
    "TIP-TMP": ("Temperatura do ar", "°C"),
    "TIP-CHU": ("Precipitação", "mm"),
    "TIP-UMI": ("Umidade relativa do ar", "%"),
    "TIP-TUR": ("Turbidez", "NTU"),
}


def medicoes_sinteticas() -> list[dict]:
    """30 dias de junho/2026, a cada 30 minutos, com os dias especiais descritos no topo."""
    aleatorio = np.random.default_rng(42)
    linhas = []
    for dia in range(1, 31):
        chuvoso, achatado = dia in DIAS_DE_CHUVA, dia in DIAS_DE_CHUVA or dia == DIA_NUBLADO
        for ponto in range(48):
            instante = datetime(2026, 6, dia) + timedelta(minutes=30 * ponto)
            ciclo = np.sin(np.pi * ponto / 47)
            valores = {
                "TIP-TMP": (18 + 1.5 * ciclo if achatado else 20 + 8 * ciclo) + aleatorio.normal(0, 0.3),
                "TIP-CHU": (35 / 48 if chuvoso else 0.0) + (30 / 8 if dia == DIA_CHUVA_NOTURNA and ponto >= 40 else 0.0),
                "TIP-UMI": (95 if chuvoso or dia == DIA_NUBLADO else 70) + aleatorio.normal(0, 2),
                "TIP-TUR": (40 if chuvoso else 5) + aleatorio.normal(0, 1),
            }
            for codigo, valor in valores.items():
                linhas.append({
                    "estacao_codigo": "EST-1", "estacao": "Estação sintética", "codigo_registro": f"R-{dia:02d}-{ponto:02d}",
                    "data_hora": instante, "codigo_parametro": codigo, "parametro": NOMES[codigo][0],
                    "unidade_medida": NOMES[codigo][1], "valor": round(float(valor), 2),
                })
    return linhas


def main(argv: list[str]) -> None:
    """Compara os vizinhos de 03/06 pelos dois métodos e agrupa os perfis com KMeans."""
    if "--simulado" in argv:
        embedder = EmbedderSimulado()
    else:
        from src.agente.rag.embeddings import EmbedderFastembed
        from src.config import load_config_indice

        cfg = load_config_indice()
        embedder = EmbedderFastembed(cfg.embeddings_modelo, cfg.dir_indice / "modelos")
    medicoes = medicoes_sinteticas()
    referencia = date(2026, 6, 3)

    resumos = {r.dia: r for r in resumos_diarios(medicoes)}
    print(f"Resumo de {referencia:%d/%m}:\n  {resumos[referencia].conteudo}\n")

    pasta = Path(tempfile.mkdtemp())
    indexar_dias(medicoes, embedder, pasta)
    busca = abrir_busca_de_dias(embedder, pasta)
    por_texto = [date.fromisoformat(t.secao) for t in busca.vizinhos(resumos[referencia].conteudo, "EST-1", referencia.isoformat(), 6)]
    print("1. Vizinhos pelo TEXTO (embedding):", ", ".join(f"{d.day:02d}" for d in por_texto))

    perfis = perfis_diarios(medicoes)
    por_perfil = [d for d, _ in vizinhos_por_perfil(perfis, "EST-1", referencia, 6)]
    print("2. Vizinhos pelo PERFIL (48 pontos):", ", ".join(f"{d.day:02d}" for d in por_perfil))
    comuns = set(por_texto) & set(por_perfil)
    print(f"   Em comum: {len(comuns)} de 6. Dia 12 (nublado): texto={date(2026, 6, 12) in por_texto} perfil={date(2026, 6, 12) in por_perfil}."
          f" Dia 21 (chuva à noite): texto={date(2026, 6, 21) in por_texto} perfil={date(2026, 6, 21) in por_perfil}.")

    agrupamento = agrupar_perfis(np.array(list(perfis.values())))
    print("\n3. KMeans dos perfis")
    for k in agrupamento.silhuetas:
        print(f"   k={k}  silhueta={agrupamento.silhuetas[k]:.2f}  inércia={agrupamento.inercias[k]:.1f}")
    grupos: dict[int, list[int]] = {}
    for (_, dia), rotulo in zip(perfis, agrupamento.rotulos):
        grupos.setdefault(int(rotulo), []).append(dia.day)
    print(f"   k escolhido = {agrupamento.k}: " + " | ".join(f"grupo {g}: {', '.join(map(str, dias))}" for g, dias in sorted(grupos.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
