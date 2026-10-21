// Página "Testar API do BI": chama /api-bi/consulta e /api-bi/verificar no Flask,
// que repassa as chamadas para /api/v1/bi com a chave guardada no servidor.
const biForm = document.querySelector("#bi-form");
const biRota = document.querySelector("#bi-rota");
const biErro = document.querySelector("#bi-erro");
const numero = new Intl.NumberFormat("pt-BR");

const mostrarErro = (mensagem) => {
  biErro.textContent = mensagem || "";
  biErro.hidden = !mensagem;
};

const celula = (texto, classe) => {
  const td = document.createElement("td");
  if (classe) td.className = classe;
  td.textContent = texto;
  return td;
};

const statusTag = (resultado) => {
  const span = document.createElement("span");
  span.className = resultado.ok ? "bi-tag bi-tag-ok" : "bi-tag bi-tag-erro";
  span.textContent = resultado.status ? `${resultado.status}` : "sem resposta";
  return span;
};

const formatarValor = (valor) => {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "number") return Number.isInteger(valor) ? String(valor) : numero.format(Math.round(valor * 1000) / 1000);
  if (typeof valor === "boolean") return valor ? "sim" : "não";
  return String(valor).replace(/T00:00:00(\.000)?$/, "").replace(/\.000$/, "").replace("T", " ");
};

// Mostra só os campos da rota escolhida: filtros nas medições, paginação na fato.
const atualizarCampos = () => {
  const opcao = biRota.selectedOptions[0];
  const comFiltro = opcao.hasAttribute("data-filtros");
  document.querySelector("#bi-filtros").hidden = !comFiltro;
  document.querySelector("#bi-filtros").disabled = !comFiltro;
  const paginacao = document.querySelector("#bi-paginacao");
  paginacao.hidden = biRota.value !== "medicoes";
  paginacao.querySelectorAll("input").forEach((input) => { input.disabled = biRota.value !== "medicoes"; });
};
biRota?.addEventListener("change", atualizarCampos);
if (biRota) atualizarCampos();

const renderizarAmostra = (resultado) => {
  const tabela = document.querySelector("#bi-amostra");
  tabela.replaceChildren();
  const nota = document.querySelector("#bi-amostra-nota");
  if (!resultado.amostra?.length) {
    nota.textContent = "A rota respondeu sem linhas para o recorte informado.";
    return;
  }
  const thead = tabela.createTHead().insertRow();
  resultado.colunas.forEach((coluna) => {
    const th = document.createElement("th");
    th.textContent = coluna;
    thead.append(th);
  });
  const tbody = tabela.createTBody();
  resultado.amostra.forEach((linha) => {
    const tr = tbody.insertRow();
    resultado.colunas.forEach((coluna) => {
      tr.append(celula(formatarValor(linha[coluna]), typeof linha[coluna] === "number" ? "num" : ""));
    });
  });
  nota.textContent = `Amostra com as primeiras ${resultado.amostra.length} de ${numero.format(resultado.linhas)} linhas recebidas.`;
};

