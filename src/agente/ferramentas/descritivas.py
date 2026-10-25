"""
Ferramentas descritivas: panorama, parâmetros, resumo, anomalias, série e perfil horário.

Conceito
--------
Cada ferramenta junta três peças já prontas:

1. os argumentos validados (argumentos.py);
2. o acesso aos dados com filtros e cache (ConsultaDados);
3. o cálculo puro (calculos.py), que reaproveita o AnaliticsService.

A DESCRIÇÃO é a parte mais importante para o LLM: ele escolhe a ferramenta
só por ela (seleção zero-shot). Cada descrição diz o que a ferramenta faz,
quando usar e quando NÃO usar. Descrições vagas fazem o LLM chamar a
ferramenta errada, e isso é medido na avaliação (Fase 8).

Regras de retorno (docs/agente/ferramentas.md § 2): sempre os filtros
aplicados, a unidade e a quantidade; recorte vazio não é erro (devolve um
aviso e o período coberto pelos dados).

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_2.py (zero-shot)
Documentação: docs/agente/ferramentas.md § 3 e § 4
"""
from functools import partial

from src.agente.ferramentas.argumentos import (
    ArgumentosAnomalias,
    ArgumentosPerfil,
    ArgumentosResumo,
    ArgumentosSerie,
    ComPeriodo,
    SemArgumentos,
)
from src.agente.ferramentas.base import ErroDeRegra, Ferramenta
from src.agente.ferramentas.calculos import (
    MAXIMO_PONTOS_SERIE,
    agregar_serie,
    estimar_pontos,
    perfil_por_hora,
    resumir,
    selecionar_anomalias,
)
from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes

AVISO_SEM_MEDICOES = "sem medições no recorte"
BASE_CALCULO = "limites IQR e Z-Score calculados sobre o recorte pedido"

DESCRICAO_PANORAMA = (
    "Mostra as estações monitoradas (código, nome, município e UF), o período coberto por cada uma "
    "(primeira e última leitura), a quantidade de leituras, o intervalo médio entre leituras, os CÓDIGOS "
    "dos operadores que registraram leituras em cada estação (com período e quantidade) e quantos "
    "parâmetros estão cadastrados. Use primeiro em perguntas vagas ('que dados você tem?'), para saber se "
    "existe dado num período ou para 'quem opera a estação?'. O código do operador (ex.: OP-RJ-001) não é "
    "dado pessoal; nome, CPF e e-mail não ficam disponíveis (LGPD). Não traz valores medidos: para isso "
    "use resumo_estatistico."
)
DESCRICAO_PARAMETROS = (
    "Lista os parâmetros medidos com código, nome, unidade e faixa válida (faixa_minima e faixa_maxima; "
    "null = sem limite). Use para traduzir nomes ('oxigênio', 'chuva', 'acidez') nos códigos que as outras "
    "ferramentas exigem (ex.: TIP-OXI) e para perguntas sobre unidades e faixas. Não traz valores medidos."
)
DESCRICAO_RESUMO = (
    "Calcula estatísticas descritivas por estação e parâmetro num período: quantidade, média, mediana, "
    "desvio padrão, variância, quartis (Q1, Q3), IQR, mínimo, máximo, limites IQR e número de anomalias. "
    "Use para qualquer pergunta numérica sobre valores medidos ('pH médio em junho', 'temperatura máxima "
    "da água em agosto'). Para a evolução ao longo do tempo use serie_temporal; para listar as anomalias "
    "use listar_anomalias."
)
DESCRICAO_ANOMALIAS = (
    "Lista as medições anômalas (regra IQR e Z-Score acima de 3) com data e hora, valor, limites, Z-Score e "
    "indicador de alerta (IQR, ZSCORE ou IQR+ZSCORE), além do total e da contagem por alerta. Use para "
    "perguntas sobre anomalias, alertas ou valores extremos. Os limites são calculados sobre o recorte "
    "pedido: uma medição pode ser anômala num mês e normal no período inteiro."
)
DESCRICAO_SERIE = (
    "Série temporal de UM parâmetro agregada por hora, dia, semana (começa na segunda-feira) ou mês, com a "
    f"estatística escolhida (media, mediana, minimo, maximo ou soma) e a quantidade de medições por ponto. "
    f"Use para evolução e tendência no tempo ('temperatura média por semana em agosto', 'chuva acumulada "
    f"por mês'). No máximo {MAXIMO_PONTOS_SERIE} pontos: para períodos longos, use granularidade maior. "
    "Para um único número do período inteiro, use resumo_estatistico."
)
DESCRICAO_PERFIL = (
    "Ciclo diário de UM parâmetro: média e mediana em cada hora do dia (0 a 23) no período, e as horas de "
    "maior e menor média. Use para 'em que hora a radiação solar é maior?' ou 'como a umidade varia ao "
    "longo do dia?'. Para a evolução entre dias, use serie_temporal."
)


