// Chat do agente analítico (src/ui/agente.py).
// Segurança (POL-09): o texto do usuário e as fontes entram com textContent (nunca como HTML);
// só a resposta entra como HTML, e ela já vem convertida no servidor sem HTML permitido.

(() => {
  // Tema salvo (o dashboard.js cuida do botão; aqui só aplica antes de desenhar a conversa).
  try {
    const tema = localStorage.getItem("da-tema");
    if (tema) document.documentElement.dataset.theme = tema;
  } catch (erro) { /* armazenamento indisponível */ }

  const formulario = document.querySelector("#agente-form");
  const campo = document.querySelector("#agente-pergunta");
  const conversa = document.querySelector("#agente-conversa");
  const estado = document.querySelector("#agente-estado");
  const botao = document.querySelector("#agente-enviar");
  const campoChave = document.querySelector("#agente-chave");
  let conversaId = null;

  function adicionar(classe, preencher) {
    document.querySelector("#agente-vazio")?.remove();
    const bloco = document.createElement("article");
    bloco.className = `agente-mensagem ${classe}`;
    preencher(bloco);
    conversa.append(bloco);
    bloco.scrollIntoView({ behavior: "smooth", block: "end" });
    return bloco;
  }

  function mostrarPergunta(texto) {
    adicionar("agente-usuario", (bloco) => { bloco.textContent = texto; });
  }

  function mostrarResposta(dados) {
    adicionar("agente-resposta", (bloco) => {
      const texto = document.createElement("div");
      texto.innerHTML = dados.resposta_html; // HTML gerado no servidor com html=False (sem script)
      bloco.append(texto);
      if (dados.fontes.length) {
        const titulo = document.createElement("p");
        titulo.className = "eyebrow";
        titulo.textContent = "Fontes";
        const lista = document.createElement("ul");
        lista.className = "agente-fontes";
        for (const fonte of dados.fontes) {
          const item = document.createElement("li");
          item.textContent = fonte.descricao;
          lista.append(item);
        }
        bloco.append(titulo, lista);
      }
      const uso = document.createElement("p");
      uso.className = "muted agente-uso";
      uso.textContent = `tokens: ${dados.uso.tokens_entrada} de entrada, ${dados.uso.tokens_saida} de saída · ${(dados.latencia_ms / 1000).toFixed(1)} s`;
      bloco.append(uso);
    });
  }

  function mostrarErro(texto) {
    adicionar("agente-erro", (bloco) => { bloco.textContent = texto; });
  }

  formulario.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const pergunta = campo.value.trim();
    if (!pergunta) return;
    mostrarPergunta(pergunta);
    campo.value = "";
    botao.disabled = true;
    estado.textContent = "Pensando…";
    const cabecalhos = { "Content-Type": "application/json" };
    if (campoChave?.value) cabecalhos["X-API-Key"] = campoChave.value;
    try {
      const resposta = await fetch("/agente/perguntar", {
        method: "POST",
        headers: cabecalhos,
        body: JSON.stringify({ pergunta, conversa_id: conversaId }),
      });
      const dados = await resposta.json().catch(() => ({ erro: "Resposta inválida do servidor." }));
      if (dados.conversa_id) conversaId = dados.conversa_id;
      if (resposta.ok) mostrarResposta(dados);
      else mostrarErro(dados.erro || `Erro ${resposta.status}.`);
    } catch (erro) {
      mostrarErro("Não foi possível falar com o servidor.");
    } finally {
      botao.disabled = false;
      estado.textContent = "";
      campo.focus();
    }
  });

  document.querySelector("#agente-nova")?.addEventListener("click", () => {
    conversaId = null;
    conversa.replaceChildren();
    campo.focus();
  });
})();
