"""
Dados de exemplo em memória, para doctests e estudo sem banco.

Conceito
--------
Injeção de dependência: o ConsultaDados não sabe se os repositórios falam com
o Azure SQL ou com uma lista em memória. Basta ter os mesmos métodos de
LEITURA (get_medicoes, get_cobertura, get_all, get_com_estacoes). Isso é
"duck typing": se anda como um repositório e fala como um repositório, serve.

Os repositórios daqui não têm nenhum método de escrita, como os reais vistos
pelo agente (política POL-01). São usados nos exemplos dos docstrings e no
exemplo offline do agente (e06_agente_offline, Fase 3).

Documentação: docs/agente/guia-estudos.md § 5
"""
import hashlib
from datetime import date, datetime, timedelta

from src.agente.ferramentas.consulta_dados import ConsultaDados
from src.models.estacao_model import EstacaoModel
from src.models.parametro_model import ParametroModel

ESTACAO_EXEMPLO = EstacaoModel(
    id_estacao=1, codigo_estacao="EST-1", nome="Estação 1", municipio_id=1, latitude=-22.9, longitude=-43.2
)
PARAMETRO_EXEMPLO = ParametroModel(
    id_parametro=1, codigo_parametro="TIP-PH", nome="pH", unidade_medida="pH", valor_minimo=0, valor_maximo=14
)
# Código do operador (não é dado pessoal) das medições de exemplo.
OPERADOR_EXEMPLO = "OP-1"


def medicoes_de_exemplo(valores: list[float], horas: list[int] | None = None) -> list[dict]:
    """
    Medições de pH da estação de exemplo, no formato de LeituraRepository.get_medicoes().

    Args:
        valores: um valor por medição.
        horas: horas desde 01/06/2026 00:00 (padrão: 0, 1, 2...).

    Returns:
        Uma linha por medição.

    Example:
        >>> medicoes_de_exemplo([7.0])[0]["data_hora"].isoformat()
        '2026-06-01T00:00:00'
    """
    horas = horas if horas is not None else list(range(len(valores)))
    inicio = datetime(2026, 6, 1)
    return [
        {
            "estacao_id": ESTACAO_EXEMPLO.id_estacao,
            "estacao_codigo": ESTACAO_EXEMPLO.codigo_estacao,
            "estacao": ESTACAO_EXEMPLO.nome,
            "codigo_registro": f"REG-{indice:05d}",
            "data_hora": inicio + timedelta(hours=hora),
            "codigo_parametro": PARAMETRO_EXEMPLO.codigo_parametro,
            "parametro": PARAMETRO_EXEMPLO.nome,
            "unidade_medida": PARAMETRO_EXEMPLO.unidade_medida,
            "valor": valor,
        }
        for indice, (valor, hora) in enumerate(zip(valores, horas))
    ]


