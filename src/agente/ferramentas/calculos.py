"""
Cálculos das ferramentas descritivas, em funções puras.

Conceito
--------
Função pura recebe dados e devolve dados, sem acessar banco, rede ou relógio.
Por isso é testável com uma lista pequena de medições e um resultado
calculado à mão, e o mesmo teste vale para qualquer banco.

Estatística descritiva (módulo 3, estatistica_IA):

- tendência central: média e mediana. Com distribuições assimétricas (pH com
  assimetria 3,5, turbidez 16,7), a média é puxada pelos picos e a mediana não;
- dispersão: desvio padrão, variância, quartis (Q1, Q3) e IQR = Q3 - Q1;
- anomalias: regra IQR (fora de [Q1 - 1,5·IQR, Q3 + 1,5·IQR]) e Z-Score
  (|valor - média| / desvio > 3).

Nada é recalculado aqui: estatísticas e anomalias vêm do
AnaliticsService.analisar_medicoes(), já testado contra
sql/queries_analiticas.sql. Este módulo só renomeia, filtra, ordena e agrega
no tempo (pandas resample/groupby).

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA/estatistica_IA/aplicacao_estatistica.py
Documentação: docs/agente/ferramentas.md § 4 e docs/analise-estatistica.md
"""
from collections import Counter
from datetime import date, timedelta

import pandas as pd

from src.agente.ferramentas.base import ErroDeRegra
from src.services.analytics_service import AnaliticsService

# Regra do pandas para cada granularidade. "W-MON" com label/closed "left" =
# semanas que começam na segunda-feira, rotuladas pela própria segunda.
REGRAS_RESAMPLE = {"hora": "h", "dia": "D", "semana": "W-MON", "mes": "MS"}
AGREGACOES = {"media": "mean", "mediana": "median", "minimo": "min", "maximo": "max", "soma": "sum"}
MAXIMO_PONTOS_SERIE = 200

# Chaves do relatório do AnaliticsService → chaves curtas do retorno da ferramenta.
_CHAVES_RESUMO = {
    "Estação": "estacao",
    "Código": "codigo",
    "Parâmetro": "parametro",
    "Unidade": "unidade",
    "Quantidade": "quantidade",
    "Média": "media",
    "Mediana": "mediana",
    "Desvio Padrão": "desvio_padrao",
    "Variância": "variancia",
    "Q1": "q1",
    "Q3": "q3",
    "IQR": "iqr",
    "Mínimo": "minimo",
    "Máximo": "maximo",
    "Limite Inferior": "limite_inferior",
    "Limite Superior": "limite_superior",
    "Anomalias": "anomalias",
}


def resumir(medicoes: list[dict]) -> list[dict]:
    """
    Estatísticas por estação e parâmetro, com chaves curtas.

    Args:
        medicoes: linhas no formato de LeituraRepository.get_medicoes().

    Returns:
        Uma linha por estação + parâmetro (docs/agente/ferramentas.md § 4.3).
        Lista vazia se não houver medições.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import medicoes_de_exemplo
        >>> linhas = medicoes_de_exemplo([7.0, 7.2, 7.4, 7.6])
        >>> resumo = resumir(linhas)[0]
        >>> round(resumo["media"], 3), round(resumo["mediana"], 3), resumo["quantidade"]
        (7.3, 7.3, 4)
    """
    analise = AnaliticsService.analisar_medicoes(medicoes)
    return [{curta: linha[longa] for longa, curta in _CHAVES_RESUMO.items()} for linha in analise["estatisticas"]]


