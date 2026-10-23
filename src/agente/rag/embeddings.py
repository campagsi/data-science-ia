"""
Embeddings: transformar texto em vetor, de forma que significados parecidos fiquem próximos.

Conceito
--------
Um embedding é um vetor de números (aqui, 384) aprendido por um modelo de
linguagem. "acidez da água" e "pH" ficam perto; "velocidade do vento" fica
longe. É o mesmo conceito do mat_IA.py do módulo (rei, rainha, carro), só que
com dimensões aprendidas em vez de escritas à mão.

Proximidade = similaridade de cosseno: cos(u, v) = u·v / (|u|·|v|).
Com os vetores NORMALIZADOS (norma 1), o cosseno vira só o produto escalar u·v,
e a busca em N trechos é uma multiplicação de matriz. Por isso todo Embedder
devolve vetores normalizados. O fastembed não normaliza (norma ~5,2 medida em
21/10/2026), então a normalização é feita aqui.

Duas implementações da mesma interface (Protocol Embedder):

- EmbedderFastembed: o modelo real da decisão DA2
  (paraphrase-multilingual-MiniLM-L12-v2, ONNX, local). O texto não sai da máquina;
- EmbedderSimulado: "hashing trick" (truque de hashing). Cada palavra vira uma
  posição do vetor por sha256. Textos com palavras em comum ficam parecidos,
  mas sinônimos não ("acidez" ≠ "pH"). Serve para testes rápidos e offline.
  Usa hashlib e não hash(), porque o hash() de str muda a cada processo.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA/matematica_IA/mat_IA.py
Documentação: docs/agente/rag.md § 4 e docs/agente/bibliotecas.md § 4.4
"""
import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

MODELO_PADRAO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Modelos assimétricos (família e5) exigem prefixos diferentes para documento e consulta.
PREFIXOS = {
    "intfloat/multilingual-e5-large": ("passage: ", "query: "),
}
DIMENSOES_CONHECIDAS = {MODELO_PADRAO: 384, "intfloat/multilingual-e5-large": 1024}

_PALAVRA = re.compile(r"\w+", re.UNICODE)


@runtime_checkable
class Embedder(Protocol):
    """
    Interface de qualquer modelo de embeddings do agente.

    Example:
        >>> isinstance(EmbedderSimulado(), Embedder)
        True
    """

    modelo: str  # entra no id de cada trecho: trocar o modelo reindexa tudo

    @property
    def dimensoes(self) -> int:
        """Tamanho de cada vetor."""
        ...

    def vetorizar_documentos(self, textos: list[str]) -> np.ndarray:
        """Matriz (n, dimensoes) com uma linha normalizada por texto."""
        ...

    def vetorizar_consulta(self, texto: str) -> np.ndarray:
        """Vetor (dimensoes,) normalizado da consulta."""
        ...


def normalizar(matriz: np.ndarray) -> np.ndarray:
    """
    Divide cada linha pela sua norma, para cosseno = produto escalar.

    Raises:
        ValueError: alguma linha com norma zero (cosseno indefinido).

    Example:
        >>> [round(float(x), 3) for x in normalizar(np.array([[3.0, 4.0]]))[0]]   # norma 5 → (3/5, 4/5)
        [0.6, 0.8]
    """
    matriz = np.atleast_2d(np.asarray(matriz, dtype=np.float32))
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    if np.any(normas == 0):
        raise ValueError("vetor com norma zero: não dá para calcular o cosseno")
    return matriz / normas