class LeiturasEmMemoria:
    """
    Repositório de medições em memória, com os mesmos filtros do get_medicoes().

    Args:
        medicoes: linhas no formato de get_medicoes().

    Example:
        >>> from datetime import date
        >>> leituras = LeiturasEmMemoria(medicoes_de_exemplo([7.0, 7.2]))
        >>> len(leituras.get_medicoes(data_inicio=date(2026, 6, 1))), leituras.get_cobertura()[0]["leituras"]
        (2, 2)
    """

    def __init__(self, medicoes: list[dict]) -> None:
        """Guarda as medições."""
        self.__medicoes = list(medicoes)

    def get_medicoes(
        self,
        estacao_id: int | None = None,
        municipio_id: int | None = None,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        codigos_parametro: list[str] | None = None,
    ) -> list[dict]:
        """Medições do recorte: só data_inicio = aquele dia; as duas datas = intervalo fechado."""
        def no_recorte(medicao: dict) -> bool:
            """Aplica os filtros a uma medição."""
            dia = medicao["data_hora"].date()
            if estacao_id is not None and medicao["estacao_id"] != estacao_id:
                return False
            if data_inicio is not None and data_fim is None and dia != data_inicio:
                return False
            if data_inicio is not None and data_fim is not None and not data_inicio <= dia <= data_fim:
                return False
            return not codigos_parametro or medicao["codigo_parametro"] in codigos_parametro

        return [medicao for medicao in self.__medicoes if no_recorte(medicao)]

    def get_cobertura(self) -> list[dict]:
        """Primeira e última leitura e quantidade de leituras por estação."""
        por_estacao: dict[str, set] = {}
        for medicao in self.__medicoes:
            por_estacao.setdefault(medicao["estacao_codigo"], set()).add((medicao["codigo_registro"], medicao["data_hora"]))
        return [
            {
                "estacao_codigo": codigo,
                "primeira_leitura": min(instante for _, instante in leituras),
                "ultima_leitura": max(instante for _, instante in leituras),
                "leituras": len(leituras),
            }
            for codigo, leituras in sorted(por_estacao.items())
        ]

    def get_operadores(self) -> list[dict]:
        """Códigos dos operadores por estação; medição sem "operador_codigo" conta como OPERADOR_EXEMPLO."""
        por_chave: dict[tuple[str, str], set] = {}
        for medicao in self.__medicoes:
            chave = (medicao["estacao_codigo"], medicao.get("operador_codigo", OPERADOR_EXEMPLO))
            por_chave.setdefault(chave, set()).add((medicao["codigo_registro"], medicao["data_hora"]))
        return [
            {
                "estacao_codigo": estacao,
                "operador_codigo": operador,
                "primeira_leitura": min(instante for _, instante in leituras),
                "ultima_leitura": max(instante for _, instante in leituras),
                "leituras": len(leituras),
            }
            for (estacao, operador), leituras in sorted(por_chave.items())
        ]

    def get_assinatura(self) -> dict:
        """Assinatura do conteúdo, no formato de get_assinatura() (checksum por hash das medições)."""
        chaves = sorted((m["codigo_registro"], m["codigo_parametro"], m["valor"]) for m in self.__medicoes)
        instantes = [m["data_hora"] for m in self.__medicoes]
        return {
            "medicoes": len(chaves),
            "primeira": min(instantes).isoformat() if instantes else None,
            "ultima": max(instantes).isoformat() if instantes else None,
            "checksum": int(hashlib.sha256(repr(chaves).encode("utf-8")).hexdigest()[:8], 16),
        }


class CadastroEmMemoria:
    """
    Repositório de cadastro em memória (estações, municípios ou parâmetros).

    Args:
        itens: o que get_all() e get_com_estacoes() devolvem.

    Example:
        >>> CadastroEmMemoria([ESTACAO_EXEMPLO]).get_all()[0].codigo_estacao
        'EST-1'
    """

    def __init__(self, itens: list) -> None:
        """Guarda os itens."""
        self.__itens = list(itens)

    def get_all(self) -> list:
        """Todos os itens."""
        return list(self.__itens)

    def get_com_estacoes(self) -> list:
        """Municípios com estação (mesmo conteúdo de get_all, no caso dos municípios)."""
        return list(self.__itens)


def consulta_de_exemplo(medicoes: list[dict] | None = None) -> ConsultaDados:
    """
    ConsultaDados em memória: estação EST-1 (Rio de Janeiro/RJ) e o parâmetro TIP-PH.

    Args:
        medicoes: medições do exemplo. Padrão: pH 7.0, 7.2, 7.4 e 7.6 em 01/06/2026, de 0h a 3h.

    Returns:
        ConsultaDados sem banco, pronto para as ferramentas.

    Example:
        >>> consulta_de_exemplo().estacoes()
        [{'codigo': 'EST-1', 'nome': 'Estação 1', 'municipio': 'Rio de Janeiro', 'uf': 'RJ'}]
    """
    medicoes = medicoes if medicoes is not None else medicoes_de_exemplo([7.0, 7.2, 7.4, 7.6])
    return ConsultaDados(
        LeiturasEmMemoria(medicoes),
        CadastroEmMemoria([ESTACAO_EXEMPLO]),
        CadastroEmMemoria([{"id": 1, "nome": "Rio de Janeiro", "sigla": "RJ"}]),
        CadastroEmMemoria([PARAMETRO_EXEMPLO]),
    )