def selecionar_anomalias(medicoes: list[dict], alerta: str | None, ordenar_por: str, limite: int) -> dict:
    """
    Anomalias do recorte, filtradas pelo alerta, ordenadas e limitadas.

    Os limites IQR e o Z-Score são calculados sobre as medições recebidas
    (decisão D9): anomalias de junho calculadas só com junho podem diferir
    das calculadas com o período inteiro.

    Args:
        medicoes: linhas no formato de get_medicoes().
        alerta: "IQR", "ZSCORE", "IQR+ZSCORE" ou None (todos).
        ordenar_por: "extremidade" (maior |Z-Score| primeiro) ou "data".
        limite: itens devolvidos. O total vem sempre completo.

    Returns:
        {"total", "por_alerta", "itens"}. por_alerta conta todo o recorte,
        e total conta o que passou pelo filtro de alerta.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import medicoes_de_exemplo
        >>> valores = [7.0] * 10 + [7.1] * 10 + [9.9]
        >>> resultado = selecionar_anomalias(medicoes_de_exemplo(valores), None, "extremidade", 5)
        >>> resultado["total"], resultado["itens"][0]["valor"], resultado["itens"][0]["alerta"]
        (1, 9.9, 'IQR+ZSCORE')
    """
    codigos = {(m["estacao"], m["parametro"]): m["codigo_parametro"] for m in medicoes}
    anomalias = AnaliticsService.analisar_medicoes(medicoes)["anomalias"]
    por_alerta = Counter(a["Alerta"] for a in anomalias)
    filtradas = [a for a in anomalias if alerta is None or a["Alerta"] == alerta]

    if ordenar_por == "extremidade":
        # Por quê: Z-Score None (desvio zero) vai para o fim, e não quebra a ordenação.
        filtradas.sort(key=lambda a: abs(a["Z-Score"]) if a["Z-Score"] is not None else -1.0, reverse=True)
    else:
        filtradas.sort(key=lambda a: a["Data"])

    itens = [
        {
            "data_hora": a["Data"],
            "estacao": a["Estação"],
            "codigo": codigos.get((a["Estação"], a["Parâmetro"])),
            "parametro": a["Parâmetro"],
            "unidade": a["Unidade"],
            "valor": a["Valor"],
            "limite_inferior": a["Limite Inferior"],
            "limite_superior": a["Limite Superior"],
            "zscore": a["Z-Score"],
            "alerta": a["Alerta"],
            "registro": a["Registro"],
        }
        for a in filtradas[:limite]
    ]
    return {"total": len(filtradas), "por_alerta": dict(sorted(por_alerta.items())), "itens": itens}


def estimar_pontos(inicio: date, fim: date, granularidade: str) -> int:
    """
    Quantos pontos uma série terá, calculado só pelas datas.

    Serve para recusar uma série grande demais ANTES de consultar o banco.

    Args:
        inicio: data inicial.
        fim: data final, inclusiva.
        granularidade: "hora", "dia", "semana" ou "mes".

    Returns:
        Número máximo de pontos da série.

    Example:
        >>> from datetime import date
        >>> estimar_pontos(date(2026, 8, 1), date(2026, 8, 31), "dia")
        31
        >>> estimar_pontos(date(2026, 8, 1), date(2026, 8, 31), "hora")
        744
        >>> estimar_pontos(date(2026, 4, 1), date(2026, 10, 23), "mes")
        7
    """
    dias = (fim - inicio).days + 1
    if granularidade == "hora":
        return dias * 24
    if granularidade == "dia":
        return dias
    if granularidade == "semana":
        segunda = inicio - timedelta(days=inicio.weekday())
        return (fim - segunda).days // 7 + 1
    return (fim.year - inicio.year) * 12 + fim.month - inicio.month + 1


