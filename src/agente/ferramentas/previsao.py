"""
Ferramenta prever: a previsão de curto prazo exposta ao LLM (Fase 10, DA10).

Conceito
--------
A ferramenta só LÊ o modelo treinado por python main.py --treinar-previsao
(src/previsao/). Ela monta os atributos do último instante com dados (o mesmo
cálculo do treino) e pede a previsão ao Pipeline aprovado:

    última leitura 23/10 23:30 → atributos (lags, médias, hora) → Ridge → 21,4 °C às 05:30

O retorno traz SEMPRE o erro esperado do modelo e dos dois baselines no
horizonte pedido (MAE e RMSE da validação e do teste). O system prompt manda
o LLM informar a margem de erro e dizer que é uma estimativa (POL-03: o número
e o erro vêm do modelo, nunca do LLM).

A referência é a ÚLTIMA LEITURA DISPONÍVEL, e não a hora atual: os dados
podem terminar antes ou depois de hoje (ponto P3 da análise).

Horizonte que o modelo não venceu no treino é recusado com erro de regra:
publicar uma previsão pior que "igual à mesma hora de ontem" seria enganar o usuário.

Documentação: docs/agente/ferramentas.md § 4.12
"""
from datetime import timedelta
from functools import partial
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from src.agente.ferramentas.argumentos import PADRAO_CODIGO
from src.agente.ferramentas.base import ErroDeRegra, Ferramenta
from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes
from src.previsao.atributos import montar_atributos
from src.previsao.dados import PASSOS_POR_HORA, series_alvo
from src.previsao.persistencia import ModeloPrevisao
from src.previsao.relatorio import AVISO_SINTETICOS

DIAS_DE_HISTORICO = 3
AVISO_PREVISAO = "Estimativa do modelo, não uma medição. " + AVISO_SINTETICOS
DESCRICAO_PREVER = (
    "Prevê temperatura do ar (TIP-TMP), umidade (TIP-UMI), temperatura da água (TIP-TAG) ou radiação solar "
    "(TIP-RAD) de 1 a 24 horas depois da ÚLTIMA leitura disponível, com o modelo treinado no projeto. Devolve a "
    "previsão e o erro esperado (MAE e RMSE) do modelo e dos baselines ingênuo e sazonal. Na resposta, informe "
    "sempre a margem de erro (MAE) e que é uma estimativa. Só os horizontes aprovados no treino respondem; os "
    "outros voltam com erro explicando que o modelo não supera o baseline. Não use para valores passados: para "
    "isso use resumo_estatistico ou serie_temporal."
)


class ArgumentosPrever(BaseModel):
    """
    Argumentos de prever.

    Example:
        >>> ArgumentosPrever(parametro="TIP-TMP", horizonte_horas=6).estacao is None
        True
    """

    model_config = ConfigDict(extra="forbid")

    parametro: Literal["TIP-TMP", "TIP-UMI", "TIP-TAG", "TIP-RAD"] = Field(description="Parâmetro com estrutura temporal.")
    estacao: str | None = Field(None, pattern=PADRAO_CODIGO, description="Código da estação, ex.: EST-RJ-001. Obrigatório com mais de uma estação.")
    horizonte_horas: int = Field(ge=1, le=24, description="Horas à frente da última leitura (1 a 24).")


def criar_ferramenta_prever(consulta: ConsultaDados, modelo: ModeloPrevisao) -> Ferramenta:
    """
    A ferramenta prever ligada aos dados e ao modelo carregado.

    Example:
        >>> criar_ferramenta_prever(None, ModeloPrevisao({}, {"avaliacoes": {}})).nome
        'prever'
    """
    return Ferramenta("prever", DESCRICAO_PREVER, ArgumentosPrever, partial(prever, consulta, modelo))


