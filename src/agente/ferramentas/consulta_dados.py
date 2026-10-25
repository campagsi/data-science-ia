"""
Acesso aos dados das ferramentas: filtros no banco e cache com tempo de vida.

Conceito
--------
As ferramentas nunca falam com o banco diretamente. O ConsultaDados é a única
porta de entrada, e só tem métodos de LEITURA (política POL-01). Ele recebe
os repositórios prontos (injeção de dependência): em produção, repositórios
ligados ao Azure SQL com o usuário só de leitura do agente; nos testes,
repositórios falsos em memória, sem banco.

Duas preocupações de eficiência:

- filtrar no banco: estação, parâmetros e período vão para o WHERE do
  get_medicoes(), e não para um filtro em Python depois de trazer 105 mil linhas;
- cache com tempo de vida (TTL, time to live): a mesma pergunta repetida, ou o
  LLM chamando duas ferramentas sobre o mesmo recorte, não consulta o banco duas vezes.

O cache é protegido por lock, porque o Flask atende requisições em paralelo,
e tem tamanho máximo, porque cada recorte pode ter dezenas de milhares de linhas.

Documentação: docs/agente/arquitetura.md § 2 e § 10
"""
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.agente.ferramentas.base import ErroDeRegra
from src.database.connection import DatabaseConnection
from src.models.parametro_model import ParametroModel
from src.repository.estacao_repository import EstacaoRepository
from src.repository.leitura_repository import LeituraRepository
from src.repository.municipio_repository import MunicipioRepository
from src.repository.parametro_repository import ParametroRepository

# Os dados mudam só quando a ingestão roda; 5 minutos de cache é seguro.
TTL_CACHE_SEGUNDOS = 300
# Cada recorte de medições pode ter até ~105 mil linhas; poucos ficam em memória.
MAXIMO_RECORTES_EM_CACHE = 8


@dataclass(frozen=True)
class FiltroMedicoes:
    """
    Recorte de medições pedido por uma ferramenta. É imutável e hashable, e serve de chave do cache.

    Args:
        estacao: código da estação (EST-RJ-001) ou None (todas).
        parametros: códigos dos parâmetros, ordenados, ou None (todos).
        data_inicio: data inicial ou None.
        data_fim: data final inclusiva ou None.

    Example:
        >>> FiltroMedicoes(parametros=("TIP-PH",)) == FiltroMedicoes(parametros=("TIP-PH",))
        True
    """

    estacao: str | None = None
    parametros: tuple[str, ...] | None = None
    data_inicio: date | None = None
    data_fim: date | None = None


