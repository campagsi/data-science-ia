"""
Bancos vetoriais do agente: em memória (numpy, Fase 4) e ChromaDB (Fase 5).

Conceito
--------
Um banco vetorial guarda, para cada trecho, o vetor (embedding) e os dados do
trecho, e responde "quais trechos têm o vetor mais parecido com este?".

Com os vetores normalizados, a similaridade de cosseno de TODOS os trechos com
a consulta é uma única multiplicação de matriz:

    similaridades = matriz (N × 384) @ consulta (384)   →   N números entre -1 e 1

Depois é só ordenar. Isso é busca EXATA por força bruta. Com ~700 trechos, é
instantânea. Índices aproximados (HNSW, no ChromaDB da Fase 5) só compensam a
partir de centenas de milhares de vetores.

Persistência: os vetores vão para um .npz (formato do numpy) e os dados dos
trechos, o modelo e a dimensão vão para um .json, os dois em data/agente/ (fora do Git).
Guardar o modelo permite recusar um índice criado com outro modelo: misturar
vetores de modelos diferentes daria similaridades sem sentido.

ChromaDB (decisão DA3): banco vetorial "de verdade", embutido no processo e
salvo em data/agente/chroma. Ele usa um índice HNSW (Hierarchical Navigable
Small World): em vez de comparar a consulta com TODOS os vetores, navega por um
grafo de vizinhos. A busca é APROXIMADA, mas muito mais rápida em coleções
grandes. As duas implementações seguem a mesma interface (VectorStore), e um
teste confere que devolvem os mesmos trechos.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-Rags-Embenddings/rag_pipeline.py (VectorStore)
Documentação: docs/agente/rag.md § 5 e docs/agente/bibliotecas.md § 4.6
"""
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

ARQUIVO_VETORES = "indice_docs.npz"
ARQUIVO_DADOS = "indice_docs.json"
PASTA_CHROMA = "chroma"
COLECAO_CHROMA = "docs"
TIPOS = ("memoria", "chroma")


@dataclass(frozen=True)
class RegistroIndice:
    """
    Um trecho guardado no índice.

    Args:
        id: sha256(modelo + arquivo + seção + texto), ver indexador.py.
        arquivo: caminho relativo do documento.
        secao: caminho dos títulos.
        texto: conteúdo do trecho (já mascarado, POL-02).

    Example:
        >>> RegistroIndice("abc", "docs/x.md", "Título", "Texto.").arquivo
        'docs/x.md'
    """

    id: str
    arquivo: str
    secao: str
    texto: str


@dataclass(frozen=True)
class TrechoEncontrado:
    """
    Resultado de uma busca: o trecho e a similaridade de cosseno com a consulta.

    Example:
        >>> TrechoEncontrado("abc", "docs/x.md", "Título", "Texto.", 0.71).similaridade
        0.71
    """

    id: str
    arquivo: str
    secao: str
    texto: str
    similaridade: float


@runtime_checkable
class VectorStore(Protocol):
    """
    Interface de qualquer banco vetorial do agente (memória na Fase 4, ChromaDB na Fase 5).

    Example:
        >>> isinstance(VectorStoreMemoria("simulado", 4), VectorStore)
        True
    """

    modelo: str
    dimensoes: int

    def ids(self) -> set[str]:
        """Ids dos trechos guardados."""
        ...

    def persistir(self) -> None:
        """Garante que o índice está gravado em disco."""
        ...

    def inserir(self, registros: list[RegistroIndice], vetores: np.ndarray) -> None:
        """Acrescenta trechos com seus vetores normalizados."""
        ...

    def remover(self, ids: set[str]) -> None:
        """Retira os trechos dos ids."""
        ...

    def buscar(self, vetor: np.ndarray, top_k: int) -> list[TrechoEncontrado]:
        """Os top_k trechos mais parecidos com o vetor, do mais para o menos parecido."""
        ...


