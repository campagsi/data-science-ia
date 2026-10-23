"""
O agente: o laço de tool use com os guardrails.

Conceito
--------
Um agente é um LAÇO, e não uma chamada única ao LLM:

    1. o LLM recebe a pergunta e as especificações das ferramentas;
    2. se pedir ferramentas, o CÓDIGO as executa e devolve os resultados;
    3. o LLM lê os resultados e decide: pede mais ferramentas ou responde.

Isso é decomposição de tarefas: "o pH de junho teve anomalias? o que o alerta
significa?" vira resumo_estatistico → listar_anomalias → resposta.

Os guardrails entram em pontos fixos do laço (id da política entre parênteses):

    entrada   → tamanho e caracteres de controle (POL-05), máscara de PII (POL-02)
    laço      → orçamento de chamadas, tokens e tempo (POL-07); ferramentas só
                de leitura e argumentos validados (POL-01, POL-06, no registro)
    saída     → números conferidos com os resultados (POL-03), máscara da
                resposta (POL-02), fontes montadas pelo código (POL-04)
    sempre    → cada guardrail acionado vai para o log com o id (POL-13)

A conversa só cresce para a frente (append-only): nada já enviado ao LLM é
alterado. O system prompt e as ferramentas são os mesmos em todas as chamadas
de uma pergunta. A correção da POL-03 entra como mensagem NOVA de sistema, e a
resposta forçada mantém as ferramentas e só as proíbe. No Claude Haiku 5.5,
qualquer edição do que já foi enviado invalida os blocos de raciocínio (erro 400).

Onde estudar: docs/agente/arquitetura.md § 5 e docs/agente/guardrails-e-owasp.md § 8
"""
import json
import time
from collections.abc import Callable
from datetime import date

from src.agente.contratos import ChamadaFerramenta, Fonte, Mensagem, RespostaAgente, ResultadoFerramenta
from src.agente.conversa import Conversas
from src.agente.ferramentas.registro import RegistroFerramentas
from src.agente.guardrails.entrada import preparar_pergunta
from src.agente.guardrails.orcamento import OrcamentoPergunta
from src.agente.guardrails.politicas import registrar_acionamento
from src.agente.guardrails.saida import acrescentar_aviso, numeros_sem_origem, pedido_de_correcao
from src.agente.llm.base import ErroProvedorLLM, LLMClient, RespostaLLM
from src.agente.prompts import montar_system_prompt
from src.logger import (
    registrar_chamada_ferramenta,
    registrar_falha_llm,
    registrar_pergunta_agente,
    registrar_resposta_agente,
)
from src.security import mascarar_texto_livre

MENSAGEM_FALHA_PROVEDOR = (
    "Não consegui falar com o modelo de linguagem agora. Tente de novo em alguns instantes."
)
MENSAGEM_RECUSA = (
    "Não posso ajudar com esse pedido. Posso responder sobre as medições ambientais, "
    "as análises estatísticas e as regras do projeto."
)
MENSAGEM_SEM_TEXTO = "Não consegui formular uma resposta com os dados disponíveis. Tente reformular a pergunta."
AVISO_CORTADA = "\n\n⚠ A resposta foi interrompida pelo limite de tamanho."
ERRO_LIMITE_CHAMADAS = "limite de chamadas de ferramenta desta pergunta atingido; responda com o que já tem"


