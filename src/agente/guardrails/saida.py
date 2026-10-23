"""
Guardrails de saída: verificação dos números da resposta (política POL-03).

Conceito
--------
Alucinação numérica: o LLM prevê o próximo token e, sem o número real, completa
com um número PLAUSÍVEL ("o pH médio foi 7,2"). O system prompt manda usar só
números das ferramentas, mas o prompt é um guardrail fraco: o modelo pode
desobedecer. Este módulo é a verificação em código:

1. extrair os números da resposta (formato brasileiro: 7,38 e 1.402);
2. ignorar o que não é medição: datas, horas, anos, códigos (EST-RJ-001),
   durações ("7 dias"), ordinais (1º) e itens numerados de lista;
3. procurar cada número nos resultados das ferramentas, na pergunta, no
   histórico e no system prompt, com tolerância de arredondamento: um número
   mostrado com 2 casas confere se estiver a até 0,005 do valor da ferramenta.
   Uma porcentagem também confere com a fração: "12,5%" ↔ p_evento=0.125
   (calibração da Fase 8: sem isso, toda probabilidade certa era acusada);
4. o que sobrar é "número sem origem".

É uma HEURÍSTICA: pode acusar um número legítimo (falso positivo) ou deixar
passar um inventado que por acaso coincide com outro valor. Por isso a ação é
leve (pedir correção uma vez e, se persistir, avisar), e os falsos positivos
são medidos na avaliação (Fase 8).

Documentação: docs/agente/guardrails-e-owasp.md § 9 ("Como a verificação dos números funciona")
"""
import re
from collections.abc import Iterable

from src.agente.contratos import ResultadoFerramenta

ANO_MINIMO, ANO_MAXIMO = 2000, 2100

# Trechos removidos antes de procurar números (não são medições).
_IGNORAR = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?"),  # 2026-06-03T06:00
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),  # 03/06/2026 e 03/06
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),  # 06:00
    re.compile(r"\b\d{1,2}h(?:\d{2})?\b"),  # 12h, 6h30
    re.compile(r"\b[A-Za-z]{2,}(?:-[A-Za-z0-9]+)+\b"),  # EST-RJ-001, TIP-PH, REG-RJ-001-03106
    # Cuidado: "º" (ordinal) e "°" (grau) são caracteres diferentes; "32 °C" é medição e fica.
    re.compile(r"\b\d+\.?[ªº]"),  # 1º, 2ª, 3.º
    re.compile(r"(?im)^\s*\d+[.)]\s"),  # "1. " no início de um item de lista
    re.compile(r"\b\d+\s+(?:dias?|horas?|minutos?|segundos?|semanas?|meses|m[eê]s|anos?)\b", re.IGNORECASE),
]
_NUMERO = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)*(?![\w])")
_PORCENTAGEM = re.compile(r"(?<![\w.,])(-?\d+(?:[.,]\d+)*)\s?%")


def candidatos(trecho: str) -> list[tuple[float, float]]:
    """
    Valores possíveis de um número escrito, cada um com a tolerância de arredondamento.

    "1.402" é ambíguo (mil quatrocentos e dois ou um vírgula quatro zero dois),
    então devolve os dois. A tolerância é meia unidade da última casa mostrada.

    Example:
        >>> candidatos("7,38")
        [(7.38, 0.0051)]
        >>> candidatos("1.402")
        [(1402.0, 0.51), (1.402, 0.00051)]
        >>> candidatos("1.402,5")
        [(1402.5, 0.051)]
    """
    def tolerancia(decimais: str) -> float:
        """Meia unidade da última casa, com folga para erro de ponto flutuante."""
        return round(0.51 * 10 ** -len(decimais), 10)

    if "," in trecho:
        inteiro, decimais = trecho.rsplit(",", 1)
        return [(float(inteiro.replace(".", "") + "." + decimais), tolerancia(decimais))]
    partes = trecho.split(".")
    if len(partes) == 1:
        return [(float(trecho), tolerancia(""))]
    resultado = []
    if all(len(p) == 3 for p in partes[1:]):  # pode ser separador de milhar
        resultado.append((float(trecho.replace(".", "")), tolerancia("")))
    if len(partes) == 2:  # pode ser decimal com ponto
        resultado.append((float(trecho), tolerancia(partes[1])))
    return resultado


def extrair_numeros(texto: str) -> list[str]:
    """
    Números do texto que podem ser medições, na ordem em que aparecem.

    Args:
        texto: resposta do LLM.

    Returns:
        Os números como foram escritos (ex.: "7,38"), sem datas, horas, anos,
        códigos, durações, ordinais e numeração de lista.

    Example:
        >>> extrair_numeros("Em 03/06/2026 às 06:00 (EST-RJ-001), o pH foi 9,30; média 7,38 em 1.402 medições na última 1 semana de 2026.")
        ['9,30', '7,38', '1.402']
    """
    for padrao in _IGNORAR:
        texto = padrao.sub(" ", texto)
    numeros = []
    for achado in _NUMERO.finditer(texto):
        trecho = achado.group(0)
        valores = candidatos(trecho.lstrip("-"))
        if len(valores) == 1 and valores[0][1] > 0.5 and ANO_MINIMO <= valores[0][0] <= ANO_MAXIMO:
            continue  # ano solto ("em 2026")
        numeros.append(trecho)
    return numeros


