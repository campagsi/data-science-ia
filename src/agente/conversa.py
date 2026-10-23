"""
Histórico curto de cada conversa, em memória.

Conceito
--------
O LLM não tem memória entre chamadas: cada chamada recebe a conversa inteira
de novo. É o histórico que permite entender "e em julho?" depois de "qual o pH
médio em junho?". Mas cada turno reenviado custa tokens e ocupa a janela de
contexto, por isso só os últimos N turnos são mantidos (DA6: 10).

Um turno guarda só a pergunta e a resposta final. Os pedidos e os resultados
de ferramentas ficam de fora: a resposta já traz os números que importam, e
o LLM pode chamar a ferramenta de novo se precisar.

O histórico fica só na memória do processo (LGPD: nada é gravado em banco) e
é protegido por lock, porque o Flask atende requisições em paralelo.

Onde estudar: avanade-ds-ia/modulo-3/Fundamentos-IA-Gen/ia_gen_1.py (janela de contexto)
Documentação: docs/agente/arquitetura.md § 2 e docs/agente/seguranca-e-prompts.md § 6
"""
import re
import threading
import uuid
from collections import OrderedDict, deque

from src.agente.contratos import Mensagem

# Por quê: o id vem do navegador na Fase 7. Um formato fechado evita guardar
# texto arbitrário (ou dado pessoal) como chave e no log.
FORMATO_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class Conversa:
    """
    Os últimos turnos (pergunta + resposta) de uma conversa.

    Args:
        conversa_id: identificador da conversa.
        max_turnos: turnos mantidos. Os mais antigos são descartados.

    Example:
        >>> conversa = Conversa("c-1", max_turnos=2)
        >>> conversa.registrar("pH médio em junho?", "7,38.")
        >>> conversa.registrar("E em julho?", "7,41.")
        >>> conversa.registrar("E em agosto?", "7,35.")
        >>> conversa.turnos
        2
        >>> [m.texto for m in conversa.mensagens]
        ['E em julho?', '7,41.', 'E em agosto?', '7,35.']
    """

    def __init__(self, conversa_id: str, max_turnos: int) -> None:
        """Cria a janela vazia de turnos."""
        if max_turnos < 1:
            raise ValueError("max_turnos deve ser pelo menos 1")
        self.id = conversa_id
        # Conceito: deque com maxlen é uma janela deslizante. Ao passar do
        # limite, o turno mais antigo sai sozinho.
        self.__turnos: deque[tuple[Mensagem, Mensagem]] = deque(maxlen=max_turnos)
        self.__lock = threading.Lock()

    @property
    def turnos(self) -> int:
        """Quantidade de turnos guardados."""
        with self.__lock:
            return len(self.__turnos)

    @property
    def mensagens(self) -> tuple[Mensagem, ...]:
        """Histórico na ordem: usuário, assistente, usuário, assistente..."""
        with self.__lock:
            return tuple(mensagem for turno in self.__turnos for mensagem in turno)

    def registrar(self, pergunta: str, resposta: str) -> None:
        """Guarda um turno concluído."""
        turno = (Mensagem.usuario(pergunta), Mensagem.assistente(resposta))
        with self.__lock:
            self.__turnos.append(turno)


class Conversas:
    """
    Conversas ativas, por conversa_id.

    Args:
        max_turnos: turnos mantidos por conversa (AGENTE_HISTORICO_TURNOS).
        max_conversas: conversas mantidas no processo. Ao passar do limite, a
            usada há mais tempo é descartada, para a memória não crescer sem fim.

    Example:
        >>> conversas = Conversas(max_turnos=10)
        >>> nova = conversas.obter()
        >>> nova.id.startswith("c-")
        True
        >>> conversas.obter(nova.id) is nova
        True
        >>> conversas.obter("outra") is nova
        False
        >>> len(conversas)
        2
    """

    def __init__(self, max_turnos: int = 10, max_conversas: int = 1000) -> None:
        """Cria o dicionário vazio de conversas, com os limites."""
        if max_conversas < 1:
            raise ValueError("max_conversas deve ser pelo menos 1")
        self.__max_turnos = max_turnos
        self.__max_conversas = max_conversas
        self.__conversas: OrderedDict[str, Conversa] = OrderedDict()
        self.__lock = threading.Lock()

    def __len__(self) -> int:
        """Quantidade de conversas ativas."""
        with self.__lock:
            return len(self.__conversas)

    def obter(self, conversa_id: str | None = None) -> Conversa:
        """
        Devolve a conversa do id, criando-a se não existir.

        Sem id, cria uma conversa nova com id gerado. Um id desconhecido (ex.:
        o servidor reiniciou) começa uma conversa vazia com esse id.

        Raises:
            ValueError: id fora do formato (letras, números, "_" e "-", até 64).
        """
        if conversa_id is None:
            conversa_id = f"c-{uuid.uuid4().hex[:12]}"
        elif not FORMATO_ID.fullmatch(conversa_id):
            raise ValueError("conversa_id inválido")

        with self.__lock:
            conversa = self.__conversas.get(conversa_id)
            if conversa is None:
                conversa = Conversa(conversa_id, self.__max_turnos)
                self.__conversas[conversa_id] = conversa
                if len(self.__conversas) > self.__max_conversas:
                    self.__conversas.popitem(last=False)
            # Conceito: LRU (least recently used). A conversa usada agora vai
            # para o fim, e a do começo é a que está parada há mais tempo.
            self.__conversas.move_to_end(conversa_id)
            return conversa

    def descartar(self, conversa_id: str) -> None:
        """Esquece a conversa (ex.: botão "nova conversa"). Id desconhecido é ignorado."""
        with self.__lock:
            self.__conversas.pop(conversa_id, None)
