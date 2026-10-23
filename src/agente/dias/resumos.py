"""
Resumos diários: cada dia de cada estação vira um texto curto (Fase 9).

Conceito
--------
Embeddings comparam SIGNIFICADO, e número solto tem pouco significado para
eles: "21,3 °C" e "21,4 °C" são quase o mesmo dia, mas viram tokens diferentes.
Por isso o resumo traz, além dos números, RÓTULOS QUALITATIVOS calculados pelo código:

    15/06/2026, estação EST-RJ-001
    Chuva moderada: 12,4 mm no dia. Temperatura do ar: média 21,3 °C, baixa para
    o período (mín. 18,2; máx. 25,8). ... 2 anomalias: 1 de pH, 1 de turbidez.

- chuva pela faixa do acumulado do dia (sem chuva, fraca, moderada, forte);
- os outros parâmetros pela posição do valor do dia entre os dias da mesma
  estação (TERCIS: o terço de baixo é "baixa", o do meio, "típica", e o de
  cima, "alta" para o período);
- anomalias do dia, com o mesmo critério da análise (IQR ou |Z| > 3)
  calculado sobre a série inteira da estação.

A primeira linha (data e estação) serve para mostrar o resumo, e não entra no
embedding: se entrasse, 15/06 e 16/06 pareceriam mais próximos só pela data.

Os números vêm das medições, nunca do LLM. São um resumo, e não a medição:
para o valor exato de um dia, o agente usa resumo_estatistico.

Documentação: docs/agente/rag.md § 8
"""
import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.services.analytics_service import AnaliticsService

PARAMETRO_CHUVA = "TIP-CHU"
# Faixas do acumulado diário de chuva, em mm: até o limite (inclusive), o rótulo.
FAIXAS_CHUVA = ((0.0, "Sem chuva"), (5.0, "Chuva fraca"), (25.0, "Chuva moderada"), (math.inf, "Chuva forte"))
# Parâmetros resumidos pelo máximo do dia: o pico importa mais que a média.
PELO_MAXIMO = frozenset({"TIP-VEN", "TIP-RAD"})
ROTULOS_TERCIL = ("baixa", "típica", "alta")


@dataclass(frozen=True)
class ResumoDia:
    """
    O resumo textual de um dia de uma estação.

    Args:
        estacao: código da estação, ex.: "EST-RJ-001".
        dia: a data.
        texto: primeira linha com data e estação; depois, o conteúdo.

    Example:
        >>> resumo = ResumoDia("EST-1", date(2026, 6, 1), "01/06/2026, estação EST-1\\nSem chuva: 0 mm no dia.")
        >>> resumo.conteudo
        'Sem chuva: 0 mm no dia.'
    """

    estacao: str
    dia: date
    texto: str

    @property
    def conteudo(self) -> str:
        """O texto sem a primeira linha (data e estação): é o que vira embedding."""
        return conteudo_do_texto(self.texto)


def conteudo_do_texto(texto: str) -> str:
    """
    O resumo sem a linha de data e estação.

    Example:
        >>> conteudo_do_texto("01/06/2026, estação EST-1\\nSem anomalias.")
        'Sem anomalias.'
    """
    return texto.split("\n", 1)[-1]


def resumos_diarios(medicoes: list[dict]) -> list[ResumoDia]:
    """
    Um resumo por estação e dia, em ordem de estação e data.

    Args:
        medicoes: linhas de LeituraRepository.get_medicoes() (todas as do período).

    Returns:
        Os resumos. Sem medições: lista vazia.

    Example:
        >>> from datetime import datetime
        >>> def linha(dia, codigo, nome, unidade, valor):
        ...     return {"estacao_codigo": "EST-1", "estacao": "Estação 1", "codigo_registro": f"R{dia}{codigo}",
        ...             "data_hora": datetime(2026, 6, dia, 12), "codigo_parametro": codigo,
        ...             "parametro": nome, "unidade_medida": unidade, "valor": valor}
        >>> medicoes = [linha(d, "TIP-CHU", "Precipitação", "mm", c) for d, c in ((1, 0.0), (2, 12.4), (3, 30.0))]
        >>> medicoes += [linha(d, "TIP-TMP", "Temperatura do ar", "°C", t) for d, t in ((1, 20.0), (2, 25.0), (3, 30.0))]
        >>> print(resumos_diarios(medicoes)[1].texto)
        02/06/2026, estação EST-1
        Chuva moderada: 12,4 mm no dia. Temperatura do ar: média 25 °C, típica para o período (mín. 25; máx. 25). Sem anomalias.
    """
    if not medicoes:
        return []
    tabela = pd.DataFrame(medicoes)
    tabela["dia"] = pd.to_datetime(tabela["data_hora"]).dt.date
    diario = (
        tabela.groupby(["estacao_codigo", "dia", "codigo_parametro"], sort=True)["valor"]
        .agg(media="mean", minimo="min", maximo="max", soma="sum")
        .reset_index()
    )
    diario["valor_do_dia"] = [
        linha.soma if linha.codigo_parametro == PARAMETRO_CHUVA else linha.maximo if linha.codigo_parametro in PELO_MAXIMO else linha.media
        for linha in diario.itertuples(index=False)
    ]
    diario["tercil"] = diario.groupby(["estacao_codigo", "codigo_parametro"])["valor_do_dia"].transform(_tercil)
    nomes = tabela.drop_duplicates("codigo_parametro").set_index("codigo_parametro")[["parametro", "unidade_medida"]]
    anomalias = _anomalias_por_dia(tabela)

    resumos = []
    for (estacao, dia), linhas in diario.groupby(["estacao_codigo", "dia"], sort=True):
        frases = [_frase(linha, *nomes.loc[linha.codigo_parametro]) for linha in _chuva_primeiro(linhas)]
        frases.append(_frase_anomalias(anomalias.get((estacao, dia), {})))
        resumos.append(ResumoDia(estacao, dia, f"{dia:%d/%m/%Y}, estação {estacao}\n" + " ".join(frases)))
    return resumos