class ConsultaDados:
    """
    Leitura dos dados com validação de códigos e cache.

    Args:
        leituras: repositório de medições (get_medicoes, get_cobertura, get_operadores, get_assinatura).
        estacoes: repositório de estações (get_all, get_by_codigo).
        municipios: repositório de municípios (get_com_estacoes).
        parametros: repositório de parâmetros (get_all).
        ttl_segundos: tempo de vida do cache.
        relogio: função que devolve o tempo atual em segundos (injetável nos testes).

    Example:
        >>> class Vazio:
        ...     def get_all(self): return []
        ...     def get_com_estacoes(self): return []
        ...     def get_cobertura(self): return []
        >>> ConsultaDados(Vazio(), Vazio(), Vazio(), Vazio()).estacoes()
        []
    """

    def __init__(
        self,
        leituras: LeituraRepository,
        estacoes: EstacaoRepository,
        municipios: MunicipioRepository,
        parametros: ParametroRepository,
        ttl_segundos: float = TTL_CACHE_SEGUNDOS,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        """Guarda os repositórios e cria o cache vazio."""
        self.__leituras = leituras
        self.__estacoes = estacoes
        self.__municipios = municipios
        self.__parametros = parametros
        self.__ttl = ttl_segundos
        self.__relogio = relogio
        self.__cache: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self.__lock = threading.Lock()

    @classmethod
    def do_banco(cls, database: DatabaseConnection) -> "ConsultaDados":
        """
        Monta o ConsultaDados com os repositórios ligados a uma conexão.

        Args:
            database: conexão com a connection string só de leitura do agente
                (AGENTE_SQL_CONNECTIONSTRING, política POL-01).

        Returns:
            ConsultaDados pronto para as ferramentas.
        """
        return cls(
            LeituraRepository(database),
            EstacaoRepository(database),
            MunicipioRepository(database),
            ParametroRepository(database),
        )

    def medicoes(self, filtro: FiltroMedicoes) -> list[dict]:
        """
        Medições do recorte, filtradas no banco.

        Args:
            filtro: estação, parâmetros e período.

        Returns:
            Linhas no formato de LeituraRepository.get_medicoes().

        Raises:
            ErroDeRegra: estação ou parâmetro inexistente.
        """
        estacao_id = self.id_estacao(filtro.estacao) if filtro.estacao else None
        if filtro.parametros:
            self.validar_parametros(filtro.parametros)
        return self.__em_cache(
            ("medicoes", filtro),
            lambda: self.__leituras.get_medicoes(
                estacao_id=estacao_id,
                data_inicio=filtro.data_inicio,
                data_fim=filtro.data_fim,
                codigos_parametro=list(filtro.parametros) if filtro.parametros else None,
            ),
        )

    def id_estacao(self, codigo: str) -> int:
        """
        Converte o código da estação no id usado pelo get_medicoes() (ponto P2).

        Raises:
            ErroDeRegra: código inexistente, com os códigos válidos na mensagem.
        """
        for estacao in self.__estacoes_cadastradas():
            if estacao.codigo_estacao == codigo:
                return estacao.id_estacao
        validos = ", ".join(e.codigo_estacao for e in self.__estacoes_cadastradas()) or "nenhuma"
        raise ErroDeRegra(f"estação inexistente: {codigo}. Estações cadastradas: {validos}")

    def validar_parametros(self, codigos: tuple[str, ...] | list[str]) -> None:
        """
        Confere se todos os códigos de parâmetro existem.

        Raises:
            ErroDeRegra: com os códigos desconhecidos e a dica de usar listar_parametros.
        """
        conhecidos = {p.codigo_parametro for p in self.parametros()}
        desconhecidos = sorted(set(codigos) - conhecidos)
        if desconhecidos:
            raise ErroDeRegra(
                f"parâmetro inexistente: {', '.join(desconhecidos)}. Use listar_parametros para ver os códigos"
            )

    def parametros(self) -> list[ParametroModel]:
        """Parâmetros cadastrados, com unidade e faixa válida."""
        return self.__em_cache(("parametros",), self.__parametros.get_all)

    def estacoes(self) -> list[dict]:
        """
        Estações cadastradas com município e UF.

        Returns:
            [{"codigo", "nome", "municipio", "uf"}] em ordem de código.
        """
        municipios = {m["id"]: m for m in self.__em_cache(("municipios",), self.__municipios.get_com_estacoes)}
        return [
            {
                "codigo": estacao.codigo_estacao,
                "nome": estacao.nome,
                "municipio": municipios.get(estacao.municipio_id, {}).get("nome"),
                "uf": municipios.get(estacao.municipio_id, {}).get("sigla"),
            }
            for estacao in sorted(self.__estacoes_cadastradas(), key=lambda e: e.codigo_estacao)
        ]

    def resolver_estacao(self, codigo: str | None) -> str:
        """
        O código pedido ou, sem ele, o da única estação cadastrada.

        A existência do código pedido é conferida por medicoes().

        Raises:
            ErroDeRegra: nenhum código e mais de uma estação (ou nenhuma) cadastrada.

        Example:
            >>> from src.agente.ferramentas.dados_exemplo import consulta_de_exemplo
            >>> consulta_de_exemplo().resolver_estacao(None), consulta_de_exemplo().resolver_estacao("EST-9")
            ('EST-1', 'EST-9')
        """
        if codigo is not None:
            return codigo
        codigos = [e["codigo"] for e in self.estacoes()]
        if len(codigos) != 1:
            raise ErroDeRegra(f"há {len(codigos)} estações ({', '.join(codigos)}); informe o argumento estacao")
        return codigos[0]

    def cobertura(self) -> list[dict]:
        """Período coberto e quantidade de leituras por estação (LeituraRepository.get_cobertura)."""
        return self.__em_cache(("cobertura",), self.__leituras.get_cobertura)

    def operadores(self) -> list[dict]:
        """Códigos dos operadores por estação, sem dado pessoal (LeituraRepository.get_operadores)."""
        return self.__em_cache(("operadores",), self.__leituras.get_operadores)

    def assinatura(self) -> dict:
        """
        Assinatura do conteúdo das medições (LeituraRepository.get_assinatura).

        Sem cache: é ela que diz se os dados mudaram desde a última atualização
        da base do agente (src/agente/manutencao.py).
        """
        return self.__leituras.get_assinatura()

    def limpar_cache(self) -> None:
        """Esquece tudo o que está em cache (ex.: depois de uma nova ingestão)."""
        with self.__lock:
            self.__cache.clear()

    def __estacoes_cadastradas(self) -> list:
        """Estações do repositório, em cache."""
        return self.__em_cache(("estacoes",), self.__estacoes.get_all)

    def __em_cache(self, chave: Any, carregar: Callable[[], Any]) -> Any:
        """
        Devolve o valor em cache ou o carrega, respeitando o TTL e o tamanho máximo.

        Por quê: o carregamento acontece fora do lock, para uma consulta lenta
        ao banco não travar as outras requisições.
        """
        agora = self.__relogio()
        with self.__lock:
            guardado = self.__cache.get(chave)
            if guardado and agora - guardado[0] < self.__ttl:
                self.__cache.move_to_end(chave)
                return guardado[1]
        valor = carregar()
        with self.__lock:
            self.__cache[chave] = (agora, valor)
            self.__cache.move_to_end(chave)
            recortes = [c for c in self.__cache if c[0] == "medicoes"]
            if len(recortes) > MAXIMO_RECORTES_EM_CACHE:
                del self.__cache[recortes[0]]
        return valor