class VectorStoreMemoria:
    """
    Banco vetorial exato em memória, com salvar() e carregar() em arquivo.

    Args:
        modelo: modelo de embeddings dos vetores guardados.
        dimensoes: tamanho de cada vetor.

    Example:
        >>> store = VectorStoreMemoria("simulado", 2)
        >>> store.inserir([RegistroIndice("a", "x.md", "S", "pH"), RegistroIndice("b", "y.md", "S", "vento")],
        ...               np.array([[1.0, 0.0], [0.0, 1.0]]))
        >>> [(t.id, round(t.similaridade, 2)) for t in store.buscar(np.array([0.8, 0.6]), 2)]
        [('a', 0.8), ('b', 0.6)]
    """

    def __init__(self, modelo: str, dimensoes: int, pasta: Path | None = None) -> None:
        """Índice vazio para o modelo e a dimensão; pasta = onde persistir() grava."""
        self.modelo = modelo
        self.dimensoes = dimensoes
        self.pasta = pasta
        self.__registros: list[RegistroIndice] = []
        self.__vetores = np.zeros((0, dimensoes), dtype=np.float32)
        # Por quê: o Flask atende em paralelo; buscar enquanto outro processo indexa não pode ver meio índice.
        self.__lock = threading.Lock()

    def __len__(self) -> int:
        """Quantidade de trechos guardados."""
        return len(self.__registros)

    def ids(self) -> set[str]:
        """Ids dos trechos guardados."""
        with self.__lock:
            return {registro.id for registro in self.__registros}

    def inserir(self, registros: list[RegistroIndice], vetores: np.ndarray) -> None:
        """
        Acrescenta trechos e vetores.

        Raises:
            ValueError: quantidade de vetores diferente da de trechos, ou dimensão errada.
        """
        if not registros:
            return
        vetores = np.asarray(vetores, dtype=np.float32)
        if vetores.shape != (len(registros), self.dimensoes):
            raise ValueError(f"esperava vetores {(len(registros), self.dimensoes)}, recebeu {vetores.shape}")
        with self.__lock:
            self.__registros += registros
            self.__vetores = np.vstack([self.__vetores, vetores])

    def remover(self, ids: set[str]) -> None:
        """Retira os trechos dos ids (ids desconhecidos são ignorados)."""
        if not ids:
            return
        with self.__lock:
            manter = [indice for indice, registro in enumerate(self.__registros) if registro.id not in ids]
            self.__registros = [self.__registros[indice] for indice in manter]
            self.__vetores = self.__vetores[manter]

    def buscar(self, vetor: np.ndarray, top_k: int) -> list[TrechoEncontrado]:
        """Os top_k mais parecidos, por similaridade de cosseno (produto escalar de vetores normalizados)."""
        with self.__lock:
            if not self.__registros:
                return []
            # Conceito: busca exata por força bruta = uma multiplicação de matriz.
            similaridades = self.__vetores @ np.asarray(vetor, dtype=np.float32)
            ordem = np.argsort(-similaridades)[:top_k]
            return [TrechoEncontrado(**asdict(self.__registros[i]), similaridade=float(similaridades[i])) for i in ordem]

    def persistir(self) -> None:
        """Grava na pasta do índice (se houver uma)."""
        if self.pasta is not None:
            self.salvar(self.pasta)

    def salvar(self, pasta: Path) -> None:
        """Grava vetores (.npz) e dados (.json) na pasta, criando-a se precisar."""
        pasta.mkdir(parents=True, exist_ok=True)
        with self.__lock:
            np.savez(pasta / ARQUIVO_VETORES, vetores=self.__vetores)
            dados = {"modelo": self.modelo, "dimensoes": self.dimensoes, "registros": [asdict(r) for r in self.__registros]}
        (pasta / ARQUIVO_DADOS).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def carregar(cls, pasta: Path) -> "VectorStoreMemoria | None":
        """
        Índice salvo na pasta, ou None se ainda não houver (rode python main.py --indexar).

        Raises:
            ValueError: arquivos inconsistentes (quantidade de vetores ≠ de trechos).
        """
        if not (pasta / ARQUIVO_DADOS).exists() or not (pasta / ARQUIVO_VETORES).exists():
            return None
        dados = json.loads((pasta / ARQUIVO_DADOS).read_text(encoding="utf-8"))
        with np.load(pasta / ARQUIVO_VETORES) as arquivo:
            vetores = arquivo["vetores"]
        store = cls(dados["modelo"], dados["dimensoes"], pasta)
        registros = [RegistroIndice(**r) for r in dados["registros"]]
        if len(registros) != len(vetores):
            raise ValueError("índice corrompido: quantidade de vetores diferente da de trechos; rode --indexar de novo")
        store.inserir(registros, vetores)
        return store


