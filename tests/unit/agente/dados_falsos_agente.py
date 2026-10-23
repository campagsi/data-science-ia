"""
Dados falsos para testar as ferramentas do agente sem banco.

Uma estação (EST-1, Rio de Janeiro/RJ) com leituras a cada 30 minutos por 3 dias
(01 a 03/06/2026), com valores calculáveis à mão:

- TIP-PH: 7.0 nas horas pares e 7.2 nas ímpares, com um pico de 9.9 às 06:00 de 02/06;
- TIP-TMP: 20 + hora até o meio-dia e 20 + (24 - hora) depois (pico às 12h, mínimo às 0h);
- TIP-CHU: 0 mm sempre (parâmetro sem faixa máxima).
"""
from datetime import date, datetime, timedelta

from src.agente.ferramentas.consulta_dados import ConsultaDados
from src.models.estacao_model import EstacaoModel
from src.models.parametro_model import ParametroModel

INICIO = datetime(2026, 6, 1)
LEITURAS_POR_ESTACAO = 144  # 3 dias × 48 leituras
PICO_PH = datetime(2026, 6, 2, 6, 0)

PARAMETROS = [
    ParametroModel(id_parametro=1, codigo_parametro="TIP-CHU", nome="Precipitação", unidade_medida="mm", valor_minimo=0, valor_maximo=None),
    ParametroModel(id_parametro=2, codigo_parametro="TIP-PH", nome="pH", unidade_medida="pH", valor_minimo=0, valor_maximo=14),
    ParametroModel(id_parametro=3, codigo_parametro="TIP-TMP", nome="Temperatura do ar", unidade_medida="°C", valor_minimo=-10, valor_maximo=50),
]


def valor_ph(instante: datetime) -> float:
    """pH da leitura: 7.0 nas horas pares, 7.2 nas ímpares, 9.9 no pico."""
    if instante == PICO_PH:
        return 9.9
    return 7.0 if instante.hour % 2 == 0 else 7.2


def valor_temperatura(instante: datetime) -> float:
    """Temperatura com ciclo diário: sobe até 32 °C ao meio-dia e desce até 20 °C à meia-noite."""
    hora = instante.hour
    return 20.0 + (hora if hora <= 12 else 24 - hora)


def gerar_medicoes(estacoes: list[EstacaoModel]) -> list[dict]:
    """Medições no formato de get_medicoes() para cada estação, ordenadas como o repositório real."""
    linhas = []
    for estacao in estacoes:
        for indice in range(LEITURAS_POR_ESTACAO):
            instante = INICIO + timedelta(minutes=30 * indice)
            registro = f"REG-{estacao.codigo_estacao}-{indice:05d}"
            for parametro, valor in (("TIP-CHU", 0.0), ("TIP-PH", valor_ph(instante)), ("TIP-TMP", valor_temperatura(instante))):
                modelo = next(p for p in PARAMETROS if p.codigo_parametro == parametro)
                linhas.append(
                    {
                        "estacao_id": estacao.id_estacao,
                        "estacao_codigo": estacao.codigo_estacao,
                        "estacao": estacao.nome,
                        "codigo_registro": registro,
                        "data_hora": instante,
                        "codigo_parametro": parametro,
                        "parametro": modelo.nome,
                        "unidade_medida": modelo.unidade_medida,
                        "valor": valor,
                    }
                )
    return sorted(linhas, key=lambda m: (m["estacao_codigo"], m["codigo_parametro"], m["data_hora"]))


class LeiturasFalsas:
    """Imita LeituraRepository: mesmos filtros do get_medicoes() e contagem de chamadas."""

    def __init__(self, medicoes: list[dict]) -> None:
        """Guarda as medições e zera o contador de consultas."""
        self.medicoes = medicoes
        self.chamadas = 0

    def get_medicoes(self, estacao_id=None, municipio_id=None, data_inicio=None, data_fim=None, codigos_parametro=None):
        """Filtra como o SQL real: só data_inicio = aquele dia; as duas datas = intervalo fechado."""
        self.chamadas += 1

        def no_recorte(m: dict) -> bool:
            """Aplica os filtros a uma medição."""
            dia = m["data_hora"].date()
            if estacao_id is not None and m["estacao_id"] != estacao_id:
                return False
            if data_inicio is not None and data_fim is None and dia != data_inicio:
                return False
            if data_inicio is not None and data_fim is not None and not data_inicio <= dia <= data_fim:
                return False
            return not codigos_parametro or m["codigo_parametro"] in codigos_parametro

        return [m for m in self.medicoes if no_recorte(m)]

    def get_cobertura(self):
        """MIN, MAX e COUNT de leituras por estação, como o SQL do repositório."""
        por_estacao: dict[str, list[datetime]] = {}
        for m in self.medicoes:
            por_estacao.setdefault(m["estacao_codigo"], set()).add((m["codigo_registro"], m["data_hora"]))
        return [
            {
                "estacao_codigo": codigo,
                "primeira_leitura": min(instante for _, instante in leituras),
                "ultima_leitura": max(instante for _, instante in leituras),
                "leituras": len(leituras),
            }
            for codigo, leituras in sorted(por_estacao.items())
        ]


class CadastroFalso:
    """Imita os repositórios de estações, municípios e parâmetros (só os métodos de leitura)."""

    def __init__(self, itens: list) -> None:
        """Guarda os itens devolvidos por get_all()."""
        self.itens = itens

    def get_all(self):
        """Todos os itens cadastrados."""
        return list(self.itens)

    def get_com_estacoes(self):
        """Municípios com estação, no formato do MunicipioRepository."""
        return list(self.itens)


def montar_consulta(n_estacoes: int = 1, relogio=None) -> tuple[ConsultaDados, LeiturasFalsas]:
    """ConsultaDados com dados falsos; devolve também as leituras falsas, para contar as chamadas."""
    estacoes = [
        EstacaoModel(id_estacao=i, codigo_estacao=f"EST-{i}", nome=f"Estação {i}", municipio_id=10, latitude=-22.9, longitude=-43.2)
        for i in range(1, n_estacoes + 1)
    ]
    leituras = LeiturasFalsas(gerar_medicoes(estacoes))
    extras = {"relogio": relogio} if relogio else {}
    consulta = ConsultaDados(
        leituras,
        CadastroFalso(estacoes),
        CadastroFalso([{"id": 10, "nome": "Rio de Janeiro", "sigla": "RJ"}]),
        CadastroFalso(PARAMETROS),
        **extras,
    )
    return consulta, leituras
