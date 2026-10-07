import logging
from typing import Any

from pydantic import ValidationError

from src.logger import logger, registrar_rejeicao
from src.models.parametro_model import ParametroModel
from src.repository.parametro_repository import ParametroRepository


class ParametroService:
    """
    Sincroniza os parâmetros encontrados no lote com a tabela Parametros.

    Parâmetro novo (código *_tipo_codigo ainda não cadastrado) é inserido sem
    faixa; não bloqueia a carga. Só fica de fora, com log ERROR, o parâmetro
    que não pode ser cadastrado ou usado com segurança (fase 7 do TODO).
    """

    def __init__(self, repository: ParametroRepository) -> None:
        self.__repository = repository

    def sincronizar(self, descobertos: dict[str, dict[str, Any]]) -> dict[str, ParametroModel]:
        """
        descobertos: saída de NormalizationService.descobrir_parametros().

        Devolve os parâmetros aceitos (codigo_parametro → ParametroModel, com id
        e faixa), já incluindo os recém-cadastrados. Os rejeitados não aparecem
        no retorno, e a validação descarta as medições deles.
        """
        cadastrados = {p.codigo_parametro: p for p in self.__repository.get_all()}
        nomes = {p.nome.casefold(): p.codigo_parametro for p in cadastrados.values()}
        rejeitados: set[str] = set()
        novos: list[ParametroModel] = []

        for codigo, info in sorted(descobertos.items()):
            campo = info["campo"]
            unidade = info.get("unidade_medida")

            existente = cadastrados.get(codigo)
            if existente is not None:
                # Unidade diferente da cadastrada mistura escalas (ex.: °F com °C):
                # as medições desse parâmetro ficam de fora até alguém corrigir.
                if unidade is not None and unidade.casefold() != existente.unidade_medida.casefold():
                    self.__rejeitar(
                        campo, codigo,
                        f"unidade {unidade} diferente da cadastrada ({existente.unidade_medida})",
                    )
                    rejeitados.add(codigo)
                continue

            if unidade is None:
                self.__rejeitar(campo, codigo, "unidade de medida ausente")
                rejeitados.add(codigo)
                continue

            nome = self.nome_legivel(campo)
            if nome.casefold() in nomes:
                self.__rejeitar(
                    campo, codigo,
                    f"nome {nome} já cadastrado para o código {nomes[nome.casefold()]}",
                )
                rejeitados.add(codigo)
                continue

            try:
                novos.append(
                    ParametroModel(codigo_parametro=codigo, nome=nome, unidade_medida=unidade)
                )
            except ValidationError:
                self.__rejeitar(campo, codigo, "código, nome ou unidade acima do tamanho permitido")
                rejeitados.add(codigo)
                continue
            nomes[nome.casefold()] = codigo

        if novos:
            self.__repository.create_many(novos)
            for parametro in novos:
                logger.info(
                    f"Novo parâmetro cadastrado: {parametro.codigo_parametro} "
                    f"({parametro.nome}, {parametro.unidade_medida}), sem faixa de valores."
                )

        atualizados = self.__repository.get_all() if novos else list(cadastrados.values())
        return {
            p.codigo_parametro: p for p in atualizados if p.codigo_parametro not in rejeitados
        }

    @staticmethod
    def nome_legivel(campo: str) -> str:
        """Nome inicial de um parâmetro novo a partir do campo (ex.: salinidade_total → Salinidade total)."""
        return campo.replace("_", " ").strip().capitalize()

    @staticmethod
    def faixas(parametros: dict[str, ParametroModel]) -> dict[str, tuple[float | None, float | None]]:
        """Faixas no formato esperado pelo ValidationService."""
        return {
            codigo: (parametro.valor_minimo, parametro.valor_maximo)
            for codigo, parametro in parametros.items()
        }

    @staticmethod
    def __rejeitar(campo: str, codigo: str, motivo: str) -> None:
        registrar_rejeicao(
            "parametro", "parametro", campo, motivo, valor=codigo, severidade=logging.ERROR,
        )
