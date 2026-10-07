"""
Único ponto de anonimização e criptografia de dados pessoais (LGPD).

- CPF e nome: anonimização irreversível com SHA-256 (HMAC-SHA256 quando há
  CHAVE_HASH configurada), sempre 64 caracteres hexadecimais.
- E-mail: criptografia reversível com Fernet (chave simétrica).

As chaves vêm do .env (CHAVE_CRIPTOGRAFIA e CHAVE_HASH) e são entregues por
configurar_seguranca(), chamada uma vez no início da aplicação. Regras em
docs/seguranca-lgpd.md.
"""

import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken

__cifra: Fernet | None = None
__chave_hash: bytes | None = None


def configurar_seguranca(chave_criptografia: str, chave_hash: str = "") -> None:
    """Registra as chaves usadas pelas funções deste módulo."""
    global __cifra, __chave_hash

    try:
        cifra = Fernet(chave_criptografia.encode("utf-8"))
    except (ValueError, TypeError, AttributeError) as error:
        # A mensagem nunca inclui a chave recebida.
        raise ValueError(
            "CHAVE_CRIPTOGRAFIA inválida: deve ser uma chave Fernet "
            "(Base64 de 32 bytes, gerada com Fernet.generate_key())."
        ) from error

    __cifra = cifra
    __chave_hash = (chave_hash or "").encode("utf-8")


def __configuracao() -> tuple[Fernet, bytes]:
    if __cifra is None or __chave_hash is None:
        raise RuntimeError(
            "Segurança não configurada: chame configurar_seguranca() no início da aplicação."
        )
    return __cifra, __chave_hash


def __gerar_hash(valor: str) -> str:
    _, chave_hash = __configuracao()
    dados = valor.encode("utf-8")
    if chave_hash:
        return hmac.new(chave_hash, dados, hashlib.sha256).hexdigest()
    return hashlib.sha256(dados).hexdigest()


def anonimizar_cpf(cpf: str | None) -> str | None:
    """Hash irreversível do CPF; pontuação é ignorada (873.604.219-69 == 87360421969)."""
    if cpf is None:
        return None
    digitos = re.sub(r"\D", "", str(cpf))
    if not digitos:
        return None
    return __gerar_hash(digitos)


def anonimizar_nome(nome: str | None) -> str | None:
    """Hash irreversível do nome; espaços extras e maiúsculas não alteram o resultado."""
    if nome is None:
        return None
    normalizado = " ".join(str(nome).split()).casefold()
    if not normalizado:
        return None
    return __gerar_hash(normalizado)


def criptografar_email(email: str | None) -> str | None:
    """Criptografia reversível do e-mail; o token muda a cada chamada."""
    if email is None or not str(email).strip():
        return None
    cifra, _ = __configuracao()
    return cifra.encrypt(str(email).strip().encode("utf-8")).decode("utf-8")


def descriptografar_email(token: str | None) -> str | None:
    """Recupera o e-mail original. Uso restrito a consultas autorizadas."""
    if token is None or not str(token).strip():
        return None
    cifra, _ = __configuracao()
    try:
        return cifra.decrypt(str(token).encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise ValueError(
            "Não foi possível descriptografar o e-mail: token inválido ou chave diferente."
        ) from error
