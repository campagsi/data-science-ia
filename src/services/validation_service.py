from typing import Any

Faixa = tuple[float | None, float | None]


class ValidationService:
    """
    Verifica os registros normalizados antes de qualquer gravação.

    Não grava nem loga: devolve um resultado por registro (contrato na seção 4
    de docs/analise-implementacao.md). O log de rejeitados é gerado a partir
    desses resultados por src.logger.registrar_resultados_validacao().
    """

    # Campos sem os quais a leitura não pode ser gravada (completude).
    CAMPOS_VITAIS = (
        "registro_codigo",
        "data_hora_ciclo",
        "cidade_estado",
        "municipio",
        "estacao_codigo",
        "estacao_nome",
        "estacao_latitude",
        "estacao_longitude",
        "operador_codigo",
        "cpf_hash",
        "nome_hash",
        "email_criptografado",
    )
    _FAIXAS_COORDENADAS: dict[str, Faixa] = {
        "estacao_latitude": (-90, 90),
        "estacao_longitude": (-180, 180),
    }

    def __init__(
        self,
        faixas: dict[str, Faixa] | None = None,
        siglas_estados: set[str] | None = None,
    ) -> None:
        """
        faixas: codigo_parametro → (valor_minimo, valor_maximo), lidas de Parametros;
            None em um dos limites = sem limite; parâmetro ausente = sem faixa.
        siglas_estados: siglas cadastradas em Estados; None = não confere.
        """
        self.__faixas = faixas or {}
        self.__siglas_estados = siglas_estados

    def validate_data(self, normalizados: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Devolve um resultado por registro, na mesma ordem, sem interromper o lote."""
        registros_vistos: set[str] = set()
        estacoes: dict[str, tuple] = {}
        operadores: dict[str, tuple] = {}

        resultados = []
        for registro in normalizados:
            campos_nulos = [campo for campo in self.CAMPOS_VITAIS if registro.get(campo) is None]
            motivos = []
            if campos_nulos:
                motivos.append(
                    self.__motivo("completude", ",".join(campos_nulos), "campo vital nulo")
                )

            motivos += self.__validar_cabecalho(registro)
            motivos += self.__validar_unicidade(registro, registros_vistos, estacoes, operadores)

            itens_validos, itens_invalidos = self.__validar_itens(registro.get("itens", []))
            if not itens_validos:
                motivos.append(
                    self.__motivo("completude", "itens", "leitura sem medições válidas")
                )

            resultados.append(
                {
                    "registro_codigo": registro.get("registro_codigo"),
                    "valido": not motivos,
                    "campos_nulos": campos_nulos,
                    "itens_invalidos": itens_invalidos,
                    "motivos": motivos,
                    "registro": dict(registro, itens=itens_validos),
                }
            )
        return resultados

    @staticmethod
    def registros_validos(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Registros que podem ser gravados nas entidades e na Silver."""
        return [resultado["registro"] for resultado in resultados if resultado["valido"]]

    def __validar_cabecalho(self, registro: dict[str, Any]) -> list[dict[str, Any]]:
        motivos = []

        for campo, (minimo, maximo) in self._FAIXAS_COORDENADAS.items():
            valor = registro.get(campo)
            if valor is not None and not minimo <= valor <= maximo:
                motivos.append(
                    self.__motivo("acuracia", campo, f"fora da faixa {minimo} a {maximo}", valor)
                )

        sigla = registro.get("cidade_estado")
        if sigla is not None:
            if len(sigla) != 2 or not sigla.isalpha():
                motivos.append(
                    self.__motivo("validade", "cidade_estado", "sigla deve ter duas letras", sigla)
                )
            elif self.__siglas_estados is not None and sigla not in self.__siglas_estados:
                motivos.append(
                    self.__motivo("referencia", "cidade_estado", "estado não cadastrado em Estados", sigla)
                )
        return motivos

    def __validar_unicidade(
        self,
        registro: dict[str, Any],
        registros_vistos: set[str],
        estacoes: dict[str, tuple],
        operadores: dict[str, tuple],
    ) -> list[dict[str, Any]]:
        motivos = []

        codigo = registro.get("registro_codigo")
        if codigo is not None:
            if codigo in registros_vistos:
                # Retransmissão da API: mantém a primeira ocorrência.
                motivos.append(
                    self.__motivo("unicidade", "registro_codigo", "registro repetido no lote (retransmissão)")
                )
            registros_vistos.add(codigo)

        # O mesmo código não pode chegar com dados cadastrais diferentes no lote.
        # O e-mail criptografado fica de fora: o token muda a cada criptografia.
        conferencias = (
            ("estacao_codigo", estacoes, ("estacao_nome", "estacao_latitude", "estacao_longitude", "municipio")),
            ("operador_codigo", operadores, ("cpf_hash", "nome_hash", "municipio")),
        )
        for campo_codigo, vistos, campos_identidade in conferencias:
            codigo_cadastro = registro.get(campo_codigo)
            identidade = tuple(registro.get(campo) for campo in campos_identidade)
            if codigo_cadastro is None or None in identidade:
                continue
            if vistos.setdefault(codigo_cadastro, identidade) != identidade:
                motivos.append(
                    self.__motivo(
                        "unicidade", campo_codigo,
                        "código repetido no lote com dados cadastrais diferentes", codigo_cadastro,
                    )
                )
        return motivos

    def __validar_itens(self, itens: list[dict[str, Any]]) -> tuple[list, list]:
        validos, invalidos = [], []
        for item in itens:
            valor = item.get("valor")
            if valor is None:
                invalidos.append(self.__motivo("completude", item["campo"], "medição nula"))
                continue

            minimo, maximo = self.__faixas.get(item["codigo_parametro"], (None, None))
            if (minimo is not None and valor < minimo) or (maximo is not None and valor > maximo):
                invalidos.append(
                    self.__motivo(
                        "acuracia", item["campo"],
                        f"fora da faixa {self.__limite(minimo)} a {self.__limite(maximo)}", valor,
                    )
                )
                continue

            validos.append(item)
        return validos, invalidos

    @staticmethod
    def __limite(valor: float | None) -> str:
        if valor is None:
            return "sem limite"
        return f"{valor:g}"

    @staticmethod
    def __motivo(etapa: str, campo: str, motivo: str, valor: Any = None) -> dict[str, Any]:
        return {"etapa": etapa, "campo": campo, "motivo": motivo, "valor": valor}
