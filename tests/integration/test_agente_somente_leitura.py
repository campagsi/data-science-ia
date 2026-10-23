"""
Ferramentas do agente contra o SQL Server de teste, com o usuário só de leitura.

- POL-01: com sql/seguranca/agente_usuario_leitura.sql aplicado, o usuário
  agente_leitura lê as tabelas das ferramentas e não consegue gravar.
- POL-02: o usuário não lê Operadores.
- As ferramentas, executadas COMO o usuário do agente, devolvem os mesmos
  números de sql/queries_analiticas.sql.

O usuário é criado sem login (WITHOUT LOGIN) e usado com EXECUTE AS USER, que
vale para a sessão inteira de uma conexão. Assim o teste não precisa de senha.
"""
import pytest

from src.agente.contratos import ChamadaFerramenta
from src.agente.ferramentas.catalogo import criar_registro
from src.agente.ferramentas.consulta_dados import ConsultaDados

from conftest import RAIZ, _lotes

SCRIPT = RAIZ / "sql" / "seguranca" / "agente_usuario_leitura.sql"
# A mensagem vem no idioma da instância ("permission was denied", "permissão ... negada") e, no
# ALTER, como "não existe ou você não tem permissões" (o SQL Server não revela se o objeto existe).
PERMISSAO_NEGADA = r"(?i)denied|negad|permiss"


class ConexaoComoAgente:
    """Uma conexão cuja sessão roda como agente_leitura, com a mesma interface de leitura do DatabaseConnection."""

    def __init__(self, connection_string: str) -> None:
        """Abre a conexão e troca o contexto da sessão para o usuário do agente."""
        from mssql_python import connect

        self.conexao = connect(connection_string, autocommit=True)
        self.executar("EXECUTE AS USER = 'agente_leitura'")

    def executar(self, sql: str, params: tuple = ()) -> None:
        """Executa um comando sem devolver linhas."""
        with self.conexao.cursor() as cursor:
            cursor.execute(sql, params)

    def fetch_all(self, sql: str, params=None) -> list:
        """SELECT com todas as linhas."""
        with self.conexao.cursor() as cursor:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())

    def fetch_one(self, sql: str, params: tuple = ()):
        """SELECT com uma linha."""
        with self.conexao.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def fechar(self) -> None:
        """Volta ao usuário original e fecha a conexão."""
        self.executar("REVERT")
        self.conexao.close()


@pytest.fixture(scope="module")
def como_agente(banco_carregado, connection_string):
    """Banco com o dataset, o usuário agente_leitura e as permissões do script aplicadas."""
    banco_carregado.execute(
        "IF DATABASE_PRINCIPAL_ID('agente_leitura') IS NULL CREATE USER agente_leitura WITHOUT LOGIN"
    )
    for _ in range(2):  # duas vezes: o script é idempotente
        for lote in _lotes(SCRIPT):
            banco_carregado.execute(lote)
    conexao = ConexaoComoAgente(connection_string)
    yield conexao
    conexao.fechar()


def test_script_exige_o_usuario_criado_antes(banco_carregado):
    banco_carregado.execute(
        "IF DATABASE_PRINCIPAL_ID('agente_leitura') IS NOT NULL DROP USER agente_leitura"
    )

    with pytest.raises(RuntimeError, match="agente_leitura não existe"):
        banco_carregado.execute(_lotes(SCRIPT)[0])


@pytest.mark.parametrize("tabela", ["Estados", "Municipios", "Estacoes", "Parametros", "Leituras", "Leitura_Itens"])
def test_pol01_le_as_tabelas_das_ferramentas(como_agente, tabela):
    assert como_agente.fetch_one(f"SELECT COUNT(*) FROM dbo.{tabela}")[0] > 0


@pytest.mark.parametrize(
    "comando",
    [
        "INSERT INTO dbo.Estados (nome, sigla) VALUES ('Teste', 'TT')",
        "UPDATE dbo.Parametros SET nome = 'x'",
        "DELETE FROM dbo.Leitura_Itens",
        "ALTER TABLE dbo.Estacoes ADD coluna_nova INT NULL",
    ],
)
def test_pol01_nao_grava_nem_altera_estrutura(como_agente, comando):
    with pytest.raises(Exception, match=PERMISSAO_NEGADA):
        como_agente.executar(comando)


@pytest.mark.parametrize("consulta", ["SELECT TOP 1 * FROM dbo.Operadores", "SELECT COUNT(*) FROM dbo.Operadores"])
def test_pol02_nao_le_operadores(como_agente, consulta):
    with pytest.raises(Exception, match=PERMISSAO_NEGADA):
        como_agente.fetch_all(consulta)


