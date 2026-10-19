const ingestButton = document.querySelector("#ingest-button");
const ingestStatus = document.querySelector("#ingest-status");
const ingestSummary = document.querySelector("#ingest-summary");

ingestButton?.addEventListener("click", async () => {
  ingestButton.disabled = true;
  ingestStatus.classList.remove("error");
  ingestStatus.textContent = "Executando coleta e validação...";

  try {
    const response = await fetch("/ingestao", { method: "POST" });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.mensagem || "A ingestão não foi concluída.");
    }

    ingestStatus.textContent = "Ingestão concluída. Atualizando dados...";
    const summary = result.resumo;
    ingestSummary.hidden = false;
    ingestSummary.textContent = `${summary.recebidos} recebidos · ${summary.registros_validos} válidos · ${summary.leituras_gravadas} gravados`;
    window.location.reload();
  } catch (error) {
    ingestStatus.textContent = error.message;
    ingestStatus.classList.add("error");
    ingestButton.disabled = false;
  }
});

// Tema claro/escuro: segue o sistema até o usuário escolher.
document.querySelector("#theme-toggle")?.addEventListener("click", () => {
  const root = document.documentElement;
  const current = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  try { localStorage.setItem("da-tema", next); } catch (error) { /* armazenamento indisponível */ }
  document.dispatchEvent(new CustomEvent("themechange"));
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  document.dispatchEvent(new CustomEvent("themechange"));
});

// Atalhos de período: os últimos N dias até a medição mais recente gravada.
document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    const days = Number(button.dataset.preset);
    const start = document.querySelector("#start-date");
    const end = document.querySelector("#end-date");
    if (!days) {
      start.value = "";
      end.value = "";
    } else {
      const lastDate = button.parentElement.dataset.lastDate || new Date().toISOString().slice(0, 10);
      const last = new Date(`${lastDate}T00:00:00Z`);
      const first = new Date(last.getTime() - (days - 1) * 86400000);
      end.value = last.toISOString().slice(0, 10);
      start.value = first.toISOString().slice(0, 10);
    }
    button.closest("form").requestSubmit();
  });
});

document.querySelectorAll("[data-autosubmit]").forEach((select) => {
  select.addEventListener("change", () => select.form.requestSubmit());
});

// Gráfico por período (plugin em period-chart.js) e atalhos das tabelas.
const charts = window.PeriodChart ? window.PeriodChart.init() : [];
const periodChart = charts[0];

const parameterCodeByName = (name) => {
  const option = [...document.querySelectorAll("#pc-parameter option")]
    .find((item) => item.textContent === name || item.textContent.startsWith(`${name} (`));
  return option?.value;
};

document.querySelectorAll("[data-show-parameter]").forEach((button) => {
  if (!periodChart) { button.hidden = true; return; }
  button.addEventListener("click", () => {
    periodChart.setParameter(button.dataset.showParameter);
    periodChart.root.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

document.querySelectorAll("[data-show-date]").forEach((button) => {
  if (!periodChart) { button.hidden = true; return; }
  button.addEventListener("click", () => {
    periodChart.focus(parameterCodeByName(button.dataset.showParameterName), button.dataset.showDate, "semana");
  });
});