def prever(consulta: ConsultaDados, modelo: ModeloPrevisao, argumentos: ArgumentosPrever) -> dict:
    """
    A previsão a partir da última leitura, com o erro esperado do modelo e dos baselines.

    Returns:
        {"parametro", "unidade", "estacao", "referencia", "horizonte_horas", "instante_previsto",
        "previsao", "erro_validacao", "erro_teste", "modelo", "treinado_em", "periodo_treino", "aviso"}.

    Raises:
        ErroDeRegra: horizonte não treinado ou não aprovado, estação ambígua ou
            inexistente, ou lacunas nas últimas 24 h.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> validacao = {"modelo": {"mae": 0.31}, "ingenuo": {"mae": 0.29}, "ingenuo_sazonal": {"mae": 0.95}}
        >>> modelo = ModeloPrevisao({}, {"avaliacoes": {"EST-1|TIP-TMP|1": {"aprovado": False, "validacao": validacao}}})
        >>> try:
        ...     prever(consulta_de_exemplo(), modelo, ArgumentosPrever(parametro="TIP-TMP", horizonte_horas=1))
        ... except ErroDeRegra as erro:
        ...     print(str(erro)[:70])
        em 1 h o modelo não supera o baseline (MAE do modelo 0.31, ingênuo 0.2
    """
    estacao = consulta.resolver_estacao(argumentos.estacao)
    horas, parametro = argumentos.horizonte_horas, argumentos.parametro
    avaliacao = modelo.avaliacao(estacao, parametro, horas)
    if avaliacao is None:
        treinados = sorted({a["horas"] for a in modelo.metadados["avaliacoes"].values() if a.get("parametro") == parametro and a.get("estacao") == estacao and a.get("aprovado")})
        raise ErroDeRegra(f"não há modelo de {parametro} em {horas} h para {estacao}; horizontes disponíveis: {', '.join(map(str, treinados)) or 'nenhum'}")
    if not avaliacao["aprovado"]:
        erro = avaliacao["validacao"]
        raise ErroDeRegra(
            f"em {horas} h o modelo não supera o baseline (MAE do modelo {erro['modelo']['mae']}, ingênuo {erro['ingenuo']['mae']}, "
            f"ingênuo sazonal {erro['ingenuo_sazonal']['mae']}): não há previsão melhor que repetir a última medição ou a mesma hora do dia anterior"
        )
    serie = _serie_recente(consulta, estacao, parametro)
    atributos, _ = montar_atributos(serie, horas)
    ultima = atributos.iloc[[-1]]
    if ultima.isna().any(axis=None):
        raise ErroDeRegra(f"lacunas nas leituras de {parametro} nas 24 h antes de {serie.index[-1]:%d/%m/%Y %H:%M}; não dá para montar a previsão")
    referencia = serie.index[-1]
    return {
        "parametro": parametro,
        "unidade": next((p.unidade_medida for p in consulta.parametros() if p.codigo_parametro == parametro), None),
        "estacao": estacao,
        "referencia": referencia.isoformat(),
        "horizonte_horas": horas,
        "instante_previsto": (referencia + timedelta(hours=horas)).isoformat(),
        "previsao": round(float(modelo.pipeline(estacao, parametro, horas).predict(ultima)[0]), 2),
        "erro_validacao": avaliacao["validacao"],
        "erro_teste": avaliacao["teste"],
        "modelo": avaliacao["modelo"],
        "treinado_em": modelo.metadados["criado_em"][:10],
        "periodo_treino": avaliacao["periodo"],
        "aviso": AVISO_PREVISAO,
    }


def _serie_recente(consulta: ConsultaDados, estacao: str, parametro: str) -> pd.Series:
    """Os últimos dias da série (o bastante para as defasagens de 24 h e a média móvel de 48 leituras)."""
    ultima = next((c["ultima_leitura"] for c in consulta.cobertura() if c["estacao_codigo"] == estacao), None)
    if ultima is None:
        raise ErroDeRegra(f"sem leituras na estação {estacao}")
    filtro = FiltroMedicoes(estacao=estacao, parametros=(parametro,), data_inicio=ultima.date() - timedelta(days=DIAS_DE_HISTORICO), data_fim=ultima.date())
    serie = series_alvo(consulta.medicoes(filtro), (parametro,)).get((estacao, parametro))
    if serie is None or len(serie) < 24 * PASSOS_POR_HORA:
        raise ErroDeRegra(f"menos de 24 h de leituras de {parametro} antes da última leitura da estação {estacao}")
    return serie