def criar_ferramentas_descritivas(consulta: ConsultaDados) -> list[Ferramenta]:
    """
    As seis ferramentas descritivas ligadas a um ConsultaDados.

    Args:
        consulta: acesso aos dados (real ou falso, nos testes).

    Returns:
        Lista de Ferramenta, na ordem do catálogo de docs/agente/ferramentas.md § 3.

    Example:
        >>> class Vazio:
        ...     def get_all(self): return []
        ...     def get_com_estacoes(self): return []
        ...     def get_cobertura(self): return []
        >>> consulta = ConsultaDados(Vazio(), Vazio(), Vazio(), Vazio())
        >>> [f.nome for f in criar_ferramentas_descritivas(consulta)]
        ['panorama_dados', 'listar_parametros', 'resumo_estatistico', 'listar_anomalias', 'serie_temporal', 'perfil_horario']
    """
    # Por quê: partial liga o ConsultaDados à função, e a Ferramenta só passa
    # os argumentos validados. A função continua testável com qualquer consulta.
    return [
        Ferramenta("panorama_dados", DESCRICAO_PANORAMA, SemArgumentos, partial(panorama_dados, consulta)),
        Ferramenta("listar_parametros", DESCRICAO_PARAMETROS, SemArgumentos, partial(listar_parametros, consulta)),
        Ferramenta("resumo_estatistico", DESCRICAO_RESUMO, ArgumentosResumo, partial(resumo_estatistico, consulta)),
        Ferramenta("listar_anomalias", DESCRICAO_ANOMALIAS, ArgumentosAnomalias, partial(listar_anomalias, consulta)),
        Ferramenta(
            "serie_temporal",
            DESCRICAO_SERIE,
            ArgumentosSerie,
            partial(serie_temporal, consulta),
            limite_itens=MAXIMO_PONTOS_SERIE,
        ),
        Ferramenta("perfil_horario", DESCRICAO_PERFIL, ArgumentosPerfil, partial(perfil_horario, consulta)),
    ]


def panorama_dados(consulta: ConsultaDados, argumentos: SemArgumentos) -> dict:
    """
    Estações, período coberto e volume de leituras (docs/agente/ferramentas.md § 4.1).

    O intervalo médio entre leituras sai da própria cobertura:
    (última - primeira) / (leituras - 1), sem carregar as medições.

    Os operadores aparecem só pelo código (POL-02): o código identifica o posto
    de trabalho, e nome, CPF e e-mail ficam protegidos no banco e fora do alcance
    do usuário do agente.

    Args:
        consulta: acesso aos dados.
        argumentos: nenhum.

    Returns:
        {"estacoes": [{..., "operadores": [{"codigo", "primeira_leitura", "ultima_leitura", "leituras"}]}],
        "parametros_cadastrados": n}.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> estacao = panorama_dados(consulta_de_exemplo(), SemArgumentos())["estacoes"][0]
        >>> estacao["codigo"], estacao["leituras"], estacao["intervalo_medio_minutos"]
        ('EST-1', 4, 60)
        >>> [(o["codigo"], o["leituras"]) for o in estacao["operadores"]]
        [('OP-1', 4)]
    """
    cobertura = {c["estacao_codigo"]: c for c in consulta.cobertura()}
    operadores: dict[str, list[dict]] = {}
    for linha in consulta.operadores():
        operadores.setdefault(linha["estacao_codigo"], []).append(
            {
                "codigo": linha["operador_codigo"],
                "primeira_leitura": linha["primeira_leitura"],
                "ultima_leitura": linha["ultima_leitura"],
                "leituras": linha["leituras"],
            }
        )
    estacoes = []
    for estacao in consulta.estacoes():
        dados = cobertura.get(estacao["codigo"], {})
        leituras = dados.get("leituras", 0)
        intervalo = None
        if leituras > 1:
            minutos = (dados["ultima_leitura"] - dados["primeira_leitura"]).total_seconds() / 60
            intervalo = round(minutos / (leituras - 1))
        estacoes.append(
            {
                **estacao,
                "primeira_leitura": dados.get("primeira_leitura"),
                "ultima_leitura": dados.get("ultima_leitura"),
                "leituras": leituras,
                "intervalo_medio_minutos": intervalo,
                "operadores": operadores.get(estacao["codigo"], []),
            }
        )
    return {"estacoes": estacoes, "parametros_cadastrados": len(consulta.parametros())}


