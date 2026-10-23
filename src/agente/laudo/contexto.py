"""
As anomalias de um período e o contexto vizinho de cada uma (Fase 11).

Conceito
--------
Para julgar se uma anomalia é falha de sensor ou evento real, o especialista
olha a VIZINHANÇA, e não o valor sozinho:

    Anomalia: Turbidez = 480 NTU em 10/06/2026 03:00 (registro REG-...); alerta IQR+ZSCORE
    Mesmo parâmetro, 2 h antes e depois: 01:00 = 5,1; 01:30 = 4,8; ...; 05:00 = 6,2
    Outros parâmetros da mesma leitura: pH 7,2; Precipitação 0 mm; ...
    Chuva acumulada nas 3 h anteriores: 0 mm

Pico isolado, que volta ao normal na leitura seguinte e sem chuva, sugere
falha do sensor. Subida gradual depois de chuva forte sugere evento real.

As anomalias usam o mesmo critério do relatório (IQR ou |Z| > 3) sobre o
período pedido. O contexto pode olhar 2 h além das bordas do período.

Os números do texto são as medições, e ele vira a ÚNICA origem válida para os
números da justificativa (POL-03 em contrato.validar_resposta).

Documentação: docs/agente/seguranca-e-prompts.md § 9
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from src.services.analytics_service import AnaliticsService

JANELA_VIZINHOS = timedelta(hours=2)
JANELA_CHUVA = timedelta(hours=3)
PARAMETRO_CHUVA = "TIP-CHU"


@dataclass(frozen=True)
class AnomaliaComContexto:
    """
    Uma anomalia e o texto de contexto enviado ao LLM.

    Args:
        registro: código do registro (leitura) da anomalia.
        estacao: código da estação.
        parametro: código do parâmetro.
        nome_parametro, unidade: para o relatório.
        data_hora: instante da medição.
        valor: o valor anômalo.
        alerta: IQR, ZSCORE ou IQR+ZSCORE.
        zscore: o Z-Score (None se indefinido).
        texto: o contexto completo, já formatado.

    Example:
        >>> a = AnomaliaComContexto("REG-1", "EST-1", "TIP-TUR", "Turbidez", "NTU", datetime(2026, 6, 10, 3), 480.0, "IQR+ZSCORE", 6.1, "...")
        >>> a.extremidade
        6.1
    """

    registro: str
    estacao: str
    parametro: str
    nome_parametro: str
    unidade: str
    data_hora: datetime
    valor: float
    alerta: str
    zscore: float | None
    texto: str

    @property
    def extremidade(self) -> float:
        """|Z-Score|, para escolher as mais extremas quando há limite de laudos."""
        return abs(self.zscore) if self.zscore is not None else 0.0


def anomalias_com_contexto(medicoes_periodo: list[dict], medicoes_contexto: list[dict]) -> list[AnomaliaComContexto]:
    """
    As anomalias do período, cada uma com o texto de contexto, em ordem de data.

    Args:
        medicoes_periodo: medições do período pedido (definem as anomalias).
        medicoes_contexto: medições do período com margem (vizinhos nas bordas).

    Example:
        >>> def linha(hora, codigo, nome, unidade, valor):
        ...     return {"estacao_codigo": "EST-1", "estacao": "Estação 1", "codigo_registro": f"R-{hora:02d}",
        ...             "data_hora": datetime(2026, 6, 10, hora), "codigo_parametro": codigo, "parametro": nome,
        ...             "unidade_medida": unidade, "valor": valor}
        >>> medicoes = [linha(h, "TIP-TUR", "Turbidez", "NTU", 480.0 if h == 3 else 5.0 + h % 3) for h in range(8)]
        >>> medicoes += [linha(h, "TIP-CHU", "Precipitação", "mm", 0.0) for h in range(8)]
        >>> anomalia = anomalias_com_contexto(medicoes, medicoes)[0]
        >>> print(anomalia.texto)
        Anomalia: Turbidez = 480 NTU em 10/06/2026 03:00 (registro R-03); alerta IQR; limites IQR [3,88; 8,88]; Z-Score 2,47.
        Mesmo parâmetro, 2 h antes e depois: 01:00 = 6; 02:00 = 7; 04:00 = 6; 05:00 = 7.
        Outros parâmetros da mesma leitura: Precipitação 0 mm.
        Chuva acumulada nas 3 h anteriores (inclui a leitura): 0 mm.
    """
    analise = AnaliticsService.analisar_medicoes(medicoes_periodo)
    if not analise["anomalias"]:
        return []
    tabela = pd.DataFrame(medicoes_contexto)
    tabela["data_hora"] = pd.to_datetime(tabela["data_hora"])
    codigo_estacao = dict(zip(tabela["estacao"], tabela["estacao_codigo"]))
    codigo_parametro = dict(zip(tabela["parametro"], tabela["codigo_parametro"]))
    resultado = []
    for anomalia in analise["anomalias"]:
        estacao, parametro = codigo_estacao[anomalia["Estação"]], codigo_parametro[anomalia["Parâmetro"]]
        instante = pd.Timestamp(anomalia["Data"])
        resultado.append(
            AnomaliaComContexto(
                registro=anomalia["Registro"],
                estacao=estacao,
                parametro=parametro,
                nome_parametro=anomalia["Parâmetro"],
                unidade=anomalia["Unidade"],
                data_hora=instante.to_pydatetime(),
                valor=float(anomalia["Valor"]),
                alerta=anomalia["Alerta"],
                zscore=anomalia.get("Z-Score"),
                texto=_texto(anomalia, tabela[tabela["estacao_codigo"] == estacao], parametro, instante),
            )
        )
    return sorted(resultado, key=lambda a: (a.data_hora, a.estacao, a.parametro))


def _texto(anomalia: dict, da_estacao: pd.DataFrame, parametro: str, instante: pd.Timestamp) -> str:
    """O contexto da anomalia em quatro linhas."""
    unidade = anomalia["Unidade"]
    limites = (
        f"; limites IQR [{_numero(anomalia['Limite Inferior'])}; {_numero(anomalia['Limite Superior'])}]"
        if anomalia.get("Limite Inferior") is not None else ""
    )
    zscore = f"; Z-Score {_numero(anomalia['Z-Score'])}" if anomalia.get("Z-Score") is not None else ""
    linhas = [
        f"Anomalia: {anomalia['Parâmetro']} = {_numero(anomalia['Valor'])} {unidade} em {instante:%d/%m/%Y %H:%M} "
        f"(registro {anomalia['Registro']}); alerta {anomalia['Alerta']}{limites}{zscore}."
    ]
    mesmo = da_estacao[(da_estacao["codigo_parametro"] == parametro) & ((da_estacao["data_hora"] - instante).abs() <= JANELA_VIZINHOS)]
    mesmo = mesmo[mesmo["data_hora"] != instante].sort_values("data_hora")
    vizinhos = "; ".join(f"{linha.data_hora:%H:%M} = {_numero(linha.valor)}" for linha in mesmo.itertuples())
    linhas.append(f"Mesmo parâmetro, 2 h antes e depois: {vizinhos or 'sem leituras'}.")
    outros = da_estacao[(da_estacao["codigo_registro"] == anomalia["Registro"]) & (da_estacao["codigo_parametro"] != parametro)]
    outros = outros.sort_values("codigo_parametro")
    descricao = "; ".join(f"{linha.parametro} {_numero(linha.valor)} {linha.unidade_medida}" for linha in outros.itertuples())
    linhas.append(f"Outros parâmetros da mesma leitura: {descricao or 'nenhum'}.")
    chuva = da_estacao[(da_estacao["codigo_parametro"] == PARAMETRO_CHUVA) & (da_estacao["data_hora"] > instante - JANELA_CHUVA) & (da_estacao["data_hora"] <= instante)]
    if not chuva.empty:
        linhas.append(f"Chuva acumulada nas 3 h anteriores (inclui a leitura): {_numero(chuva['valor'].sum())} mm.")
    return "\n".join(linhas)


def _numero(valor: float) -> str:
    """Número com até 2 casas, vírgula decimal e sem zeros à direita."""
    texto = f"{float(valor):.2f}".rstrip("0").rstrip(".")
    return "0" if texto in ("-0", "") else texto.replace(".", ",")
