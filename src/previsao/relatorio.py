"""
Relatório do treino da previsão (python main.py --treinar-previsao), em Markdown.

Conceito
--------
O relatório mostra, para cada parâmetro e horizonte, o erro do modelo ao lado
do erro dos dois baselines. É a evidência da regra de aceite: só é publicado o
horizonte em que o modelo erra menos que os DOIS.

    | Parâmetro | h | Modelo | MAE modelo | MAE ingênuo | MAE sazonal | Teste | Publicado |
    | TIP-TMP   | 6 | Ridge  | 0,62       | 2,10        | 0,95        | 0,66  | ✔         |
    | TIP-TMP   | 1 | Ridge  | 0,31       | 0,29        | 0,95        | 0,33  | ✘ não supera o baseline |

Aviso obrigatório: os dados do projeto são SINTÉTICOS. O modelo pode estar
aprendendo o gerador dos dados, e não o clima. O resultado vale como método.

Documentação: docs/agente/todo.md (Fase 10)
"""
from collections.abc import Sequence
from datetime import datetime

from src.previsao.treino import AvaliacaoHorizonte

AVISO_SINTETICOS = (
    "Os dados do projeto são sintéticos: o modelo pode ter aprendido o gerador dos dados, e não o clima. "
    "O resultado vale como demonstração do método (validação temporal e baselines), e não como previsão do tempo real."
)


def montar_relatorio_treino(avaliacoes: Sequence[AvaliacaoHorizonte], agora: datetime | None = None) -> str:
    """
    Tabela de validação e teste por parâmetro e horizonte, com o aviso de dados sintéticos.

    Example:
        >>> a = AvaliacaoHorizonte("EST-1", "TIP-TMP", 6, "Ridge", True,
        ...     {"modelo": {"mae": 0.62, "rmse": 0.8}, "ingenuo": {"mae": 2.1, "rmse": 2.6}, "ingenuo_sazonal": {"mae": 0.95, "rmse": 1.2}},
        ...     {"modelo": {"mae": 0.66, "rmse": 0.9}}, 4000, 600, ("2026-06-01T00:00:00", "2026-10-01T00:00:00"))
        >>> linhas = montar_relatorio_treino([a], datetime(2026, 10, 21, 10, 0)).splitlines()
        >>> linhas[0], [l for l in linhas if l.startswith("| EST-1")]
        ('# Treino da previsão — 2026-10-21 10:00', ['| EST-1 | TIP-TMP | 6 | Ridge | 0,62 | 2,1 | 0,95 | 0,66 | ✔ |'])
    """
    agora = agora or datetime.now()
    linhas = [
        f"# Treino da previsão — {agora:%Y-%m-%d %H:%M}",
        "",
        f"> {AVISO_SINTETICOS}",
        "",
        "Validação: média das dobras do `TimeSeriesSplit`. Teste: últimas 2 semanas, fora das escolhas. MAE na unidade do parâmetro.",
        "",
        "| Estação | Parâmetro | h | Modelo | MAE modelo | MAE ingênuo | MAE sazonal | MAE teste | Publicado |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in avaliacoes:
        publicado = "✔" if a.aprovado else "✘ não supera o baseline"
        teste = _numero(a.teste["modelo"]["mae"]) if a.teste else "—"
        linhas.append(
            f"| {a.estacao} | {a.parametro} | {a.horas} | {a.modelo} | {_numero(a.validacao['modelo']['mae'])} | "
            f"{_numero(a.validacao['ingenuo']['mae'])} | {_numero(a.validacao['ingenuo_sazonal']['mae'])} | {teste} | {publicado} |"
        )
    aprovados = sum(a.aprovado for a in avaliacoes)
    linhas += ["", f"Publicados: {aprovados} de {len(avaliacoes)} combinações (estação × parâmetro × horizonte)."]
    return "\n".join(linhas) + "\n"


def _numero(valor: float) -> str:
    """Número com até 2 casas e vírgula decimal."""
    return f"{valor:.2f}".rstrip("0").rstrip(".").replace(".", ",")