def valores_dos_resultados(resultados: Iterable[ResultadoFerramenta]) -> list[float]:
    """
    Todos os números dentro dos dados devolvidos pelas ferramentas.

    Inclui os números escritos DENTRO dos textos (ex.: um trecho da documentação
    de buscar_documentacao diz "87,7% das leituras"): o LLM pode citá-los, e
    eles têm origem.

    Example:
        >>> valores_dos_resultados([ResultadoFerramenta.ok("c1", {"linhas": [{"media": 7.381, "quantidade": 1402}],
        ...                                                        "texto": "87,7% das leituras com 0 mm"})])
        [7.381, 1402.0, 87.7, 0.0]
    """
    valores: list[float] = []

    def coletar(valor) -> None:
        """Percorre dicts e listas guardando os números."""
        if isinstance(valor, bool):
            return
        if isinstance(valor, (int, float)):
            valores.append(float(valor))
        elif isinstance(valor, str):
            valores.extend(numero for trecho in extrair_numeros(valor) for numero, _ in candidatos(trecho.lstrip("-")))
        elif isinstance(valor, dict):
            for item in valor.values():
                coletar(item)
        elif isinstance(valor, list):
            for item in valor:
                coletar(item)

    for resultado in resultados:
        if resultado.sucesso:
            coletar(resultado.dados)
    return valores


def numeros_sem_origem(texto: str, resultados: Iterable[ResultadoFerramenta], contexto: Iterable[str] = ()) -> list[str]:
    """
    Números da resposta que não aparecem nos resultados das ferramentas nem no contexto.

    Args:
        texto: resposta do LLM.
        resultados: resultados das ferramentas desta pergunta.
        contexto: textos que também valem como origem (pergunta, histórico, system prompt).

    Returns:
        Os números sem origem, sem repetição, na ordem da resposta. Vazio = tudo conferido.

    Example:
        >>> resultado = ResultadoFerramenta.ok("c1", {"media": 7.381, "quantidade": 1402, "anomalias": 11})
        >>> numeros_sem_origem("pH médio 7,38 em 1.402 medições, 11 anomalias; 2% acima de maio.", [resultado])
        ['2']
        >>> numeros_sem_origem("Chove em 12,5% das leituras.", [ResultadoFerramenta.ok("c1", {"p_evento": 0.125})])
        []
    """
    origem = valores_dos_resultados(resultados)
    for texto_contexto in contexto:
        origem += [valor for trecho in extrair_numeros(texto_contexto) for valor, _ in candidatos(trecho.lstrip("-"))]

    porcentagens = set(_PORCENTAGEM.findall(texto))
    sem_origem: list[str] = []
    for trecho in extrair_numeros(texto):
        negativo = trecho.startswith("-")
        # Conceito: "12,5%" é 0,125. A ferramenta devolve a fração, e o LLM mostra a porcentagem.
        escalas = (1, 100) if trecho in porcentagens else (1,)
        conferido = any(
            abs((-valor if negativo else valor) / escala - referencia) <= tolerancia / escala
            for valor, tolerancia in candidatos(trecho.lstrip("-"))
            for escala in escalas
            for referencia in origem
        )
        if not conferido and trecho not in sem_origem:
            sem_origem.append(trecho)
    return sem_origem


def pedido_de_correcao(numeros: list[str]) -> str:
    """
    Mensagem de sistema que pede ao LLM para refazer a resposta sem os números sem origem.

    Example:
        >>> pedido_de_correcao(["7,2", "15"]).startswith("Verificação automática: os números 7,2 e 15 não aparecem")
        True
    """
    sujeito = f"o número {numeros[0]} não aparece" if len(numeros) == 1 else f"os números {_listar(numeros)} não aparecem"
    return (
        f"Verificação automática: {sujeito} nos resultados das ferramentas "
        "desta conversa. Reescreva a resposta usando só valores devolvidos pelas ferramentas, ou chame a "
        "ferramenta adequada para obter o número. Não faça contas de cabeça."
    )


def acrescentar_aviso(texto: str, numeros: list[str]) -> str:
    """
    Resposta com o aviso visível de números que não puderam ser conferidos.

    Example:
        >>> acrescentar_aviso("O pH foi 7,2.", ["7,2"])
        'O pH foi 7,2.\\n\\n⚠ Não foi possível conferir alguns números com os resultados das ferramentas: 7,2.'
    """
    return f"{texto}\n\n⚠ Não foi possível conferir alguns números com os resultados das ferramentas: {_listar(numeros)}."


def _listar(numeros: list[str]) -> str:
    """Junta os números em português: "a", "a e b", "a, b e c"."""
    return numeros[0] if len(numeros) == 1 else ", ".join(numeros[:-1]) + " e " + numeros[-1]
