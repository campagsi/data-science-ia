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

  // --- Base do agente (GET /agente/base e POST /agente/base/atualizar) ---
  // Cada botão só habilita com o artefato ausente ou desatualizado; o servidor confere de novo.
  const listaBase = document.querySelector("#base-lista");
  const botaoTudo = document.querySelector("#base-tudo");
  const andamento = document.querySelector("#base-andamento");
  const PENDENTES = ["ausente", "desatualizado"];
  const ROTULOS = { atualizado: "Em dia", desatualizado: "Desatualizado", ausente: "Ausente", indisponivel: "Indisponível" };
  let acompanhando = null;

  function cabecalhosBase() {
    const cabecalhos = { "Content-Type": "application/json" };
    if (campoChave?.value) cabecalhos["X-API-Key"] = campoChave.value;
    return cabecalhos;
  }

  function dataCurta(iso) {
    if (!iso) return "nunca atualizado por aqui";
    const data = new Date(iso);
    return Number.isNaN(data.getTime()) ? iso : `atualizado em ${data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}`;
  }

  function mostrarAndamento(texto, erro = false) {
    andamento.textContent = texto;
    andamento.classList.toggle("error", erro);
  }

  function desenharBase(dados) {
    const executando = dados.tarefa.executando;
    listaBase.replaceChildren();
    for (const [chave, item] of Object.entries(dados.itens)) {
      const linha = document.createElement("li");
      linha.className = "base-item";
      const topo = document.createElement("div");
      topo.className = "base-topo";
      const nome = document.createElement("strong");
      nome.textContent = item.nome;
      const selo = document.createElement("span");
      selo.className = `base-selo base-${item.situacao}`;
      selo.textContent = executando && dados.tarefa.etapa === chave ? "Atualizando…" : ROTULOS[item.situacao] || item.situacao;
      topo.append(nome, selo);
      const detalhe = document.createElement("p");
      detalhe.className = "base-detalhe";
      detalhe.textContent = item.motivo || dataCurta(item.atualizado_em);
      const botaoItem = document.createElement("button");
      botaoItem.type = "button";
      botaoItem.className = "text-button base-acao";
      botaoItem.textContent = chave === "previsao" ? "Treinar" : "Atualizar";
      botaoItem.disabled = executando || !PENDENTES.includes(item.situacao);
      botaoItem.addEventListener("click", () => atualizar([chave]));
      linha.append(topo, detalhe, botaoItem);
      listaBase.append(linha);
    }
    botaoTudo.disabled = executando || !Object.values(dados.itens).some((item) => PENDENTES.includes(item.situacao));
    if (executando) {
      mostrarAndamento(`Atualizando ${dados.tarefa.etapa_nome || "a base"}… (o treino da previsão leva cerca de 1 minuto)`);
    }
  }

  function resultadoDaTarefa(tarefa) {
    const nomes = (lista) => lista.map((chave) => ({ documentacao: "documentação", dias: "dias semelhantes", previsao: "previsão" }[chave] || chave)).join(", ");
    if (tarefa.falhas.length) {
      mostrarAndamento(`Falhou: ${nomes(tarefa.falhas)}. Consulte os logs.${tarefa.concluidos.length ? ` Concluído: ${nomes(tarefa.concluidos)}.` : ""}`, true);
    } else {
      mostrarAndamento(`Base atualizada (${nomes(tarefa.concluidos)}). A próxima pergunta já usa a versão nova.`);
    }
  }

  async function carregarBase() {
    try {
      const resposta = await fetch("/agente/base", { headers: cabecalhosBase() });
      const dados = await resposta.json().catch(() => ({ erro: "Resposta inválida do servidor." }));
      if (!resposta.ok) {
        listaBase.replaceChildren();
        botaoTudo.disabled = true;
        mostrarAndamento(resposta.status === 401 ? "Informe a chave de acesso para ver a base." : dados.erro || `Erro ${resposta.status}.`, true);
        return null;
      }
      desenharBase(dados);
      return dados;
    } catch (erro) {
      mostrarAndamento("Não foi possível falar com o servidor.", true);
      return null;
    }
  }

  function acompanhar() {
    clearInterval(acompanhando);
    acompanhando = setInterval(async () => {
      const dados = await carregarBase();
      if (dados && !dados.tarefa.executando) {
        clearInterval(acompanhando);
        acompanhando = null;
        resultadoDaTarefa(dados.tarefa);
      }
    }, 2000);
  }

  async function atualizar(itens) {
    botaoTudo.disabled = true;
    listaBase.querySelectorAll("button").forEach((botaoItem) => { botaoItem.disabled = true; });
    mostrarAndamento("Iniciando a atualização…");
    try {
      const resposta = await fetch("/agente/base/atualizar", {
        method: "POST",
        headers: cabecalhosBase(),
        body: JSON.stringify({ itens }),
      });
      const dados = await resposta.json().catch(() => ({ erro: "Resposta inválida do servidor." }));
      if (resposta.status === 202) {
        desenharBase(dados);
        acompanhar();
        return;
      }
      mostrarAndamento(dados.erro || `Erro ${resposta.status}.`, true);
      await carregarBase();
    } catch (erro) {
      mostrarAndamento("Não foi possível falar com o servidor.", true);
    }
  }

  botaoTudo?.addEventListener("click", () => atualizar("todos"));
  campoChave?.addEventListener("change", carregarBase);
  if (listaBase) {
    carregarBase().then((dados) => { if (dados?.tarefa.executando) acompanhar(); });
  }
})();
