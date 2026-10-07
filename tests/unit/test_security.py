import hashlib
import os

import pytest
from cryptography.fernet import Fernet

import src.security as security


@pytest.fixture(autouse=True)
def seguranca_configurada():
    security.configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], "chave-hash-de-teste")


def test_anonimizar_cpf_gera_hash_hexadecimal_de_64_caracteres():
    resultado = security.anonimizar_cpf("87360421969")

    assert len(resultado) == 64
    assert all(caractere in "0123456789abcdef" for caractere in resultado)
    assert "87360421969" not in resultado


def test_anonimizar_cpf_e_deterministico_e_ignora_pontuacao():
    assert security.anonimizar_cpf("873.604.219-69") == security.anonimizar_cpf(" 87360421969 ")


def test_anonimizar_nome_ignora_espacos_extras_e_maiusculas():
    assert security.anonimizar_nome("  João  Luiz da CUNHA ") == security.anonimizar_nome(
        "joão luiz da cunha"
    )


def test_cpfs_diferentes_geram_hashes_diferentes():
    assert security.anonimizar_cpf("87360421969") != security.anonimizar_cpf("87360421968")


def test_chave_hash_altera_o_hash():
    com_chave = security.anonimizar_cpf("87360421969")

    security.configurar_seguranca(os.environ["CHAVE_CRIPTOGRAFIA"], "")
    sem_chave = security.anonimizar_cpf("87360421969")

    assert sem_chave == hashlib.sha256(b"87360421969").hexdigest()
    assert com_chave != sem_chave


@pytest.mark.parametrize("funcao", ["anonimizar_cpf", "anonimizar_nome", "criptografar_email"])
@pytest.mark.parametrize("vazio", [None, "", "   "])
def test_valor_vazio_retorna_none(funcao, vazio):
    assert getattr(security, funcao)(vazio) is None


def test_cpf_sem_digitos_retorna_none():
    assert security.anonimizar_cpf("---") is None


def test_criptografia_do_email_e_reversivel():
    token = security.criptografar_email(" operador@example.invalid ")

    assert "operador@example.invalid" not in token
    assert security.descriptografar_email(token) == "operador@example.invalid"


def test_criptografia_do_email_gera_token_diferente_a_cada_chamada():
    assert security.criptografar_email("a@b.c") != security.criptografar_email("a@b.c")


def test_descriptografar_com_outra_chave_falha_sem_expor_token():
    token = security.criptografar_email("operador@example.invalid")
    security.configurar_seguranca(Fernet.generate_key().decode(), "chave-hash-de-teste")

    with pytest.raises(ValueError) as erro:
        security.descriptografar_email(token)

    assert token not in str(erro.value)


def test_chave_invalida_e_rejeitada_sem_expor_o_valor():
    with pytest.raises(ValueError, match="CHAVE_CRIPTOGRAFIA") as erro:
        security.configurar_seguranca("chave-curta-secreta")

    assert "chave-curta-secreta" not in str(erro.value)


def test_funcoes_exigem_configuracao(monkeypatch):
    monkeypatch.setattr(security, "__cifra", None)
    monkeypatch.setattr(security, "__chave_hash", None)

    with pytest.raises(RuntimeError, match="configurar_seguranca"):
        security.anonimizar_cpf("87360421969")
