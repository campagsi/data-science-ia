"""
Salvar e carregar o modelo de previsão com conferência de integridade (POL-12).

Conceito
--------
O modelo treinado vai para um arquivo com joblib (pickle). Carregar um pickle
EXECUTA CÓDIGO: um arquivo adulterado pode rodar qualquer comando na máquina
(risco LLM03, cadeia de suprimentos do OWASP Top 10 para LLM). Por isso:

    data/agente/modelos/previsao/
    ├── modelo.joblib      os Pipelines treinados
    └── metadados.json     métricas, horizontes aprovados, período de treino,
                           versão do scikit-learn e o SHA-256 do modelo.joblib

Antes do joblib.load, o código confere:

1. o SHA-256 do arquivo é igual ao do metadados.json (arquivo trocado ou
   corrompido é recusado);
2. a versão do scikit-learn é a mesma do treino (um pickle de outra versão
   pode carregar e prever errado sem erro nenhum).

Limitação: o hash protege contra troca acidental ou parcial, mas quem consegue
escrever nos DOIS arquivos consegue gerar um par válido. A proteção de fundo é
a pasta ser local e fora do Git, e nunca carregar um modelo baixado de fora.

Documentação: docs/agente/ferramentas.md § 4.12 e docs/agente/guardrails-e-owasp.md (POL-12)
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.logger import registrar_guardrail
from src.previsao.treino import AvaliacaoHorizonte

ARQUIVO_MODELO = "modelo.joblib"
ARQUIVO_METADADOS = "metadados.json"


def sha256_do_arquivo(caminho: Path) -> str:
    """
    SHA-256 do conteúdo do arquivo, em hexadecimal.

    Example:
        >>> import tempfile
        >>> arquivo = Path(tempfile.mkdtemp()) / "x.bin"
        >>> _ = arquivo.write_bytes(b"abc")
        >>> sha256_do_arquivo(arquivo)[:16]
        'ba7816bf8f01cfea'
    """
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def salvar_modelo(avaliacoes: list[AvaliacaoHorizonte], pasta: Path, agora: datetime | None = None) -> Path:
    """
    Grava os Pipelines aprovados e o metadados.json (com todas as avaliações, aprovadas ou não).

    Returns:
        O caminho do metadados.json.

    Example:
        >>> import tempfile
        >>> pasta = Path(tempfile.mkdtemp())
        >>> json.loads(salvar_modelo([], pasta, datetime(2026, 10, 21)).read_text(encoding="utf-8"))["aprovados"]
        []
    """
    import joblib
    import sklearn

    pasta.mkdir(parents=True, exist_ok=True)
    caminho_modelo = pasta / ARQUIVO_MODELO
    joblib.dump({a.chave: a.pipeline for a in avaliacoes if a.aprovado}, caminho_modelo)
    metadados = {
        "criado_em": (agora or datetime.now()).isoformat(timespec="seconds"),
        "versao_sklearn": sklearn.__version__,
        "sha256": sha256_do_arquivo(caminho_modelo),
        "aprovados": sorted(a.chave for a in avaliacoes if a.aprovado),
        "avaliacoes": {
            a.chave: {
                "estacao": a.estacao, "parametro": a.parametro, "horas": a.horas, "modelo": a.modelo,
                "aprovado": a.aprovado, "validacao": a.validacao, "teste": a.teste,
                "n_treino": a.n_treino, "n_teste": a.n_teste, "periodo": list(a.periodo),
            }
            for a in avaliacoes
        },
    }
    caminho = pasta / ARQUIVO_METADADOS
    caminho.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


@dataclass(frozen=True)
class ModeloPrevisao:
    """
    O modelo carregado: os Pipelines aprovados e as avaliações do treino.

    Args:
        pipelines: chave "estação|parâmetro|horas" → Pipeline.
        metadados: o conteúdo do metadados.json.

    Example:
        >>> modelo = ModeloPrevisao({}, {"avaliacoes": {"EST-1|TIP-TMP|6": {"aprovado": False}}})
        >>> modelo.avaliacao("EST-1", "TIP-TMP", 6)["aprovado"], modelo.avaliacao("EST-1", "TIP-TMP", 2)
        (False, None)
    """

    pipelines: dict
    metadados: dict

    def avaliacao(self, estacao: str, parametro: str, horas: int) -> dict | None:
        """As métricas do treino para a combinação, ou None se ela não foi treinada."""
        return self.metadados["avaliacoes"].get(f"{estacao}|{parametro}|{horas}")

    def pipeline(self, estacao: str, parametro: str, horas: int):
        """O Pipeline aprovado, ou None (não treinado ou não supera o baseline)."""
        return self.pipelines.get(f"{estacao}|{parametro}|{horas}")


def carregar_modelo(pasta: Path) -> ModeloPrevisao | None:
    """
    O modelo salvo, só se o SHA-256 e a versão do scikit-learn conferirem (POL-12).

    Returns:
        ModeloPrevisao, ou None (com aviso no log) se não existe, foi alterado ou
        é de outra versão do scikit-learn.

    Example:
        >>> import tempfile
        >>> carregar_modelo(Path(tempfile.mkdtemp())) is None
        True
    """
    import sklearn

    caminho_modelo, caminho_metadados = pasta / ARQUIVO_MODELO, pasta / ARQUIVO_METADADOS
    if not caminho_modelo.exists() or not caminho_metadados.exists():
        return None
    metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    if sha256_do_arquivo(caminho_modelo) != metadados.get("sha256"):
        registrar_guardrail("POL-12", "treino", acao="modelo_recusado", motivo="sha256_diferente")
        return None
    if metadados.get("versao_sklearn") != sklearn.__version__:
        registrar_guardrail("POL-12", "treino", acao="modelo_recusado", motivo="versao_sklearn", treino=metadados.get("versao_sklearn"), atual=sklearn.__version__)
        return None
    import joblib

    # Cuidado: só depois das duas conferências. joblib.load executa o pickle.
    return ModeloPrevisao(joblib.load(caminho_modelo), metadados)
