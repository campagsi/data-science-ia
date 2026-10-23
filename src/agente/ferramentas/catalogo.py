"""
Catálogo de ferramentas do agente: o que o LLM pode pedir.

Conceito
--------
Menor privilégio (least privilege): o agente só recebe as ferramentas de que
precisa, e todas são de LEITURA. A forma mais forte de impedir que o LLM grave
no banco não é bloquear a gravação, é não existir ferramenta que grave
(política POL-01, risco LLM06 "Excessive Agency" do OWASP Top 10 para LLM).

FERRAMENTAS_PERMITIDAS é a lista fechada de nomes. Montar um catálogo com
qualquer outro nome falha: uma ferramenta nova só entra com o nome acrescentado
aqui, de forma explícita e revisada.

buscar_documentacao só entra quando há um índice da documentação (python main.py
--indexar). Sem ele, o agente continua respondendo números, e o system prompt
avisa que não há ferramenta de documentação. Do mesmo jeito, dias_semelhantes só
entra quando há o índice dos dias (python main.py --indexar-dias, Fase 9), e prever,
quando há um modelo treinado localmente com o hash conferido (Fase 10, POL-12).

Documentação: docs/agente/guardrails-e-owasp.md § 4 e § 9
"""
from src.agente.dias.indice import BuscaDeDias
from src.agente.ferramentas.consulta_dados import ConsultaDados
from src.agente.ferramentas.dias import criar_ferramenta_dias_semelhantes
from src.agente.ferramentas.descritivas import criar_ferramentas_descritivas
from src.agente.ferramentas.documentacao import criar_ferramenta_documentacao
from src.agente.ferramentas.inferencia import criar_ferramentas_inferencia
from src.agente.ferramentas.previsao import criar_ferramenta_prever
from src.agente.ferramentas.registro import RegistroFerramentas
from src.agente.rag.recuperador import Recuperador
from src.previsao.persistencia import ModeloPrevisao

FERRAMENTAS_DE_DADOS = (
    "panorama_dados",
    "listar_parametros",
    "resumo_estatistico",
    "listar_anomalias",
    "serie_temporal",
    "perfil_horario",
    "comparar_periodos",
    "correlacao",
    "probabilidade_evento",
)
# As três últimas só entram quando existe o que elas leem: o índice da documentação,
# o índice dos dias e o modelo de previsão treinado (com o hash conferido).
FERRAMENTAS_PERMITIDAS = FERRAMENTAS_DE_DADOS + ("buscar_documentacao", "dias_semelhantes", "prever")


def criar_registro(
    consulta: ConsultaDados,
    max_linhas: int = 50,
    recuperador: Recuperador | None = None,
    dias: BuscaDeDias | None = None,
    modelo_previsao: ModeloPrevisao | None = None,
) -> RegistroFerramentas:
    """
    Registro com todas as ferramentas do agente, só de leitura.

    Args:
        consulta: acesso aos dados (ligado à conexão só de leitura do agente).
        max_linhas: máximo de itens por lista no retorno (AGENTE_MAX_LINHAS).
        recuperador: busca na documentação. None = sem buscar_documentacao.
        dias: busca no índice dos dias (Fase 9). None = sem dias_semelhantes.
        modelo_previsao: modelo carregado e conferido (Fase 10). None = sem prever.

    Returns:
        RegistroFerramentas pronto para o orquestrador.

    Raises:
        RuntimeError: o catálogo montado tem nome fora de FERRAMENTAS_PERMITIDAS.

    Example:
        >>> class Vazio:
        ...     def get_all(self): return []
        ...     def get_com_estacoes(self): return []
        ...     def get_cobertura(self): return []
        >>> criar_registro(ConsultaDados(Vazio(), Vazio(), Vazio(), Vazio())).nomes() == FERRAMENTAS_DE_DADOS
        True
    """
    registro = RegistroFerramentas(max_linhas)
    ferramentas = criar_ferramentas_descritivas(consulta) + criar_ferramentas_inferencia(consulta)
    if recuperador is not None:
        ferramentas.append(criar_ferramenta_documentacao(recuperador))
    if dias is not None:
        ferramentas.append(criar_ferramenta_dias_semelhantes(consulta, dias))
    if modelo_previsao is not None:
        ferramentas.append(criar_ferramenta_prever(consulta, modelo_previsao))
    for ferramenta in ferramentas:
        registro.registrar(ferramenta)
    # Por quê: falhar na montagem é melhor que expor ao LLM uma ferramenta não revisada.
    fora_da_lista = [nome for nome in registro.nomes() if nome not in FERRAMENTAS_PERMITIDAS]
    if fora_da_lista or registro.nomes()[: len(FERRAMENTAS_DE_DADOS)] != FERRAMENTAS_DE_DADOS:
        raise RuntimeError(f"catálogo diferente do permitido: {registro.nomes()}")
    return registro