class VectorStoreChroma:
    """
    Banco vetorial persistente com o ChromaDB (índice HNSW, distância de cosseno).

    Args:
        pasta: pasta do índice (data/agente); o Chroma grava em pasta/chroma.
        modelo: modelo de embeddings dos vetores (guardado nos metadados da coleção).
        dimensoes: tamanho de cada vetor.

    Example:
        >>> import tempfile
        >>> store = VectorStoreChroma(Path(tempfile.mkdtemp()), "simulado", 2)
        >>> store.inserir([RegistroIndice("a", "x.md", "S", "pH"), RegistroIndice("b", "y.md", "S", "vento")],
        ...               np.array([[1.0, 0.0], [0.0, 1.0]]))
        >>> [(t.id, round(t.similaridade, 2)) for t in store.buscar(np.array([0.8, 0.6]), 2)]
        [('a', 0.8), ('b', 0.6)]
    """

    def __init__(self, pasta: Path, modelo: str, dimensoes: int) -> None:
        """Abre (ou cria) a coleção na pasta, com o modelo e a dimensão nos metadados."""
        self.modelo = modelo
        self.dimensoes = dimensoes
        self.__cliente = _cliente_chroma(pasta)
        # Cuidado: embedding_function=None. Sem isso, o Chroma usaria o modelo
        # padrão dele, que baixa outro modelo e gera vetores incompatíveis com os nossos.
        self.__colecao = self.__cliente.get_or_create_collection(
            name=COLECAO_CHROMA,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"modelo": modelo, "dimensoes": dimensoes},
        )
        self.__lote = self.__cliente.get_max_batch_size()
        self.__lock = threading.Lock()

    @classmethod
    def abrir(cls, pasta: Path) -> "VectorStoreChroma | None":
        """
        Coleção já existente na pasta, ou None se ainda não houver índice.

        Example:
            >>> import tempfile
            >>> VectorStoreChroma.abrir(Path(tempfile.mkdtemp())) is None
            True
        """
        if not (pasta / PASTA_CHROMA).exists():
            return None
        cliente = _cliente_chroma(pasta)
        if COLECAO_CHROMA not in [colecao.name for colecao in cliente.list_collections()]:
            return None
        metadados = cliente.get_collection(COLECAO_CHROMA, embedding_function=None).metadata or {}
        return cls(pasta, metadados.get("modelo", ""), int(metadados.get("dimensoes", 0)))

    @classmethod
    def novo(cls, pasta: Path, modelo: str, dimensoes: int) -> "VectorStoreChroma":
        """Coleção vazia, apagando a anterior (usado quando o modelo de embeddings muda)."""
        cliente = _cliente_chroma(pasta)
        if COLECAO_CHROMA in [colecao.name for colecao in cliente.list_collections()]:
            cliente.delete_collection(COLECAO_CHROMA)
        return cls(pasta, modelo, dimensoes)

    def __len__(self) -> int:
        """Quantidade de trechos guardados."""
        return self.__colecao.count()

    def ids(self) -> set[str]:
        """Ids dos trechos guardados."""
        with self.__lock:
            return set(self.__colecao.get(include=[])["ids"])

    def inserir(self, registros: list[RegistroIndice], vetores: np.ndarray) -> None:
        """
        Acrescenta trechos e vetores, em lotes do tamanho máximo aceito pelo Chroma.

        Raises:
            ValueError: quantidade de vetores diferente da de trechos, ou dimensão errada.
        """
        if not registros:
            return
        vetores = np.asarray(vetores, dtype=np.float32)
        if vetores.shape != (len(registros), self.dimensoes):
            raise ValueError(f"esperava vetores {(len(registros), self.dimensoes)}, recebeu {vetores.shape}")
        with self.__lock:
            for inicio in range(0, len(registros), self.__lote):
                fatia = registros[inicio : inicio + self.__lote]
                self.__colecao.add(
                    ids=[r.id for r in fatia],
                    embeddings=vetores[inicio : inicio + self.__lote].tolist(),
                    documents=[r.texto for r in fatia],
                    metadatas=[{"arquivo": r.arquivo, "secao": r.secao} for r in fatia],
                )

    def remover(self, ids: set[str]) -> None:
        """Retira os trechos dos ids (ids desconhecidos são ignorados)."""
        lista = sorted(ids)
        with self.__lock:
            for inicio in range(0, len(lista), self.__lote):
                self.__colecao.delete(ids=lista[inicio : inicio + self.__lote])

    def buscar(self, vetor: np.ndarray, top_k: int) -> list[TrechoEncontrado]:
        """
        Os top_k mais parecidos pelo índice HNSW.

        Conceito: o Chroma devolve a DISTÂNCIA de cosseno (0 = idêntico), e não a
        similaridade. Como distância = 1 - cosseno, a similaridade é 1 - distância.
        Assim o limiar do Recuperador vale igual nos dois bancos.
        """
        with self.__lock:
            total = self.__colecao.count()
            if not total:
                return []
            resultado = self.__colecao.query(
                query_embeddings=[np.asarray(vetor, dtype=np.float32).tolist()],
                n_results=min(top_k, total),
                include=["documents", "metadatas", "distances"],
            )
        return [
            TrechoEncontrado(identificador, metadados["arquivo"], metadados["secao"], texto, 1.0 - float(distancia))
            for identificador, texto, metadados, distancia in zip(
                resultado["ids"][0], resultado["documents"][0], resultado["metadatas"][0], resultado["distances"][0]
            )
        ]

    def persistir(self) -> None:
        """Nada a fazer: o PersistentClient grava cada alteração em disco."""