def _tercil(valores: pd.Series) -> pd.Series:
    """Rótulo de cada valor pela posição entre os valores da série (baixa, típica, alta)."""
    if valores.nunique() < 3:
        return pd.Series(ROTULOS_TERCIL[1], index=valores.index)
    # Conceito: rank(pct=True) dá a fração de valores menores ou iguais (0 a 1].
    posicao = valores.rank(pct=True, method="average")
    return posicao.map(lambda p: ROTULOS_TERCIL[0] if p <= 1 / 3 else ROTULOS_TERCIL[2] if p > 2 / 3 else ROTULOS_TERCIL[1])


def _chuva_primeiro(linhas: pd.DataFrame):
    """A chuva abre o resumo (é o que mais distingue um dia do outro); depois, os códigos em ordem."""
    return sorted(linhas.itertuples(index=False), key=lambda linha: (linha.codigo_parametro != PARAMETRO_CHUVA, linha.codigo_parametro))


def _frase(linha, nome: str, unidade: str) -> str:
    """Frase de um parâmetro no dia."""
    if linha.codigo_parametro == PARAMETRO_CHUVA:
        rotulo = next(texto for limite, texto in FAIXAS_CHUVA if linha.soma <= limite)
        return f"{rotulo}: {_numero(linha.soma)} {unidade} no dia."
    if linha.codigo_parametro in PELO_MAXIMO:
        return f"{nome}: máxima {_numero(linha.maximo)} {unidade}, {linha.tercil} para o período."
    return f"{nome}: média {_numero(linha.media)} {unidade}, {linha.tercil} para o período (mín. {_numero(linha.minimo)}; máx. {_numero(linha.maximo)})."


def _anomalias_por_dia(tabela: pd.DataFrame) -> dict[tuple[str, date], dict[str, int]]:
    """(estação, dia) → {nome do parâmetro: anomalias}, com o critério da análise sobre a série inteira."""
    analise = AnaliticsService.analisar_medicoes(tabela.drop(columns=["dia"]).to_dict("records"))
    codigo_da_estacao = dict(zip(tabela["estacao"], tabela["estacao_codigo"]))
    contagem: dict[tuple[str, date], dict[str, int]] = {}
    for anomalia in analise["anomalias"]:
        chave = (codigo_da_estacao[anomalia["Estação"]], pd.Timestamp(anomalia["Data"]).date())
        por_parametro = contagem.setdefault(chave, {})
        por_parametro[anomalia["Parâmetro"]] = por_parametro.get(anomalia["Parâmetro"], 0) + 1
    return contagem


def _frase_anomalias(por_parametro: dict[str, int]) -> str:
    """
    Frase das anomalias do dia.

    Example:
        >>> _frase_anomalias({"Turbidez": 1, "pH": 2}), _frase_anomalias({})
        ('3 anomalias: 2 de pH, 1 de turbidez.', 'Sem anomalias.')
    """
    if not por_parametro:
        return "Sem anomalias."
    total = sum(por_parametro.values())
    partes = ", ".join(f"{n} de {_minuscula(nome)}" for nome, n in sorted(por_parametro.items(), key=lambda par: (-par[1], par[0])))
    return f"{total} anomalia{'s' if total > 1 else ''}: {partes}."


def _minuscula(nome: str) -> str:
    """Nome no meio da frase: "Turbidez" → "turbidez", mas "pH" fica "pH"."""
    return nome if nome[:2] == "pH" else nome[:1].lower() + nome[1:]


def _numero(valor: float) -> str:
    """
    Número com até 2 casas, vírgula decimal e sem zeros à direita.

    Example:
        >>> _numero(21.30), _numero(7.0), _numero(-3.456)
        ('21,3', '7', '-3,46')
    """
    texto = f"{valor:.2f}".rstrip("0").rstrip(".")
    return "0" if texto in ("-0", "") else texto.replace(".", ",")