def listar_parametros(consulta: ConsultaDados, argumentos: SemArgumentos) -> dict:
    """
    Parâmetros cadastrados com unidade e faixa válida (docs/agente/ferramentas.md § 4.2).

    Args:
        consulta: acesso aos dados.
        argumentos: nenhum.

    Returns:
        {"parametros": [{"codigo", "nome", "unidade", "faixa_minima", "faixa_maxima"}]}.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> listar_parametros(consulta_de_exemplo(), SemArgumentos())["parametros"][0]["faixa_maxima"]
        14.0
    """
    return {
        "parametros": [
            {
                "codigo": p.codigo_parametro,
                "nome": p.nome,
                "unidade": p.unidade_medida,
                "faixa_minima": p.valor_minimo,
                "faixa_maxima": p.valor_maximo,
            }
            for p in consulta.parametros()
        ]
    }


def resumo_estatistico(consulta: ConsultaDados, argumentos: ArgumentosResumo) -> dict:
    """
    Estatísticas descritivas do recorte (docs/agente/ferramentas.md § 4.3).

    Args:
        consulta: acesso aos dados.
        argumentos: estação, parâmetros e período.

    Returns:
        {"filtros", "linhas"} ou, sem medições, também "aviso" e "cobertura".

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> linha = resumo_estatistico(consulta_de_exemplo(), ArgumentosResumo())["linhas"][0]
        >>> linha["codigo"], round(linha["media"], 3), linha["quantidade"]
        ('TIP-PH', 7.3, 4)
    """
    parametros = tuple(sorted(argumentos.parametros)) if argumentos.parametros else None
    medicoes = consulta.medicoes(_filtro(argumentos, parametros))
    if not medicoes:
        return _sem_medicoes(consulta, argumentos, linhas=[])
    return {"filtros": _filtros(argumentos), "linhas": resumir(medicoes)}


def listar_anomalias(consulta: ConsultaDados, argumentos: ArgumentosAnomalias) -> dict:
    """
    Medições anômalas do recorte (docs/agente/ferramentas.md § 4.4).

    Args:
        consulta: acesso aos dados.
        argumentos: filtros, alerta, ordenação e limite.

    Returns:
        {"filtros", "base_calculo", "total", "por_alerta", "itens"} ou o aviso de recorte vazio.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> listar_anomalias(consulta_de_exemplo(), ArgumentosAnomalias())["total"]   # 4 valores regulares
        0
    """
    parametros = (argumentos.parametro,) if argumentos.parametro else None
    medicoes = consulta.medicoes(_filtro(argumentos, parametros))
    if not medicoes:
        return _sem_medicoes(consulta, argumentos, total=0, itens=[])
    selecao = selecionar_anomalias(medicoes, argumentos.alerta, argumentos.ordenar_por, argumentos.limite)
    return {"filtros": _filtros(argumentos), "base_calculo": BASE_CALCULO, **selecao}


