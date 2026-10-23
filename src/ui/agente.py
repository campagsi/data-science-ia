"""
Interface web do agente analítico: GET /agente (página) e POST /agente/perguntar (JSON).

Conceito
--------
A página é uma camada fina sobre Agente.perguntar(). Toda regra de negócio e
de segurança do agente continua no agente. Aqui ficam só as proteções próprias
da web (políticas de docs/agente/guardrails-e-owasp.md § 9):

- POL-07 (consumo): limite de perguntas por IP com o Flask-Limiter
  (AGENTE_LIMITE_WEB, padrão "10 per minute;200 per day"). Cada pergunta custa
  tokens, e um script não pode disparar milhares;
- POL-09 (saída segura, risco LLM05): o Markdown da resposta é convertido em
  HTML no servidor com o markdown-it-py e o HTML desabilitado. Um "<script>"
  escrito pelo LLM vira texto, e links "javascript:" não viram link. A página
  envia Content-Security-Policy, que proíbe scripts que não venham do próprio
  site, inclusive os embutidos no HTML;
- POL-10 (segredos): nenhuma chave vai para o navegador. Quem chama o LLM é o
  servidor. Se a página sair do 127.0.0.1, AGENTE_CHAVE_WEB passa a exigir o
  header X-API-Key, como a API do BI.

O agente é montado só na primeira pergunta (criar_agente lê o .env). Sem
configuração, a página abre e a pergunta responde 503 com uma mensagem amigável.
O log usa a configuração já feita pelo servidor, sem chamar configurar_logs() de novo (ponto P6).

Documentação: docs/agente/arquitetura.md § 11
"""
from __future__ import annotations

import hmac
import os
import threading
from collections.abc import Callable
from typing import Any

from flask import Blueprint, Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from markdown_it import MarkdownIt

from src.logger import logger

LIMITE_PADRAO = "10 per minute;200 per day"
MENSAGEM_INDISPONIVEL = "O agente não está disponível agora. Tente de novo em alguns instantes."
# POL-09: só recursos do próprio site; nada de script embutido, objeto ou moldura.
POLITICA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)

# Conceito: "commonmark" + html=False escapa qualquer HTML escrito pelo LLM; tabelas habilitadas.
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def markdown_seguro(texto: str) -> str:
    """
    Markdown da resposta convertido em HTML sem deixar passar HTML nem links javascript:.

    Example:
        >>> markdown_seguro("**7,3** <script>alert(1)</script>")
        '<p><strong>7,3</strong> &lt;script&gt;alert(1)&lt;/script&gt;</p>\\n'
    """
    return _MARKDOWN.render(texto)


def registrar_agente(app: Flask, fabrica: Callable[[], Any] | None = None) -> None:
    """
    Registra as rotas do agente e o limite de requisições na aplicação.

    Args:
        app: aplicação Flask (create_app).
        fabrica: monta o Agente. None = src.agente.criar_agente (lê o .env).
            Os testes passam um agente com o LLM roteirizado.
    """
    limite = os.getenv("AGENTE_LIMITE_WEB", "").strip() or LIMITE_PADRAO
    limiter = Limiter(get_remote_address, app=app, storage_uri="memory://", default_limits=[])
    obter_agente = _agente_preguicoso(fabrica)
    rotas = Blueprint("agente", __name__)

    @rotas.get("/agente")
    def pagina_agente() -> Response:
        """Página do chat, com a política de segurança de conteúdo (POL-09)."""
        resposta = Response(render_template("agente.html", chave_exigida=bool(_chave_web())))
        return _cabecalhos_seguros(resposta)

    @rotas.post("/agente/perguntar")
    @limiter.limit(limite)
    def perguntar() -> tuple[Response, int] | Response:
        """Recebe {"pergunta", "conversa_id"} e devolve a resposta, as fontes e o consumo."""
        if not _chave_valida():
            return jsonify({"erro": "chave de acesso ausente ou inválida (header X-API-Key)"}), 401
        corpo = request.get_json(silent=True)
        if not isinstance(corpo, dict) or not isinstance(corpo.get("pergunta"), str):
            return jsonify({"erro": 'envie um JSON com o campo "pergunta"'}), 400
        conversa_id = corpo.get("conversa_id")
        if conversa_id is not None and not isinstance(conversa_id, str):
            return jsonify({"erro": "conversa_id inválido"}), 400

        agente = obter_agente()
        if agente is None:
            return jsonify({"erro": MENSAGEM_INDISPONIVEL}), 503
        # Por quê: import aqui para a página abrir mesmo sem o pacote do agente configurado.
        from src.agente.guardrails.entrada import PerguntaInvalida

        try:
            resposta = agente.perguntar(corpo["pergunta"], conversa_id)
        except (PerguntaInvalida, ValueError) as erro:
            return jsonify({"erro": str(erro)}), 400
        if resposta.falhou:
            return jsonify({"erro": resposta.texto, "conversa_id": resposta.conversa_id}), 503
        return jsonify(
            {
                "conversa_id": resposta.conversa_id,
                "resposta": resposta.texto,
                "resposta_html": markdown_seguro(resposta.texto),
                "fontes": [{"tipo": f.tipo, "descricao": f.descricao} for f in resposta.fontes],
                "uso": {"tokens_entrada": resposta.tokens_entrada, "tokens_saida": resposta.tokens_saida},
                "latencia_ms": resposta.latencia_ms,
            }
        )

    @rotas.errorhandler(429)
    def limite_excedido(_erro) -> tuple[Response, int]:
        """POL-07: resposta JSON quando o limite de perguntas por IP é atingido."""
        logger.warning(f"Agente: guardrail=POL-07 acao=limite_web ip={get_remote_address()}")
        return jsonify({"erro": f"limite de perguntas atingido ({limite}); aguarde e tente de novo"}), 429

    app.register_blueprint(rotas)


def _agente_preguicoso(fabrica: Callable[[], Any] | None) -> Callable[[], Any]:
    """Monta o agente na primeira chamada e reaproveita depois; None se a configuração falhar."""
    estado: dict[str, Any] = {}
    lock = threading.Lock()

    def obter():
        """Devolve o agente, criando-o uma vez só (com lock, porque o Flask atende em paralelo)."""
        with lock:
            if "agente" not in estado:
                try:
                    if fabrica is None:
                        from src.agente import criar_agente

                        estado["agente"] = criar_agente()
                    else:
                        estado["agente"] = fabrica()
                except Exception as erro:
                    # Cuidado (POL-10): só o tipo do erro, nunca a mensagem, que pode citar variáveis.
                    logger.error(f"Agente: não foi possível montar o agente da web erro={type(erro).__name__}")
                    return None
            return estado["agente"]

    return obter


def _chave_web() -> str:
    """Chave exigida no header X-API-Key, ou vazio (uso local, rota aberta)."""
    return os.getenv("AGENTE_CHAVE_WEB", "").strip()


def _chave_valida() -> bool:
    """Sem AGENTE_CHAVE_WEB, aceita; com ela, compara em tempo constante (evita ataque de tempo)."""
    esperada = _chave_web()
    return not esperada or hmac.compare_digest(request.headers.get("X-API-Key", ""), esperada)


def _cabecalhos_seguros(resposta: Response) -> Response:
    """CSP e cabeçalhos que impedem o navegador de reinterpretar o conteúdo ou embutir a página."""
    resposta.headers["Content-Security-Policy"] = POLITICA_CSP
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta
