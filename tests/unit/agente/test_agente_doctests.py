"""
Executa os doctests (exemplos dos docstrings) de todos os módulos de src/agente.

Assim, `python -m pytest tests` já confere os exemplos, sem depender de
`--doctest-modules` (o projeto não tem pytest.ini). Também confere o padrão de
documentação de docs/agente/guia-estudos.md § 3: todo módulo tem docstring, e
os módulos de código (fora pacotes e exemplos) explicam o conceito.
"""
import ast
import doctest
import importlib
import pkgutil
from pathlib import Path

import pytest

import src.agente
import src.previsao

# src/previsao (Fase 10) segue o mesmo padrão de documentação (todo.md, regra de código da Fase 10).
PACOTES = (src.agente, src.previsao)
MODULOS = sorted(
    [pacote.__name__ for pacote in PACOTES]
    + [modulo.name for pacote in PACOTES for modulo in pkgutil.walk_packages(pacote.__path__, prefix=f"{pacote.__name__}.")]
)


@pytest.mark.parametrize("nome", MODULOS)
def test_doctests_do_modulo(nome):
    modulo = importlib.import_module(nome)

    resultado = doctest.testmod(modulo, optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE)

    assert resultado.failed == 0, f"{resultado.failed} doctest(s) falharam em {nome}"


@pytest.mark.parametrize("nome", MODULOS)
def test_modulo_segue_o_padrao_de_documentacao(nome):
    modulo = importlib.import_module(nome)
    pacote = hasattr(modulo, "__path__")
    exemplo = ".exemplos." in nome

    assert (modulo.__doc__ or "").strip(), f"{nome} sem docstring de módulo"
    if not pacote and not exemplo:
        assert "Conceito" in modulo.__doc__, f"{nome}: a docstring deve explicar o conceito"
    if exemplo:
        assert "Como rodar" in modulo.__doc__, f"{nome}: o exemplo deve dizer como rodar"


def _e_excecao(classe: ast.ClassDef) -> bool:
    """Classes de exceção dispensam Example: a docstring diz quando são lançadas."""
    return any(getattr(base, "id", "").endswith(("Error", "Exception")) for base in classe.bases)


def _sem_docstring(arquivo: Path) -> list[str]:
    """
    Classes, funções e métodos sem docstring (inclusive privados e internos), e
    funções e classes públicas de módulo sem Example (guia-estudos.md § 3.4).
    """
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    problemas = []
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not ast.get_docstring(no):
            problemas.append(f"{no.name} (linha {no.lineno}): sem docstring")
    if "exemplos" not in arquivo.parts:
        for no in arvore.body:
            publico = isinstance(no, (ast.FunctionDef, ast.ClassDef)) and not no.name.startswith("_")
            if publico and not (isinstance(no, ast.ClassDef) and _e_excecao(no)):
                if "Example" not in (ast.get_docstring(no) or ""):
                    problemas.append(f"{no.name} (linha {no.lineno}): público sem Example")
    return problemas


@pytest.mark.parametrize(
    "arquivo",
    sorted(arquivo for pacote in PACOTES for arquivo in Path(pacote.__file__).parent.rglob("*.py")),
    ids=lambda p: p.relative_to(Path(src.agente.__file__).parents[1]).as_posix(),
)
def test_toda_classe_funcao_e_metodo_tem_docstring(arquivo):
    assert _sem_docstring(arquivo) == []