def serie_temporal(consulta: ConsultaDados, argumentos: ArgumentosSerie) -> dict:
    """
    Série temporal de um parâmetro (docs/agente/ferramentas.md § 4.5).

    A série grande demais é recusada ANTES da consulta ao banco, só pelas
    datas. O código não troca a granularidade sozinho, para o LLM não
    apresentar uma série diferente da pedida.

    Args:
        consulta: acesso aos dados.
        argumentos: parâmetro, estação, período, granularidade e estatística.

    Returns:
        {"filtros", "unidade", "pontos"} ou o aviso de recorte vazio.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> argumentos = ArgumentosSerie(parametro="TIP-PH", data_inicio="2026-06-01",
        ...                              data_fim="2026-06-01", granularidade="dia")
        >>> serie_temporal(consulta_de_exemplo(), argumentos)["pontos"][0]["n"]
        4

    Raises:
        ErroDeRegra: mais de 200 pontos, ou estação omitida havendo várias.
    """
    pontos = estimar_pontos(argumentos.data_inicio, argumentos.data_fim, argumentos.granularidade)
    if pontos > MAXIMO_PONTOS_SERIE:
        raise ErroDeRegra(
            f"a série teria até {pontos} pontos (máximo {MAXIMO_PONTOS_SERIE}); use uma granularidade maior"
        )
    _exigir_estacao(consulta, argumentos)
    medicoes = consulta.medicoes(_filtro(argumentos, (argumentos.parametro,)))
    if not medicoes:
        return _sem_medicoes(consulta, argumentos, pontos=[])
    return {
        "filtros": _filtros(argumentos),
        "unidade": medicoes[0]["unidade_medida"],
        "pontos": agregar_serie(medicoes, argumentos.granularidade, argumentos.estatistica),
    }


def perfil_horario(consulta: ConsultaDados, argumentos: ArgumentosPerfil) -> dict:
    """
    Ciclo diário de um parâmetro (docs/agente/ferramentas.md § 4.6).

    Args:
        consulta: acesso aos dados.
        argumentos: parâmetro, estação e período.

    Returns:
        {"filtros", "unidade", "horas", "hora_maior_media", "hora_menor_media"} ou o aviso de recorte vazio.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> perfil_horario(consulta_de_exemplo(), ArgumentosPerfil(parametro="TIP-PH"))["hora_maior_media"]
        3

    Raises:
        ErroDeRegra: estação omitida havendo várias.
    """
    _exigir_estacao(consulta, argumentos)
    medicoes = consulta.medicoes(_filtro(argumentos, (argumentos.parametro,)))
    if not medicoes:
        return _sem_medicoes(consulta, argumentos, horas=[])
    return {"filtros": _filtros(argumentos), "unidade": medicoes[0]["unidade_medida"], **perfil_por_hora(medicoes)}


def _filtro(argumentos: ComPeriodo, parametros: tuple[str, ...] | None) -> FiltroMedicoes:
    """Monta o recorte de medições a partir dos argumentos validados."""
    return FiltroMedicoes(argumentos.estacao, parametros, argumentos.data_inicio, argumentos.data_fim)


def _filtros(argumentos: ComPeriodo) -> dict:
    """Filtros efetivamente aplicados, devolvidos para o LLM saber o que foi calculado."""
    return argumentos.model_dump(mode="json")


def _sem_medicoes(consulta: ConsultaDados, argumentos: ComPeriodo, **vazios) -> dict:
    """Recorte vazio não é erro: aviso + período coberto, para o LLM explicar ao usuário."""
    return {"filtros": _filtros(argumentos), **vazios, "aviso": AVISO_SEM_MEDICOES, "cobertura": consulta.cobertura()}


def _exigir_estacao(consulta: ConsultaDados, argumentos: ComPeriodo) -> None:
    """Série e perfil não misturam estações: com mais de uma cadastrada, a estação é obrigatória."""
    if argumentos.estacao is None:
        codigos = [e["codigo"] for e in consulta.estacoes()]
        if len(codigos) > 1:
            raise ErroDeRegra(f"há {len(codigos)} estações ({', '.join(codigos)}); informe o argumento estacao")
