"""
Ferramentas de inferência: comparar_periodos, correlacao e probabilidade_evento.

Conceito
--------
São as ferramentas para perguntas do tipo "é diferente?", "estão
relacionadas?" e "qual a chance?". Todo número (p-valor, tamanho de efeito,
r, probabilidade) é calculado em calculos_inferencia.py, com scipy, e nunca
pelo LLM (política POL-03). O retorno já traz a INTERPRETAÇÃO padronizada
(significativo ou não, efeito desprezível a grande, correlação fraca a forte),
para o LLM não inventar a sua.

Lição que as descrições reforçam: "significativo" não quer dizer "importante".
Com milhares de medições, p < 0,05 é fácil. Por isso o tamanho do efeito vem junto.

Documentação: docs/agente/ferramentas.md § 4.8 a § 4.10
"""
from functools import partial

from src.agente.ferramentas.argumentos import ArgumentosComparacao, ArgumentosCorrelacao, ArgumentosProbabilidade
from src.agente.ferramentas.base import ErroDeRegra, Ferramenta
from src.agente.ferramentas.calculos_inferencia import (
    comparar_amostras,
    correlacionar,
    no_turno,
    parear_por_leitura,
    probabilidade,
)
from src.agente.ferramentas.consulta_dados import ConsultaDados, FiltroMedicoes

AVISO_SEM_MEDICOES = "sem medições no recorte"

DESCRICAO_COMPARACAO = (
    "Compara UM parâmetro entre dois recortes (A e B): datas diferentes (junho × julho) ou turnos "
    "diferentes no mesmo período (dia × noite). Devolve a descritiva de cada recorte, o teste de "
    "Mann-Whitney (p-valor e se é significativo a 5%) e o tamanho do efeito com a interpretação. Use para "
    "'a turbidez de julho foi diferente da de junho?' e 'a temperatura do dia é diferente da noite?'. "
    "Sempre informe o tamanho do efeito junto com o p-valor: com muitas medições, uma diferença "
    "desprezível pode ser 'significativa'."
)
DESCRICAO_CORRELACAO = (
    "Mede a correlação entre 2 a 6 parâmetros (Spearman por padrão, ou Pearson), pareando os valores da "
    "mesma leitura. Devolve r, p-valor, quantidade de pares e a interpretação (desprezível, fraca, moderada "
    "ou forte; positiva ou negativa). Use para 'temperatura e umidade estão relacionadas?'. Correlação não é "
    "causa; quando der desprezível, diga que não há relação."
)
DESCRICAO_PROBABILIDADE = (
    "Calcula a probabilidade de um evento num parâmetro (ex.: chuva > 0 mm) pela proporção de leituras e, "
    "se houver condição, a probabilidade condicional (ex.: P(chuva > 0 | umidade > 90%)), com as contagens. "
    "Use para 'qual a chance de chover quando a umidade passa de 90%?'. Use listar_parametros para saber a "
    "unidade dos valores de referência."
)


def criar_ferramentas_inferencia(consulta: ConsultaDados) -> list[Ferramenta]:
    """
    As três ferramentas de inferência ligadas a um ConsultaDados.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> [f.nome for f in criar_ferramentas_inferencia(consulta_de_exemplo())]
        ['comparar_periodos', 'correlacao', 'probabilidade_evento']
    """
    return [
        Ferramenta("comparar_periodos", DESCRICAO_COMPARACAO, ArgumentosComparacao, partial(comparar_periodos, consulta)),
        Ferramenta("correlacao", DESCRICAO_CORRELACAO, ArgumentosCorrelacao, partial(correlacao, consulta)),
        Ferramenta("probabilidade_evento", DESCRICAO_PROBABILIDADE, ArgumentosProbabilidade, partial(probabilidade_evento, consulta)),
    ]


def comparar_periodos(consulta: ConsultaDados, argumentos: ArgumentosComparacao) -> dict:
    """
    Mann-Whitney e tamanho de efeito entre os recortes A e B (docs/agente/ferramentas.md § 4.8).

    Raises:
        ErroDeRegra: estação omitida havendo várias, ou recorte com menos de 5 valores.

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo, medicoes_de_exemplo
        >>> valores = [8.0 if 6 <= hora < 18 else 7.0 for hora in range(24)]   # pH maior durante o dia
        >>> consulta = consulta_de_exemplo(medicoes_de_exemplo(valores))
        >>> argumentos = ArgumentosComparacao(parametro="TIP-PH", inicio_a="2026-06-01", fim_a="2026-06-01", turno_a="dia",
        ...                                   inicio_b="2026-06-01", fim_b="2026-06-01", turno_b="noite")
        >>> resultado = comparar_periodos(consulta, argumentos)
        >>> resultado["a"]["n"], resultado["b"]["n"], resultado["sentido"]
        (12, 12, 'A maior que B')
    """
    _exigir_estacao(consulta, argumentos.estacao)
    filtros = argumentos.model_dump(mode="json")
    a = _valores(consulta, argumentos.estacao, argumentos.parametro, argumentos.inicio_a, argumentos.fim_a, argumentos.turno_a)
    b = _valores(consulta, argumentos.estacao, argumentos.parametro, argumentos.inicio_b, argumentos.fim_b, argumentos.turno_b)
    if not a or not b:
        return {"filtros": filtros, "aviso": AVISO_SEM_MEDICOES, "n_a": len(a), "n_b": len(b), "cobertura": consulta.cobertura()}
    unidade = _unidade(consulta, argumentos.parametro)
    return {"filtros": filtros, "unidade": unidade, **comparar_amostras(a, b)}