class EmbedderSimulado:
    """
    Embeddings por hashing de palavras: determinísticos, offline e instantâneos.

    Args:
        dimensoes: tamanho do vetor.

    Example:
        >>> embedder = EmbedderSimulado()
        >>> chuva, outra_chuva, vento = embedder.vetorizar_documentos(
        ...     ["chuva e alertas IQR", "alertas IQR da chuva", "velocidade do vento"])
        >>> bool(chuva @ outra_chuva > chuva @ vento)
        True
    """

    def __init__(self, dimensoes: int = 256) -> None:
        """Define o tamanho do vetor e o nome do "modelo" (entra no id dos trechos)."""
        self.__dimensoes = dimensoes
        self.modelo = f"simulado-hashing-{dimensoes}"

    @property
    def dimensoes(self) -> int:
        """Tamanho de cada vetor."""
        return self.__dimensoes

    def vetorizar_documentos(self, textos: list[str]) -> np.ndarray:
        """Um vetor normalizado por texto."""
        return normalizar(np.stack([self.__vetor(texto) for texto in textos]))

    def vetorizar_consulta(self, texto: str) -> np.ndarray:
        """Vetor normalizado da consulta (simétrico: mesmo cálculo dos documentos)."""
        return self.vetorizar_documentos([texto])[0]

    def __vetor(self, texto: str) -> np.ndarray:
        """
        Soma +1 ou -1 na posição de cada palavra, as duas escolhidas pelo sha256 da palavra.

        Por quê: o sinal aleatório faz palavras diferentes que caem na mesma
        posição se anularem em média, em vez de se somarem (colisão de hashing).
        """
        vetor = np.zeros(self.__dimensoes, dtype=np.float32)
        for palavra in _PALAVRA.findall(texto.lower()):
            resumo = hashlib.sha256(palavra.encode("utf-8")).digest()
            posicao = int.from_bytes(resumo[:4], "big") % self.__dimensoes
            vetor[posicao] += 1.0 if resumo[4] % 2 == 0 else -1.0
        if not vetor.any():
            vetor[0] = 1.0  # texto sem palavras: vetor fixo, para não ter norma zero
        return vetor


class EmbedderFastembed:
    """
    Embeddings do modelo real (DA2) com o fastembed, carregado só no primeiro uso.

    Args:
        modelo: nome no catálogo do fastembed (AGENTE_EMBEDDINGS_MODELO).
        pasta_cache: onde o modelo baixado fica guardado. Padrão: data/agente/modelos,
            fora do Git; a pasta temporária do sistema pode ser limpa a qualquer momento.

    Example:
        >>> EmbedderFastembed().dimensoes   # não baixa nada: a dimensão é conhecida
        384
    """

    def __init__(self, modelo: str = MODELO_PADRAO, pasta_cache: Path | None = None) -> None:
        """Guarda o nome e a pasta; o modelo só é carregado na primeira vetorização."""
        self.modelo = modelo
        self.__pasta = pasta_cache or Path(__file__).resolve().parents[3] / "data" / "agente" / "modelos"
        self.__prefixo_documento, self.__prefixo_consulta = PREFIXOS.get(modelo, ("", ""))
        self.__motor = None
        self.__dimensoes = DIMENSOES_CONHECIDAS.get(modelo)
        self.__lock = threading.Lock()

    @property
    def dimensoes(self) -> int:
        """Tamanho de cada vetor (conhecido pelo nome, ou medido no primeiro uso)."""
        if self.__dimensoes is None:
            self.__dimensoes = int(self.vetorizar_consulta("teste").shape[0])
        return self.__dimensoes

    def vetorizar_documentos(self, textos: list[str]) -> np.ndarray:
        """Matriz normalizada, com o prefixo de documento quando o modelo exige."""
        return self.__vetorizar([self.__prefixo_documento + texto for texto in textos])

    def vetorizar_consulta(self, texto: str) -> np.ndarray:
        """Vetor normalizado, com o prefixo de consulta quando o modelo exige."""
        return self.__vetorizar([self.__prefixo_consulta + texto])[0]

    def __vetorizar(self, textos: list[str]) -> np.ndarray:
        """Carrega o modelo (uma vez) e vetoriza em lote."""
        with self.__lock:
            if self.__motor is None:
                # Por quê: import aqui para quem não usa embeddings reais (testes,
                # outros modos do main.py) não carregar o onnxruntime.
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from fastembed import TextEmbedding

                self.__pasta.mkdir(parents=True, exist_ok=True)
                self.__motor = TextEmbedding(self.modelo, cache_dir=str(self.__pasta))
        return normalizar(np.array(list(self.__motor.embed(textos, batch_size=32))))