def agregar_serie(medicoes: list[dict], granularidade: str, estatistica: str) -> list[dict]:
    """
    Série temporal de um parâmetro, agregada por hora, dia, semana ou mês.

    Args:
        medicoes: medições de um único parâmetro e de uma única estação.
        granularidade: "hora", "dia", "semana" (começa na segunda) ou "mes".
        estatistica: "media", "mediana", "minimo", "maximo" ou "soma".

    Returns:
        [{"inicio", "valor", "n"}] em ordem cronológica, sem os intervalos vazios.
        "inicio" é a data (ou a data e hora, na granularidade "hora").

    Raises:
        ErroDeRegra: mais de uma estação, ou mais de 200 pontos.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import medicoes_de_exemplo
        >>> linhas = medicoes_de_exemplo([1.0, 3.0, 10.0], horas=[0, 1, 24])
        >>> agregar_serie(linhas, "dia", "media")
        [{'inicio': '2026-06-01', 'valor': 2.0, 'n': 2}, {'inicio': '2026-06-02', 'valor': 10.0, 'n': 1}]
    """
    if not medicoes:
        return []
    exigir_estacao_unica(medicoes)
    serie = pd.Series(
        [m["valor"] for m in medicoes],
        index=pd.DatetimeIndex([m["data_hora"] for m in medicoes]),
    ).sort_index()
    grupos = serie.resample(REGRAS_RESAMPLE[granularidade], label="left", closed="left")
    tabela = pd.DataFrame({"valor": grupos.agg(AGREGACOES[estatistica]), "n": grupos.count()})
    tabela = tabela[tabela["n"] > 0]
    if len(tabela) > MAXIMO_PONTOS_SERIE:
        raise ErroDeRegra(
            f"a série teria {len(tabela)} pontos (máximo {MAXIMO_PONTOS_SERIE}); use uma granularidade maior"
        )
    return [
        {
            "inicio": instante.isoformat() if granularidade == "hora" else instante.date().isoformat(),
            "valor": float(linha.valor),
            "n": int(linha.n),
        }
        for instante, linha in tabela.iterrows()
    ]


def perfil_por_hora(medicoes: list[dict]) -> dict:
    """
    Ciclo diário de um parâmetro: média e mediana em cada hora do dia.

    Args:
        medicoes: medições de um único parâmetro e de uma única estação.

    Returns:
        {"horas": [{"hora", "media", "mediana", "n"}], "hora_maior_media",
        "hora_menor_media"}. Sem medições, horas vazia e as duas horas None.

    Raises:
        ErroDeRegra: mais de uma estação no recorte.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import medicoes_de_exemplo
        >>> linhas = medicoes_de_exemplo([0.0, 800.0, 2.0, 600.0], horas=[3, 12, 27, 36])
        >>> perfil = perfil_por_hora(linhas)
        >>> perfil["hora_maior_media"], perfil["hora_menor_media"], perfil["horas"][1]
        (12, 3, {'hora': 12, 'media': 700.0, 'mediana': 700.0, 'n': 2})
    """
    if not medicoes:
        return {"horas": [], "hora_maior_media": None, "hora_menor_media": None}
    exigir_estacao_unica(medicoes)
    tabela = pd.DataFrame({"hora": [m["data_hora"].hour for m in medicoes], "valor": [m["valor"] for m in medicoes]})
    por_hora = tabela.groupby("hora")["valor"].agg(["mean", "median", "count"])
    return {
        "horas": [
            {"hora": int(hora), "media": float(linha["mean"]), "mediana": float(linha["median"]), "n": int(linha["count"])}
            for hora, linha in por_hora.iterrows()
        ],
        "hora_maior_media": int(por_hora["mean"].idxmax()),
        "hora_menor_media": int(por_hora["mean"].idxmin()),
    }


def exigir_estacao_unica(medicoes: list[dict]) -> None:
    """
    Recusa recortes com mais de uma estação (série e perfil não misturam estações).

    Raises:
        ErroDeRegra: com os códigos das estações, para o LLM escolher uma.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import medicoes_de_exemplo
        >>> exigir_estacao_unica(medicoes_de_exemplo([1.0]))   # uma estação: ok
    """
    codigos = sorted({m["estacao_codigo"] for m in medicoes})
    if len(codigos) > 1:
        raise ErroDeRegra(f"o recorte tem {len(codigos)} estações ({', '.join(codigos)}); informe o argumento estacao")