def correlacao(consulta: ConsultaDados, argumentos: ArgumentosCorrelacao) -> dict:
    """
    Correlação par a par, com as medições pareadas pela mesma leitura (docs/agente/ferramentas.md § 4.9).

    Raises:
        ErroDeRegra: parâmetro inexistente (ConsultaDados.validar_parametros).

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> try:
        ...     correlacao(consulta_de_exemplo(), ArgumentosCorrelacao(parametros=["TIP-PH", "TIP-UMI"]))
        ... except ErroDeRegra as erro:
        ...     print(erro)
        parâmetro inexistente: TIP-UMI. Use listar_parametros para ver os códigos
    """
    parametros = tuple(argumentos.parametros)
    medicoes = consulta.medicoes(FiltroMedicoes(argumentos.estacao, tuple(sorted(parametros)), argumentos.data_inicio, argumentos.data_fim))
    filtros = argumentos.model_dump(mode="json")
    if not medicoes:
        return {"filtros": filtros, "pares": [], "aviso": AVISO_SEM_MEDICOES, "cobertura": consulta.cobertura()}
    return {"filtros": filtros, "metodo": argumentos.metodo, "pares": correlacionar(parear_por_leitura(medicoes), list(parametros), argumentos.metodo)}


def probabilidade_evento(consulta: ConsultaDados, argumentos: ArgumentosProbabilidade) -> dict:
    """
    P(evento) e P(evento | condição) pela proporção de leituras (docs/agente/ferramentas.md § 4.10).

    Example:
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> argumentos = ArgumentosProbabilidade(evento_parametro="TIP-PH", evento_operador=">", evento_valor=7.3)
        >>> probabilidade_evento(consulta_de_exemplo(), argumentos)["p_evento"]   # 7,4 e 7,6 entre 4 leituras
        0.5
    """
    tem_condicao = argumentos.condicao_parametro is not None
    parametros = {argumentos.evento_parametro} | ({argumentos.condicao_parametro} if tem_condicao else set())
    medicoes = consulta.medicoes(FiltroMedicoes(argumentos.estacao, tuple(sorted(parametros)), argumentos.data_inicio, argumentos.data_fim))
    filtros = argumentos.model_dump(mode="json")
    if not medicoes:
        return {"filtros": filtros, "aviso": AVISO_SEM_MEDICOES, "cobertura": consulta.cobertura()}
    evento = (argumentos.evento_parametro, argumentos.evento_operador, argumentos.evento_valor)
    condicao = (argumentos.condicao_parametro, argumentos.condicao_operador, argumentos.condicao_valor) if tem_condicao else None
    unidades = {p: _unidade(consulta, p) for p in sorted(parametros)}
    return {"filtros": filtros, "unidades": unidades, **probabilidade(parear_por_leitura(medicoes), evento, condicao)}


def _valores(consulta: ConsultaDados, estacao, parametro, inicio, fim, turno) -> list[float]:
    """Valores do parâmetro no período, só nas horas do turno."""
    medicoes = consulta.medicoes(FiltroMedicoes(estacao, (parametro,), inicio, fim))
    return [m["valor"] for m in medicoes if no_turno(m["data_hora"], turno)]


def _unidade(consulta: ConsultaDados, codigo: str) -> str | None:
    """Unidade do parâmetro pelo cadastro."""
    return next((p.unidade_medida for p in consulta.parametros() if p.codigo_parametro == codigo), None)


def _exigir_estacao(consulta: ConsultaDados, estacao: str | None) -> None:
    """Comparar períodos não mistura estações: com mais de uma cadastrada, a estação é obrigatória."""
    if estacao is None:
        codigos = [e["codigo"] for e in consulta.estacoes()]
        if len(codigos) > 1:
            raise ErroDeRegra(f"há {len(codigos)} estações ({', '.join(codigos)}); informe o argumento estacao")