def test_ferramentas_como_agente_batem_com_as_consultas_analiticas(como_agente, banco_carregado, consultas_analiticas):
    registro = criar_registro(ConsultaDados.do_banco(como_agente))
    sql = {linha[2]: linha for linha in banco_carregado.fetch_all(consultas_analiticas[0])}

    resultado = registro.executar(ChamadaFerramenta("c1", "resumo_estatistico", {}))

    assert resultado.sucesso, resultado.erro
    linhas = {linha["codigo"]: linha for linha in resultado.dados["linhas"]}
    assert set(linhas) == set(sql)
    for codigo, (_, _, _, _, unidade, quantidade, media, desvio, _, minimo, maximo) in sql.items():
        linha = linhas[codigo]
        assert (linha["unidade"], linha["quantidade"]) == (unidade, quantidade)
        assert linha["media"] == pytest.approx(media, abs=1e-3)
        assert linha["desvio_padrao"] == pytest.approx(desvio, abs=1e-3)
        assert (linha["minimo"], linha["maximo"]) == pytest.approx((minimo, maximo), abs=1e-3)


def test_panorama_como_agente_usa_a_cobertura_agregada(como_agente):
    registro = criar_registro(ConsultaDados.do_banco(como_agente))

    estacao = registro.executar(ChamadaFerramenta("c1", "panorama_dados", {})).dados["estacoes"][0]

    assert estacao["leituras"] > 0
    assert estacao["intervalo_medio_minutos"] == 30


def test_referencias_do_golden_set_executam_como_agente(como_agente):
    """
    Fase 8: cada número esperado do golden set é calculável nos dados reais.

    Pega, antes de gastar tokens, um caso com estação, parâmetro ou período que
    não existe no dataset (a referência viraria "indisponível" no relatório).
    """
    import math

    from src.agente.avaliacao.execucao import Referencias
    from src.agente.avaliacao.golden import carregar_golden

    referencias = Referencias(criar_registro(ConsultaDados.do_banco(como_agente)))
    valores = {
        (caso.id, numero.origem): referencias.valor(numero, caso.argumentos_esperados[numero.ferramenta])
        for caso in carregar_golden()
        for numero in caso.numeros_esperados
    }

    assert len(valores) >= 20
    assert [chave for chave, valor in valores.items() if valor is None or not math.isfinite(valor)] == []


def test_dias_semelhantes_nos_dados_reais_como_agente(como_agente, tmp_path):
    """Fase 9: os dias do golden set têm resumo, e a ferramenta responde com o índice montado nos dados reais."""
    from datetime import date

    from src.agente.avaliacao.golden import carregar_golden
    from src.agente.dias.indice import abrir_busca_de_dias, indexar_dias
    from src.agente.ferramentas.consulta_dados import FiltroMedicoes
    from src.agente.rag.embeddings import EmbedderSimulado

    consulta = ConsultaDados.do_banco(como_agente)
    resumo = indexar_dias(consulta.medicoes(FiltroMedicoes()), EmbedderSimulado(), tmp_path)
    registro = criar_registro(consulta, dias=abrir_busca_de_dias(EmbedderSimulado(), tmp_path))

    assert resumo.chunks >= 100  # um resumo por estação e dia
    for caso in carregar_golden(categoria="similaridade"):
        argumentos = caso.argumentos_esperados["dias_semelhantes"]
        resultado = registro.executar(ChamadaFerramenta("c1", "dias_semelhantes", argumentos))
        assert resultado.sucesso, (caso.id, resultado.erro)
        assert len(resultado.dados["dias"]) == 5 and argumentos["data"] not in {d["data"] for d in resultado.dados["dias"]}
        assert date.fromisoformat(resultado.dados["data_referencia"]) == date.fromisoformat(argumentos["data"])


def test_previsao_treina_nos_dados_reais_e_prever_responde_como_agente(como_agente, tmp_path):
    """Fase 10: treino com validação temporal nos dados do projeto, modelo conferido e a ferramenta respondendo."""
    from src.agente.ferramentas.consulta_dados import FiltroMedicoes
    from src.previsao.dados import PARAMETROS_ALVO
    from src.previsao.persistencia import carregar_modelo, salvar_modelo
    from src.previsao.relatorio import montar_relatorio_treino
    from src.previsao.treino import treinar

    consulta = ConsultaDados.do_banco(como_agente)
    avaliacoes = treinar(consulta.medicoes(FiltroMedicoes(parametros=PARAMETROS_ALVO)))
    salvar_modelo(avaliacoes, tmp_path)
    (tmp_path / "relatorio_previsao.md").write_text(montar_relatorio_treino(avaliacoes), encoding="utf-8")
    registro = criar_registro(consulta, modelo_previsao=carregar_modelo(tmp_path))

    assert {a.parametro for a in avaliacoes} == set(PARAMETROS_ALVO)
    for avaliacao in avaliacoes:
        resultado = registro.executar(ChamadaFerramenta("c1", "prever", {"parametro": avaliacao.parametro, "estacao": avaliacao.estacao, "horizonte_horas": avaliacao.horas}))
        # Aprovado responde com a previsão; reprovado volta como erro de regra explicando o baseline.
        assert resultado.sucesso == avaliacao.aprovado, (avaliacao.chave, resultado.erro)
        if not avaliacao.aprovado:
            assert "não supera o baseline" in resultado.erro
