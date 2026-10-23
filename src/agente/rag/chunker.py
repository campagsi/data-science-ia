"""
Chunking: divide a documentação Markdown em trechos (chunks) para o RAG.

Conceito
--------
O RAG não busca documentos inteiros, e sim TRECHOS: um documento de 30 KB fala
de muitos assuntos, e o embedding de tudo junto seria uma média sem foco.
O trecho ideal fala de UM assunto e cabe no contexto do LLM sem desperdício.

Duas etapas (docs/agente/rag.md § 3):

1. pela estrutura: divide nos títulos #, ## e ###, guardando o caminho da seção
   ("analise-estatistica.md > Anomalias"). Seção = unidade de assunto;
2. recursiva dentro da seção grande: corta primeiro entre parágrafos, depois
   entre linhas, frases e palavras (separadores por prioridade), até caber em
   500 caracteres. Blocos de código e tabelas ficam inteiros quando cabem.
   (Era 1.000; o experimento e08 da Fase 8 mediu hit@4 de 0,77 com 1.000 e de 0,92 com 500.)

Sobreposição REAL de 75 caracteres (15% do tamanho): o fim de um trecho se repete no começo do
seguinte, para uma ideia cortada na fronteira aparecer inteira em pelo menos um
dos dois. (O RecursiveChuncker do módulo recebe overlap, mas não o usa.)

Trechos com menos de 80 caracteres são juntados ao anterior: um título solto ou
um "Ver abaixo." não ajudam a responder nada.

Cabeçalho contextual: o texto vetorizado começa com "Documento" e "Seção".
Assim o parágrafo "com n ≤ 10, |Z| nunca passa de 3" carrega o assunto no embedding.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-Rags-Embenddings/rag_pipeline.py
Documentação: docs/agente/rag.md § 3
"""
import re
from dataclasses import dataclass

TAMANHO_MAXIMO = 500
SOBREPOSICAO = 75
TAMANHO_MINIMO = 80
# Separadores por prioridade: parágrafo, linha, frase, palavra.
SEPARADORES = ("\n\n", "\n", ". ", " ")

_TITULO = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Chunk:
    """
    Um trecho de documento.

    Args:
        arquivo: caminho relativo à raiz do projeto, ex.: "docs/analise-estatistica.md".
        secao: caminho dos títulos, ex.: "Análise estatística > Anomalias".
        texto: conteúdo do trecho (sem o cabeçalho contextual).

    Example:
        >>> Chunk("docs/x.md", "Título", "Texto do trecho.").texto_vetorizado()
        'Documento: docs/x.md\\nSeção: Título\\n\\nTexto do trecho.'
    """

    arquivo: str
    secao: str
    texto: str

    def texto_vetorizado(self) -> str:
        """Texto que vira embedding: cabeçalho contextual (documento e seção) + conteúdo."""
        return f"Documento: {self.arquivo}\nSeção: {self.secao}\n\n{self.texto}"


def dividir_markdown(
    texto: str,
    arquivo: str,
    tamanho_maximo: int = TAMANHO_MAXIMO,
    sobreposicao: int = SOBREPOSICAO,
    tamanho_minimo: int = TAMANHO_MINIMO,
) -> list[Chunk]:
    """
    Divide um documento Markdown em trechos por seção, com sobreposição.

    Args:
        texto: conteúdo do arquivo.
        arquivo: caminho relativo, guardado em cada trecho.
        tamanho_maximo: máximo de caracteres por trecho.
        sobreposicao: caracteres repetidos entre trechos vizinhos da mesma seção.
        tamanho_minimo: trechos menores são juntados ao anterior.

    Returns:
        Trechos na ordem do documento.

    Example:
        >>> doc = "# Análise\\n\\n## Anomalias\\n\\nUma medição é anômala fora do IQR ou com |Z| > 3, sempre sinalizada e nunca removida."
        >>> [(c.secao, c.texto[:20]) for c in dividir_markdown(doc, "docs/a.md")]
        [('Análise > Anomalias', 'Uma medição é anômal')]
    """
    trechos: list[Chunk] = []
    for secao, corpo in _secoes(texto):
        for pedaco in _dividir(corpo, tamanho_maximo, sobreposicao):
            if trechos and len(pedaco) < tamanho_minimo and trechos[-1].arquivo == arquivo:
                anterior = trechos.pop()
                pedaco_junto = f"{anterior.texto}\n\n{pedaco}"
                trechos.append(Chunk(arquivo, anterior.secao, pedaco_junto))
            elif len(pedaco) >= tamanho_minimo or not trechos:
                trechos.append(Chunk(arquivo, secao, pedaco))
    return [t for t in trechos if len(t.texto) >= tamanho_minimo]