class Agente:
    """
    Responde perguntas com o LLM, as ferramentas e os guardrails.

    Args:
        llm: qualquer LLMClient (Claude, ou o roteirizado nos testes).
        registro: catálogo de ferramentas só de leitura.
        conversas: históricos por conversa_id.
        obter_cobertura: devolve o período coberto pelos dados (ConsultaDados.cobertura).
        max_ferramentas: chamadas de ferramenta por pergunta (AGENTE_MAX_FERRAMENTAS).
        max_tokens_pergunta: tokens de entrada acumulados por pergunta (AGENTE_MAX_TOKENS_PERGUNTA).
        prazo_segundos: tempo total por pergunta (AGENTE_PRAZO_PERGUNTA_SEGUNDOS).
        hoje: data de referência (injetável nos testes).
        relogio: tempo em segundos (injetável nos testes).

    Example:
        >>> from src.agente.ferramentas.catalogo import criar_registro
        >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
        >>> from src.agente.llm.roteirizado import LLMRoteirizado
        >>> consulta = consulta_de_exemplo()
        >>> llm = LLMRoteirizado([
        ...     RespostaLLM(chamadas=[ChamadaFerramenta("c1", "resumo_estatistico", {"parametros": ["TIP-PH"]})],
        ...                 motivo_parada="ferramentas"),
        ...     RespostaLLM(texto="O pH médio foi 7,3 (4 medições)."),
        ... ])
        >>> agente = Agente(llm, criar_registro(consulta), Conversas(), consulta.cobertura)
        >>> resposta = agente.perguntar("Qual o pH médio?")
        >>> resposta.texto, resposta.fontes[0].descricao
        ('O pH médio foi 7,3 (4 medições).', 'resumo_estatistico(parametros=["TIP-PH"])')
    """

    def __init__(
        self,
        llm: LLMClient,
        registro: RegistroFerramentas,
        conversas: Conversas,
        obter_cobertura: Callable[[], list[dict]],
        max_ferramentas: int = 6,
        max_tokens_pergunta: int = 60000,
        prazo_segundos: float = 180,
        hoje: Callable[[], date] = date.today,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        """Guarda as dependências (injeção de dependência: o teste troca o LLM pelo roteirizado)."""
        self.__llm = llm
        self.__registro = registro
        self.__conversas = conversas
        self.__obter_cobertura = obter_cobertura
        self.__max_ferramentas = max_ferramentas
        self.__max_tokens = max_tokens_pergunta
        self.__prazo = prazo_segundos
        self.__hoje = hoje
        self.__relogio = relogio

    def perguntar(self, pergunta: str, conversa_id: str | None = None) -> RespostaAgente:
        """
        Responde uma pergunta, continuando a conversa quando há conversa_id.

        Args:
            pergunta: texto digitado pelo usuário.
            conversa_id: conversa a continuar ("e em julho?"). None = conversa nova.

        Returns:
            RespostaAgente com o texto, as fontes, os tokens e o tempo. Se o
            provedor falhar, o texto é uma mensagem amigável e falhou=True.

        Raises:
            PerguntaInvalida: pergunta vazia ou com mais de 1.000 caracteres (POL-05).
            ValueError: conversa_id fora do formato.
        """
        preparada = preparar_pergunta(pergunta)
        conversa = self.__conversas.obter(conversa_id)
        registrar_pergunta_agente(conversa.id, preparada.texto)
        if preparada.mascarada:
            registrar_acionamento("POL-02", conversa.id, acao="mascara_pergunta")

        # Por quê: montados UMA vez. System e ferramentas iguais em todas as chamadas da pergunta.
        system = montar_system_prompt(self.__hoje(), self.__obter_cobertura(), self.__registro.nomes())
        ferramentas = self.__registro.especificacoes()
        historico = conversa.mensagens
        mensagens = [*historico, Mensagem.usuario(preparada.texto)]
        orcamento = OrcamentoPergunta(self.__max_ferramentas, self.__max_tokens, self.__prazo, self.__relogio)
        contexto = [preparada.texto, system, *(m.texto for m in historico)]
        fontes: list[Fonte] = []
        resultados: list[ResultadoFerramenta] = []
        correcao_pedida = False

        try:
            while True:
                permitir = orcamento.permite_ferramentas()
                if not permitir:
                    registrar_acionamento("POL-07", conversa.id, acao="resposta_forcada", motivo=orcamento.motivo_esgotado())
                resposta = self.__llm.gerar(system, mensagens, ferramentas, permitir_ferramentas=permitir)
                orcamento.registrar_tokens(resposta.tokens_entrada, resposta.tokens_saida)

                if resposta.motivo_parada == "recusa":
                    registrar_acionamento("POL-11", conversa.id, acao="recusa_do_modelo")
                    texto = MENSAGEM_RECUSA
                    break

                if resposta.chamadas and permitir:
                    mensagens.append(Mensagem.assistente(resposta.texto, resposta.chamadas, resposta.bruto))
                    rodada = self.__executar(conversa.id, resposta.chamadas, orcamento)
                    mensagens.append(Mensagem.ferramenta(rodada))
                    resultados += rodada
                    fontes += [Fonte.de_chamada(c) for c, r in zip(resposta.chamadas, rodada) if r.sucesso]
                    continue

                texto = self.__texto_final(conversa.id, resposta)
                sem_origem = numeros_sem_origem(texto, resultados, contexto)
                if sem_origem and not correcao_pedida and orcamento.permite_correcao():
                    # POL-03: a resposta com número sem origem NÃO entra no histórico;
                    # o pedido de correção é acrescentado no fim (append-only).
                    correcao_pedida = True
                    registrar_acionamento("POL-03", conversa.id, acao="correcao", numeros=len(sem_origem))
                    mensagens.append(Mensagem.sistema(pedido_de_correcao(sem_origem)))
                    continue
                if sem_origem:
                    registrar_acionamento("POL-03", conversa.id, acao="aviso", numeros=len(sem_origem))
                    texto = acrescentar_aviso(texto, sem_origem)
                break
        except ErroProvedorLLM as erro:
            registrar_falha_llm(conversa.id, str(erro))
            return self.__resposta(MENSAGEM_FALHA_PROVEDOR, conversa.id, fontes, orcamento, falhou=True)

        mascarado = mascarar_texto_livre(texto)
        if mascarado != texto:
            registrar_acionamento("POL-02", conversa.id, acao="mascara_resposta")
        conversa.registrar(preparada.texto, mascarado)
        return self.__resposta(mascarado, conversa.id, fontes, orcamento)

    def __executar(
        self, conversa_id: str, chamadas: tuple[ChamadaFerramenta, ...], orcamento: OrcamentoPergunta
    ) -> list[ResultadoFerramenta]:
        """
        Executa as chamadas que cabem no orçamento e recusa as que passam dele.

        Toda chamada recebe um resultado (a API exige um tool_result por
        tool_use), inclusive as recusadas pelo limite (POL-07).
        """
        restantes = orcamento.restantes()
        if len(chamadas) > restantes:
            registrar_acionamento("POL-07", conversa_id, acao="chamadas_excedentes", pedidas=len(chamadas), permitidas=restantes)
        resultados = []
        for indice, chamada in enumerate(chamadas):
            if indice >= restantes:
                resultados.append(ResultadoFerramenta.falha(chamada.id, ERRO_LIMITE_CHAMADAS))
                continue
            inicio = self.__relogio()
            resultado = self.__registro.executar(chamada)
            registrar_chamada_ferramenta(
                conversa_id,
                chamada.nome,
                json.dumps(chamada.argumentos, ensure_ascii=False, default=str),
                resultado.sucesso,
                int((self.__relogio() - inicio) * 1000),
                resultado.erro,
            )
            resultados.append(resultado)
        orcamento.registrar_chamadas(min(len(chamadas), restantes))
        return resultados

    @staticmethod
    def __texto_final(conversa_id: str, resposta: RespostaLLM) -> str:
        """Texto da resposta final, com aviso quando foi cortada pelo limite de tokens (POL-07)."""
        texto = resposta.texto.strip() or MENSAGEM_SEM_TEXTO
        if resposta.motivo_parada == "limite_tokens":
            registrar_acionamento("POL-07", conversa_id, acao="resposta_cortada")
            texto += AVISO_CORTADA
        return texto

    @staticmethod
    def __resposta(
        texto: str, conversa_id: str, fontes: list[Fonte], orcamento: OrcamentoPergunta, falhou: bool = False
    ) -> RespostaAgente:
        """Monta a RespostaAgente e registra a linha de resposta no log."""
        ms = orcamento.milissegundos()
        registrar_resposta_agente(conversa_id, len(fontes), orcamento.tokens_entrada, orcamento.tokens_saida, ms)
        return RespostaAgente(
            texto=texto,
            conversa_id=conversa_id,
            fontes=tuple(fontes),
            tokens_entrada=orcamento.tokens_entrada,
            tokens_saida=orcamento.tokens_saida,
            latencia_ms=ms,
            falhou=falhou,
        )