// Executa a rota escolhida no formulário; rolar = levar a tela até o resultado.
const executarConsulta = async (rolar = true) => {
  const botao = biForm.querySelector("button[type=submit]");
  botao.disabled = true;
  mostrarErro("");
  const parametros = new URLSearchParams();
  new FormData(biForm).forEach((valor, nome) => { if (valor !== "") parametros.append(nome, valor); });

  try {
    const resposta = await fetch(`/api-bi/consulta?${parametros}`);
    const resultado = await resposta.json();
    const secao = document.querySelector("#bi-resultado");
    secao.hidden = false;
    document.querySelector("#bi-url").textContent = resultado.url || "";
    const status = document.querySelector("#bi-status");
    status.replaceChildren(statusTag(resultado), ` · ${resultado.descricao || ""}`);
    document.querySelector("#bi-tempo").textContent = resultado.tempo_ms != null ? `${numero.format(resultado.tempo_ms)} ms` : "—";
    if (!resultado.ok) {
      mostrarErro(resultado.mensagem);
      ["#bi-total", "#bi-linhas", "#bi-colunas"].forEach((id) => { document.querySelector(id).textContent = "—"; });
      document.querySelector("#bi-amostra").replaceChildren();
      document.querySelector("#bi-amostra-nota").textContent = "";
      return;
    }
    document.querySelector("#bi-total").textContent = numero.format(resultado.total);
    document.querySelector("#bi-linhas").textContent = numero.format(resultado.linhas);
    document.querySelector("#bi-colunas").textContent = resultado.colunas.length;
    const pag = resultado.paginacao;
    document.querySelector("#bi-pagina-info").textContent = pag
      ? `página ${numero.format(pag.pagina)} de ${numero.format(pag.total_paginas)}`
      : "linhas recebidas";
    renderizarAmostra(resultado);
    if (rolar) secao.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (erro) {
    mostrarErro("Não foi possível falar com o dashboard. Confira se o Flask está rodando.");
  } finally {
    botao.disabled = false;
  }
};

biForm?.addEventListener("submit", (evento) => {
  evento.preventDefault();
  executarConsulta();
});

const definirCard = (id, valor, nota, estado) => {
  document.querySelector(`#bi-${id}`).textContent = valor;
  if (nota !== undefined) document.querySelector(`#bi-${id}-nota`).textContent = nota;
  const card = document.querySelector(`#bi-card-${id}`);
  if (card) {
    card.classList.toggle("metric-alert", estado === "erro");
    card.classList.toggle("metric-ok", estado === "ok");
  }
};

const escapar = (texto) => String(texto).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const orientar = (html) => {
  const aviso = document.querySelector("#bi-orientacao");
  aviso.innerHTML = html || "";
  aviso.hidden = !html;
};

const renderizarRotas = (rotas) => {
  const linhas = document.querySelector("#bi-check-linhas");
  linhas.replaceChildren(...rotas.map((r) => {
    const tr = document.createElement("tr");
    const status = document.createElement("td");
    status.append(statusTag(r));
    tr.append(
      celula(`/${r.rota}`),
      celula(r.descricao),
      status,
      celula(r.tempo_ms != null ? `${numero.format(r.tempo_ms)} ms` : "—", "num"),
      celula(r.ok ? numero.format(r.total) : "—", "num"),
      celula(r.ok ? "" : r.mensagem),
    );
    return tr;
  }));
  document.querySelector("#bi-check-resumo").textContent = `${rotas.filter((r) => r.ok).length} de ${rotas.length} rotas respondendo`;
  document.querySelector("#bi-verificacao").hidden = !rotas.length;
};

// Situação geral, carregada ao abrir a página e pelo botão "Atualizar status".
const carregarStatus = async () => {
  const botao = document.querySelector("#bi-check");
  botao.disabled = true;
  mostrarErro("");
  try {
    const s = await (await fetch("/api-bi/status")).json();
    if (!s.api.online) {
      definirCard("api", "Offline", s.api.mensagem ? "sem resposta" : `HTTP ${s.api.status}`, "erro");
      definirCard("gold", "—", "depende da API", null);
      definirCard("rotas", "0");
      document.querySelector("#bi-medicoes").textContent = "—";
      orientar(`<strong>A API não respondeu em <code>${escapar(s.servidor)}</code>.</strong> Em outro terminal, na raiz do projeto, execute <code>python -m uvicorn src.api.app:app</code> e clique em "Atualizar status".`);
      renderizarRotas([]);
      return;
    }
    definirCard("api", "Online", `${s.servidor} · ${numero.format(s.api.tempo_ms)} ms`, "ok");
    definirCard("rotas", `${s.rotas_ok}`, undefined, s.rotas_ok === s.rotas.length ? "ok" : "erro");
    document.querySelector("#bi-medicoes").textContent = s.total_medicoes != null ? numero.format(s.total_medicoes) : "—";
    renderizarRotas(s.rotas);
    if (s.gold_disponivel) {
      definirCard("gold", "Disponível", "4 tabelas Parquet lidas", "ok");
      orientar("");
      executarConsulta(false);
    } else if (s.gold_mensagem) {
      definirCard("gold", "Vazia", "nenhum Parquet gerado", "erro");
      orientar('<strong>A API está no ar, mas a camada Gold ainda não foi gerada.</strong> Execute a ingestão, que grava Bronze, Silver e Gold em <code>data_lake/</code>: botão "Executar ingestão" no <a href="/">dashboard</a> ou <code>python main.py --ingestao</code>. Depois clique em "Atualizar status".');
    } else {
      definirCard("gold", "Erro", "veja a tabela de rotas", "erro");
      orientar("");
    }
  } catch (erro) {
    mostrarErro("Não foi possível falar com o dashboard. Confira se o Flask está rodando.");
  } finally {
    botao.disabled = false;
  }
};

document.querySelector("#bi-check")?.addEventListener("click", carregarStatus);
if (biForm) carregarStatus();

document.querySelector("#bi-copiar")?.addEventListener("click", async (evento) => {
  const botao = evento.currentTarget;
  try {
    await navigator.clipboard.writeText(document.querySelector("#bi-url").textContent);
    botao.textContent = "Copiada";
    setTimeout(() => { botao.textContent = "Copiar URL"; }, 1500);
  } catch (erro) { /* área de transferência indisponível */ }
});