def _secoes(texto: str) -> list[tuple[str, str]]:
    """
    Separa o documento pelos títulos #, ## e ### (fora de blocos de código).

    Devolve (caminho da seção, corpo) para cada seção com conteúdo.
    """
    caminho: list[str] = []
    secoes: list[tuple[str, list[str]]] = [("", [])]
    em_codigo = False
    for linha in texto.splitlines():
        if linha.lstrip().startswith("```"):
            em_codigo = not em_codigo
        titulo = None if em_codigo else _TITULO.match(linha)
        if titulo:
            nivel = len(titulo.group(1))
            caminho = caminho[: nivel - 1] + [titulo.group(2)]
            secoes.append((" > ".join(caminho), []))
        else:
            secoes[-1][1].append(linha)
    return [(nome or "(início)", "\n".join(linhas).strip()) for nome, linhas in secoes if "\n".join(linhas).strip()]


def _dividir(texto: str, tamanho_maximo: int, sobreposicao: int) -> list[str]:
    """
    Corta o texto em pedaços de até tamanho_maximo, nos separadores, com sobreposição.

    Os blocos de código (```) entram como uma unidade só, para não serem cortados no meio.
    """
    if len(texto) <= tamanho_maximo:
        return [texto]
    unidades = _unidades(texto, 0, tamanho_maximo)
    pedacos: list[str] = []
    atual = ""
    for unidade, separador in unidades:
        candidato = f"{atual}{separador}{unidade}" if atual else unidade
        if len(candidato) <= tamanho_maximo:
            atual = candidato
            continue
        if atual:
            pedacos.append(atual)
            # Conceito: sobreposição. O novo pedaço começa com o fim do anterior.
            cauda = _cauda(atual, sobreposicao)
            # Por quê: se a cauda + a unidade não cabem, mas a unidade sozinha cabe
            # (ex.: uma tabela), a unidade fica inteira e sem sobreposição: cortar
            # a tabela no meio custaria mais do que perder a repetição.
            cabe = len(cauda) + len(separador) + len(unidade) <= tamanho_maximo
            atual = f"{cauda}{separador}{unidade}" if cauda and cabe else unidade
        else:
            atual = unidade
        while len(atual) > tamanho_maximo:  # unidade sozinha maior que o máximo: corte duro
            pedacos.append(atual[:tamanho_maximo])
            atual = atual[tamanho_maximo - sobreposicao :]
    if atual:
        pedacos.append(atual)
    return pedacos


def _unidades(texto: str, nivel: int, tamanho_maximo: int) -> list[tuple[str, str]]:
    """
    Quebra o texto pelo separador do nível, descendo para o próximo quando a unidade passa de tamanho_maximo.

    Devolve (unidade, separador que vinha antes dela), para remontar o texto fiel.
    """
    separador = SEPARADORES[nivel]
    partes = _juntar_blocos_de_codigo(texto.split(separador)) if nivel == 0 else texto.split(separador)
    unidades: list[tuple[str, str]] = []
    for indice, parte in enumerate(partes):
        antes = separador if indice else ""
        if len(parte) > tamanho_maximo and nivel + 1 < len(SEPARADORES) and not parte.lstrip().startswith("```"):
            internas = _unidades(parte, nivel + 1, tamanho_maximo)
            unidades.append((internas[0][0], antes))
            unidades += internas[1:]
        elif parte:
            unidades.append((parte, antes))
    return unidades


def _juntar_blocos_de_codigo(paragrafos: list[str]) -> list[str]:
    """Reúne os parágrafos de um mesmo bloco de código (que pode ter linhas em branco)."""
    juntos: list[str] = []
    aberto = False
    for paragrafo in paragrafos:
        if aberto:
            juntos[-1] += "\n\n" + paragrafo
        else:
            juntos.append(paragrafo)
        if paragrafo.count("```") % 2 == 1:
            aberto = not aberto
    return juntos


def _cauda(texto: str, tamanho: int) -> str:
    """Últimos caracteres do texto, começando numa palavra inteira (sem cortar no meio da palavra)."""
    if tamanho <= 0:
        return ""
    cauda = texto[-tamanho:]
    espaco = cauda.find(" ")
    return cauda[espaco + 1 :] if 0 <= espaco < len(cauda) - 1 else cauda