def _cliente_chroma(pasta: Path):
    """
    Cliente persistente do Chroma em pasta/chroma, sem telemetria.

    Por quê: o Chroma envia telemetria anônima por padrão. Um índice local da
    documentação não tem motivo para mandar dado de uso para fora (risco LLM03).
    """
    # Por quê: import aqui para quem usa o banco em memória não carregar o Chroma.
    import chromadb

    (pasta / PASTA_CHROMA).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(pasta / PASTA_CHROMA), settings=chromadb.Settings(anonymized_telemetry=False)
    )


def abrir_indice(tipo: str, pasta: Path) -> VectorStore | None:
    """
    Índice existente do tipo ("memoria" ou "chroma"), ou None se ainda não houver.

    Raises:
        ValueError: tipo desconhecido.

    Example:
        >>> import tempfile
        >>> abrir_indice("memoria", Path(tempfile.mkdtemp())) is None
        True
    """
    if tipo == "memoria":
        return VectorStoreMemoria.carregar(pasta)
    if tipo == "chroma":
        return VectorStoreChroma.abrir(pasta)
    raise ValueError(f"banco vetorial desconhecido: {tipo}. Use um destes: {', '.join(TIPOS)}")


def novo_indice(tipo: str, pasta: Path, modelo: str, dimensoes: int) -> VectorStore:
    """
    Índice vazio do tipo, substituindo o que houver na pasta (troca de modelo).

    Example:
        >>> import tempfile
        >>> len(novo_indice("memoria", Path(tempfile.mkdtemp()), "simulado", 4))
        0
    """
    if tipo == "memoria":
        return VectorStoreMemoria(modelo, dimensoes, pasta)
    if tipo == "chroma":
        return VectorStoreChroma.novo(pasta, modelo, dimensoes)
    raise ValueError(f"banco vetorial desconhecido: {tipo}. Use um destes: {', '.join(TIPOS)}")
