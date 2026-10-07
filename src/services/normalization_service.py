import math
from datetime import datetime
from typing import Any

from src.logger import logger, registrar_rejeicao
from src.security import anonimizar_cpf, anonimizar_nome, criptografar_email


class NormalizationService:
    """
    Normaliza o payload da API para o modelo 3FN.

    Cada registro vira um cabeçalho (estado, município, estação, operador,
    registro e data/hora) com uma lista de itens, um por parâmetro medido.
    Os dados pessoais do operador saem já anonimizados (docs/seguranca-lgpd.md).
    Nada derruba o lote: o que não pode ser convertido vai para o log de
    rejeitados e o restante segue.
    """

    _SUFIXO_PARAMETRO = "_tipo_codigo"
    _CAMPOS_TEXTO = (
        "registro_codigo",
        "cidade_estado",
        "cidade_nome",
        "municipio",
        "estacao_codigo",
        "estacao_nome",
        "operador_codigo",
    )
    _CAMPOS_COORDENADA = ("estacao_latitude", "estacao_longitude")
    _CAMPOS_PESSOAIS = ("operador_cpf", "operador_nome_completo", "operador_email")

    def normalize(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normaliza o lote, ordenado por data/hora do ciclo, sem alterar o payload recebido."""
        if not isinstance(raw_data, list):
            raise ValueError("Os dados brutos devem ser uma lista de registros.")

        normalizados = []
        descartados: set[str] = set()

        for index, record in enumerate(raw_data):
            if not isinstance(record, dict):
                registrar_rejeicao(
                    "normalizacao", "leitura", "registro",
                    f"registro {index} não é um objeto JSON",
                )
                continue

            normalizado = self.__normalizar_registro(record)
            if normalizado is not None:
                normalizados.append(normalizado)
            descartados |= set(record) - self.__campos_utilizados(record)

        if descartados:
            # Decisão D5: campos sem coluna no banco não são persistidos.
            logger.info(
                "Campos do payload sem coluna no banco (descartados): "
                + ", ".join(sorted(descartados))
            )

        normalizados.sort(
            key=lambda r: (r["data_hora_ciclo"] is None, r["data_hora_ciclo"] or datetime.min)
        )
        logger.info(
            f"Normalização: {len(normalizados)} de {len(raw_data)} registros normalizados."
        )
        return normalizados

    @staticmethod
    def descobrir_parametros(normalizados: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """
        Parâmetros presentes no lote: codigo_parametro → campo e unidade de medida.

        A unidade é a primeira encontrada no lote; None se nenhum registro a informa.
        """
        parametros: dict[str, dict[str, Any]] = {}
        for registro in normalizados:
            for item in registro["itens"]:
                atual = parametros.setdefault(
                    item["codigo_parametro"],
                    {"campo": item["campo"], "unidade_medida": None},
                )
                if atual["unidade_medida"] is None:
                    atual["unidade_medida"] = item["unidade_medida"]
        return parametros

    def __normalizar_registro(self, record: dict[str, Any]) -> dict[str, Any] | None:
        normalizado = {campo: self.__texto(record.get(campo)) for campo in self._CAMPOS_TEXTO}
        registro = normalizado["registro_codigo"]

        if normalizado["cidade_estado"] is not None:
            normalizado["cidade_estado"] = normalizado["cidade_estado"].upper()
        normalizado["municipio"] = normalizado["municipio"] or normalizado["cidade_nome"]
        del normalizado["cidade_nome"]

        for campo in self._CAMPOS_COORDENADA:
            valor = record.get(campo)
            try:
                normalizado[campo] = self.__numero(valor)
            except ValueError:
                registrar_rejeicao(
                    "normalizacao", "leitura", campo, "coordenada não numérica",
                    registro=registro, valor=valor,
                )
                return None

        valor_data = record.get("data_hora_ciclo")
        try:
            normalizado["data_hora_ciclo"] = self.__data_hora(valor_data)
        except ValueError:
            registrar_rejeicao(
                "normalizacao", "leitura", "data_hora_ciclo", "data/hora não está no formato ISO",
                registro=registro, valor=valor_data,
            )
            return None

        # Anonimização logo após a limpeza; os originais não são copiados
        # para o registro normalizado (minimização).
        normalizado["cpf_hash"] = anonimizar_cpf(record.get("operador_cpf"))
        normalizado["nome_hash"] = anonimizar_nome(record.get("operador_nome_completo"))
        normalizado["email_criptografado"] = criptografar_email(record.get("operador_email"))

        normalizado["itens"] = self.__normalizar_itens(record, registro)
        return normalizado

    def __normalizar_itens(self, record: dict[str, Any], registro: str | None) -> list[dict[str, Any]]:
        itens = []
        for chave in record:
            if not chave.endswith(self._SUFIXO_PARAMETRO):
                continue

            campo = chave.removesuffix(self._SUFIXO_PARAMETRO)
            codigo = self.__texto(record[chave])
            if codigo is None:
                registrar_rejeicao(
                    "normalizacao", "item", campo, "código do parâmetro ausente",
                    registro=registro,
                )
                continue

            valor = record.get(campo)
            try:
                valor = self.__numero(valor)
            except ValueError:
                registrar_rejeicao(
                    "normalizacao", "item", campo, "medição não numérica",
                    registro=registro, valor=valor,
                )
                continue

            try:
                data_hora_leitura = self.__data_hora(record.get(f"data_hora_leitura_{campo}"))
            except ValueError:
                data_hora_leitura = None  # informativa; não é persistida (D5)

            itens.append(
                {
                    "campo": campo,
                    "codigo_parametro": codigo,
                    "unidade_medida": self.__unidade(record, campo),
                    # None = medição nula; tratada na completude (fase 5).
                    "valor": valor,
                    "data_hora_leitura": data_hora_leitura,
                }
            )
        return itens

    def __unidade(self, record: dict[str, Any], campo: str) -> str | None:
        # O payload tem nomes fora do padrão, como oxigenio_dissolvido_medida e
        # velocidade_unidade_medida (para velocidade_vento).
        candidatos = (
            f"{campo}_unidade_medida",
            f"{campo}_medida",
            f"{campo.split('_')[0]}_unidade_medida",
        )
        for candidato in candidatos:
            unidade = self.__texto(record.get(candidato))
            if unidade is not None:
                return unidade
        return None

    def __campos_utilizados(self, record: dict[str, Any]) -> set[str]:
        usados = set(self._CAMPOS_TEXTO) | set(self._CAMPOS_COORDENADA) | set(self._CAMPOS_PESSOAIS)
        usados.add("data_hora_ciclo")
        for chave in record:
            if chave.endswith(self._SUFIXO_PARAMETRO):
                campo = chave.removesuffix(self._SUFIXO_PARAMETRO)
                usados |= {
                    chave,
                    campo,
                    f"{campo}_unidade_medida",
                    f"{campo}_medida",
                    f"{campo.split('_')[0]}_unidade_medida",
                }
        return usados

    @staticmethod
    def __texto(valor: Any) -> str | None:
        if valor is None:
            return None
        texto = str(valor).strip()
        return texto or None

    @staticmethod
    def __numero(valor: Any) -> float | None:
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return None
        if isinstance(valor, bool):
            raise ValueError("booleano não é medição")
        try:
            numero = float(valor)
        except (TypeError, ValueError) as error:
            raise ValueError("valor não numérico") from error
        if not math.isfinite(numero):
            raise ValueError("valor não finito")
        return numero

    @staticmethod
    def __data_hora(valor: Any) -> datetime | None:
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return None
        if isinstance(valor, datetime):
            return valor
        return datetime.fromisoformat(str(valor).strip())
