/*
 * PeriodChart: plugin de série temporal por período (semana, mês, ano ou tudo).
 *
 * Uso: <div data-period-chart data-source="/api/serie?..." data-parameter="TIP-PH">
 *        <script type="application/json" data-parameters>[["TIP-PH", "pH", "pH"], ...]</script>
 *      </div>
 *
 * A fonte devolve baldes horários [hora ISO, quantidade, soma, mínimo, máximo] e
 * anomalias [data/hora, valor, alerta]; o plugin reagrega no navegador, navega
 * entre períodos e mostra média, faixa mín.–máx., anomalias e o perfil por hora.
 * API pública: instancia.setParameter(codigo), instancia.focus(codigo, dataIso, visao).
 * Depende de Chart.js 4 (window.Chart).
 */
(function (global) {
  "use strict";

  const VIEWS = {
    semana: { label: "Semana", unit: "semana", resolutions: ["hora", "dia"], resolution: "hora" },
    mes: { label: "Mês", unit: "mes", resolutions: ["dia", "semana"], resolution: "dia" },
    ano: { label: "Ano", unit: "ano", resolutions: ["semana", "mes"], resolution: "semana" },
    tudo: { label: "Tudo", unit: null, resolutions: ["dia", "semana", "mes"], resolution: "semana" },
  };
  const RESOLUTION_LABELS = { hora: "Hora", dia: "Dia", semana: "Semana", mes: "Mês" };
  const DRILL_DOWN = { ano: "mes", tudo: "mes", mes: "semana" };
  const STORAGE_KEY = "da-period-chart";

  const fmtNumber = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
  const fmtInteger = new Intl.NumberFormat("pt-BR");
  const fmtPercent = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1, signDisplay: "exceptZero" });
  const fmt = (options) => new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC", ...options });
  const fmtDay = fmt({ day: "2-digit", month: "2-digit" });
  const fmtDayLong = fmt({ weekday: "short", day: "2-digit", month: "short", year: "numeric" });
  const fmtDayShort = fmt({ day: "2-digit", month: "short" });
  const fmtMonth = fmt({ month: "long", year: "numeric" });
  const fmtMonthShort = fmt({ month: "short", year: "2-digit" });
  const fmtWeekday = fmt({ weekday: "short" });

  // Datas tratadas como UTC: as leituras chegam sem fuso e assim não há saltos de horário de verão.
  const parse = (text) => new Date(`${text.slice(0, 16)}:00Z`);
  const DAY = 86400000;

  function startOf(date, unit) {
    const d = new Date(date.getTime());
    if (unit === "hora") { d.setUTCMinutes(0, 0, 0); return d; }
    d.setUTCHours(0, 0, 0, 0);
    if (unit === "dia") return d;
    if (unit === "semana") return new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * DAY);
    d.setUTCDate(1);
    if (unit === "mes") return d;
    d.setUTCMonth(0);
    return d; // ano
  }

  function add(date, unit, amount) {
    const d = new Date(date.getTime());
    if (unit === "hora") return new Date(d.getTime() + amount * 3600000);
    if (unit === "dia") return new Date(d.getTime() + amount * DAY);
    if (unit === "semana") return new Date(d.getTime() + amount * 7 * DAY);
    if (unit === "mes") { d.setUTCMonth(d.getUTCMonth() + amount); return d; }
    d.setUTCFullYear(d.getUTCFullYear() + amount);
    return d;
  }

  function capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function bucketLabel(date, resolution) {
    if (resolution === "hora") return `${fmtDay.format(date)} ${String(date.getUTCHours()).padStart(2, "0")}h`;
    if (resolution === "mes") return capitalize(fmtMonthShort.format(date).replace(".", ""));
    return fmtDay.format(date);
  }

  function bucketTitle(date, resolution) {
    if (resolution === "hora") return `${fmtDayLong.format(date)}, ${String(date.getUTCHours()).padStart(2, "0")}h`;
    if (resolution === "dia") return fmtDayLong.format(date);
    if (resolution === "semana") return `Semana de ${fmtDayShort.format(date)} a ${fmtDayShort.format(add(date, "dia", 6))}`;
    return capitalize(fmtMonth.format(date));
  }

  function periodLabel(view, start, end) {
    if (view === "semana") {
      const last = add(end, "dia", -1);
      return `${fmtDayShort.format(start)} – ${fmtDayShort.format(last)} de ${last.getUTCFullYear()}`;
    }
    if (view === "mes") return capitalize(fmtMonth.format(start));
    if (view === "ano") return String(start.getUTCFullYear());
    return `${fmtDayShort.format(start)} de ${start.getUTCFullYear()} – ${fmtDayShort.format(add(end, "dia", -1))} de ${add(end, "dia", -1).getUTCFullYear()}`;
  }

  function cssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function el(tag, attributes = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  function readStorage() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch (error) { return {}; }
  }

  function writeStorage(value) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch (error) { /* armazenamento indisponível */ }
  }

  class PeriodChart {
    constructor(root, options = {}) {
      this.root = root;
      this.source = options.source || root.dataset.source;
      const parametersNode = root.querySelector("[data-parameters]");
      this.parameters = options.parameters || JSON.parse(parametersNode ? parametersNode.textContent : "[]");
      const saved = readStorage();
      this.state = {
        parameter: options.parameter || root.dataset.parameter || (this.parameters[0] || [])[0],
        view: VIEWS[saved.view] ? saved.view : "mes",
        resolution: saved.resolution || null,
        fullScale: Boolean(saved.fullScale),
        anchor: null,
      };
      this.cache = new Map();
      this.data = null;
      this.build();
      this.load();
      document.addEventListener("themechange", () => this.render());
    }

    // ---------- estrutura ----------
    build() {
      this.root.classList.add("pc");
      this.root.querySelectorAll(":scope > noscript").forEach((node) => node.remove());

      this.parameterSelect = el("select", { id: "pc-parameter", class: "pc-select" });
      for (const [code, name, unit] of this.parameters) {
        this.parameterSelect.append(el("option", { value: code, text: unit ? `${name} (${unit})` : name }));
      }
      this.parameterSelect.value = this.state.parameter;
      this.parameterSelect.addEventListener("change", () => this.setParameter(this.parameterSelect.value));

      this.viewButtons = {};
      const segmented = el("div", { class: "pc-segmented", role: "group", "aria-label": "Visualizar por" });
      for (const [key, view] of Object.entries(VIEWS)) {
        const button = el("button", { type: "button", class: "pc-segment", "data-view": key, "aria-pressed": "false", text: view.label });
        button.addEventListener("click", () => this.setView(key));
        this.viewButtons[key] = button;
        segmented.append(button);
      }

      this.resolutionSelect = el("select", { id: "pc-resolution", class: "pc-select" });
      this.resolutionSelect.addEventListener("change", () => {
        this.state.resolution = this.resolutionSelect.value;
        this.persist();
        this.render();
      });

      const toolbar = el("div", { class: "pc-toolbar" }, [
        el("label", { class: "pc-field", for: "pc-parameter" }, [el("span", { text: "Parâmetro" }), this.parameterSelect]),
        el("div", { class: "pc-field" }, [el("span", { text: "Visualizar por" }), segmented]),
        el("label", { class: "pc-field", for: "pc-resolution" }, [el("span", { text: "Agrupar por" }), this.resolutionSelect]),
      ]);

      this.prevButton = el("button", { type: "button", class: "pc-nav-button", "aria-label": "Período anterior", text: "‹" });
      this.nextButton = el("button", { type: "button", class: "pc-nav-button", "aria-label": "Próximo período", text: "›" });
      this.latestButton = el("button", { type: "button", class: "pc-latest", text: "Mais recente" });
      this.periodTitle = el("h3", { class: "pc-period", "aria-live": "polite" });
      this.prevButton.addEventListener("click", () => this.step(-1));
      this.nextButton.addEventListener("click", () => this.step(1));
      this.latestButton.addEventListener("click", () => { this.state.anchor = null; this.render(); });
      const nav = el("div", { class: "pc-nav" }, [
        el("div", { class: "pc-nav-group" }, [this.prevButton, this.periodTitle, this.nextButton]),
        this.latestButton,
      ]);

      this.kpis = {};
      const kpiRow = el("div", { class: "pc-kpis" });
      for (const [key, label] of [["media", "Média"], ["minimo", "Mínimo"], ["maximo", "Máximo"], ["medicoes", "Medições"], ["anomalias", "Anomalias"], ["variacao", "vs. período anterior"]]) {
        const value = el("strong", { text: "—" });
        const note = el("span", { class: "pc-kpi-note" });
        kpiRow.append(el("div", { class: `pc-kpi pc-kpi-${key}` }, [el("span", { class: "pc-kpi-label", text: label }), value, note]));
        this.kpis[key] = { value, note };
      }

      const legend = el("div", { class: "pc-legend", "aria-hidden": "true" }, [
        el("span", { class: "pc-key" }, [el("i", { class: "pc-key-line" }), "Média"]),
        el("span", { class: "pc-key" }, [el("i", { class: "pc-key-band" }), "Faixa mín.–máx."]),
        el("span", { class: "pc-key" }, [el("i", { class: "pc-key-anomaly" }), "Anomalia"]),
      ]);
      this.hint = el("span", { class: "pc-hint" });
      this.scaleNote = el("span", { class: "pc-scale-note" });
      this.scaleButton = el("button", { type: "button", class: "pc-scale", "aria-pressed": "false" });
      this.scaleButton.hidden = true;
      this.scaleButton.addEventListener("click", () => {
        this.state.fullScale = !this.state.fullScale;
        this.persist();
        this.render();
      });

      this.canvas = el("canvas", { role: "img" });
      this.status = el("div", { class: "pc-status", role: "status" });
      const chartWrap = el("div", { class: "pc-chart" }, [this.canvas, this.status]);

      this.profileCanvas = el("canvas", { role: "img", "aria-label": "Média por hora do dia no período" });
      this.profileTitle = el("p", { class: "pc-sub-title", text: "Perfil por hora do dia" });
      const profile = el("div", { class: "pc-profile" }, [
        this.profileTitle,
        el("p", { class: "pc-sub-note", text: "Média de cada hora no período exibido: revela o ciclo diário do parâmetro." }),
        el("div", { class: "pc-profile-chart" }, [this.profileCanvas]),
      ]);

      this.tableBody = el("tbody");
      const table = el("details", { class: "pc-table" }, [
        el("summary", { text: "Ver dados do período em tabela" }),
        el("div", { class: "table-scroll pc-table-scroll" }, [
          el("table", {}, [
            el("thead", {}, [el("tr", {}, ["Período", "Média", "Mínimo", "Máximo", "Medições"].map((text, index) => el("th", { class: index ? "num" : "", text })))]),
            this.tableBody,
          ]),
        ]),
      ]);

      this.renderControls();
      this.root.append(toolbar, nav,kpiRow, el("div", { class: "pc-chart-head" }, [legend, el("div", { class: "pc-chart-tools" }, [this.scaleNote, this.scaleButton])]), this.hint, chartWrap, profile, table);
      this.root.addEventListener("keydown", (event) => {
        if (event.target.closest("select, input")) return;
        if (event.key === "ArrowLeft") this.step(-1);
        if (event.key === "ArrowRight") this.step(1);
      });
    }

    persist() {
      writeStorage({ view: this.state.view, resolution: this.state.resolution, fullScale: this.state.fullScale });
    }

    // ---------- dados ----------
    async load() {
      const code = this.state.parameter;
      if (!code) return;
      this.root.classList.add("is-loading");
      this.setStatus(this.data ? "" : "Carregando série…");
      try {
        if (!this.cache.has(code)) {
          const separator = this.source.includes("?") ? "&" : "?";
          const response = await fetch(`${this.source}${separator}codigo=${encodeURIComponent(code)}`);
          const payload = await response.json();
          if (!response.ok || !payload.ok) throw new Error(payload.mensagem || "Não foi possível carregar a série.");
          payload.points = payload.pontos.map(([time, count, sum, min, max]) => ({ time: parse(time), count, sum, min, max }));
          payload.anomalies = payload.anomalias.map(([time, value, alert]) => ({ time: parse(time), value, alert }));
          this.cache.set(code, payload);
        }
        if (code !== this.state.parameter) return; // o usuário trocou de parâmetro durante a carga
        this.data = this.cache.get(code);
        this.render();
      } catch (error) {
        this.setStatus(error.message, true);
      } finally {
        this.root.classList.remove("is-loading");
      }
    }

    setStatus(message, isError = false) {
      this.status.textContent = message;
      this.status.hidden = !message;
      this.status.classList.toggle("is-error", isError);
    }

    // ---------- API pública ----------
    setParameter(code) {
      if (!this.parameters.some(([parameterCode]) => parameterCode === code)) return;
      this.state.parameter = code;
      this.parameterSelect.value = code;
      this.load();
    }

    focus(code, isoDate, view = "semana") {
      this.state.view = view;
      this.state.resolution = null;
      this.state.anchor = startOf(parse(isoDate), VIEWS[view].unit || "dia");
      this.root.scrollIntoView({ behavior: "smooth", block: "start" });
      if (code && code !== this.state.parameter) this.setParameter(code);
      else this.render();
    }

    setView(view) {
      const range = this.currentRange();
      this.state.view = view;
      this.state.resolution = null;
      // Mantém o contexto: ao trocar de visão, o novo período contém o início do anterior.
      this.state.anchor = range && VIEWS[view].unit ? startOf(range.start, VIEWS[view].unit) : null;
      this.persist();
      this.render();
    }

    step(direction) {
      const unit = VIEWS[this.state.view].unit;
      const range = this.currentRange();
      if (!unit || !range) return;
      const target = add(range.start, unit, direction);
      if (!this.hasDataBetween(target, add(target, unit, 1))) return;
      this.state.anchor = target;
      this.render();
    }

    // ---------- cálculo ----------
    extent() {
      const points = this.data ? this.data.points : [];
      if (!points.length) return null;
      return { first: points[0].time, last: points[points.length - 1].time };
    }

    hasDataBetween(start, end) {
      const extent = this.extent();
      return Boolean(extent) && extent.last >= start && extent.first < end;
    }

    currentRange() {
      const extent = this.extent();
      if (!extent) return null;
      const unit = VIEWS[this.state.view].unit;
      if (!unit) return { start: startOf(extent.first, "dia"), end: add(startOf(extent.last, "dia"), "dia", 1) };
      let start = this.state.anchor ? startOf(this.state.anchor, unit) : startOf(extent.last, unit);
      if (!this.hasDataBetween(start, add(start, unit, 1))) start = startOf(extent.last, unit);
      return { start, end: add(start, unit, 1) };
    }

    resolution() {
      const view = VIEWS[this.state.view];
      return view.resolutions.includes(this.state.resolution) ? this.state.resolution : view.resolution;
    }

    aggregate(start, end, resolution) {
      const buckets = [];
      const index = new Map();
      for (let cursor = startOf(start, resolution); cursor < end; cursor = add(cursor, resolution, 1)) {
        const bucket = { start: cursor, count: 0, sum: 0, min: Infinity, max: -Infinity, anomalies: [] };
        index.set(cursor.getTime(), bucket);
        buckets.push(bucket);
      }
      for (const point of this.data.points) {
        if (point.time < start || point.time >= end) continue;
        const bucket = index.get(startOf(point.time, resolution).getTime());
        if (!bucket) continue;
        bucket.count += point.count;
        bucket.sum += point.sum;
        bucket.min = Math.min(bucket.min, point.min);
        bucket.max = Math.max(bucket.max, point.max);
      }
      for (const anomaly of this.data.anomalies) {
        if (anomaly.time < start || anomaly.time >= end) continue;
        const bucket = index.get(startOf(anomaly.time, resolution).getTime());
        if (bucket) bucket.anomalies.push(anomaly);
      }
      for (const bucket of buckets) bucket.mean = bucket.count ? bucket.sum / bucket.count : null;
      return buckets;
    }

    summarize(start, end) {
      let count = 0; let sum = 0; let min = Infinity; let max = -Infinity;
      let minTime = null; let maxTime = null;
      const hours = Array.from({ length: 24 }, () => ({ count: 0, sum: 0 }));
      for (const point of this.data.points) {
        if (point.time < start || point.time >= end) continue;
        count += point.count;
        sum += point.sum;
        if (point.min < min) { min = point.min; minTime = point.time; }
        if (point.max > max) { max = point.max; maxTime = point.time; }
        const hour = hours[point.time.getUTCHours()];
        hour.count += point.count;
        hour.sum += point.sum;
      }
      const anomalies = this.data.anomalies.filter((anomaly) => anomaly.time >= start && anomaly.time < end).length;
      return { count, mean: count ? sum / count : null, min, max, minTime, maxTime, anomalies, hours };
    }

    /*
     * Limites "ajustados" do eixo Y: Q1/Q3 das médias horárias ± 3×IQR, sem cortar
     * nenhuma média de balde. Picos isolados (anomalias) deixam de achatar a série;
     * eles continuam na faixa, na tabela e no tooltip, e a escala completa fica a um clique.
     */
    robustBounds(start, end, buckets) {
      const values = [];
      for (const point of this.data.points) {
        if (point.time >= start && point.time < end) values.push(point.sum / point.count);
      }
      const bands = buckets.filter((bucket) => bucket.count);
      if (values.length < 8 || !bands.length) return null;
      values.sort((a, b) => a - b);
      const quantile = (q) => {
        const position = (values.length - 1) * q;
        const base = Math.floor(position);
        const next = values[Math.min(base + 1, values.length - 1)];
        return values[base] + (next - values[base]) * (position - base);
      };
      const q1 = quantile(0.25);
      const q3 = quantile(0.75);
      const iqr = q3 - q1;
      if (iqr <= 0) return null;
      const fullMin = Math.min(...bands.map((bucket) => bucket.min));
      const fullMax = Math.max(...bands.map((bucket) => bucket.max));
      const means = bands.map((bucket) => bucket.mean);
      const min = Math.max(fullMin, Math.min(q1 - 3 * iqr, ...means));
      const max = Math.min(fullMax, Math.max(q3 + 3 * iqr, ...means));
      // Só vale a pena quando corta uma parte relevante do eixo.
      if ((max - min) > 0.8 * (fullMax - fullMin)) return null;
      // Arredonda para um passo "redondo" (1, 2, 2,5 ou 5 × 10ⁿ) para os rótulos do eixo.
      const rough = (max - min) / 6;
      const power = 10 ** Math.floor(Math.log10(rough));
      const step = [1, 2, 2.5, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= rough);
      return { min: Math.floor(min / step) * step, max: Math.ceil(max / step) * step };
    }

    // ---------- desenho ----------
    colors() {
      return {
        line: cssVar("--chart-line", "#147a67"),
        band: cssVar("--chart-band", "rgba(20, 122, 103, 0.14)"),
        anomaly: cssVar("--chart-anomaly", "#b84f3a"),
        surface: cssVar("--paper", "#ffffff"),
        grid: cssVar("--chart-grid", "#e7ede9"),
        text: cssVar("--chart-text", "#63766f"),
        bar: cssVar("--chart-bar", "#7fb8a8"),
        barHighlight: cssVar("--chart-line", "#147a67"),
      };
    }

    renderControls() {
      for (const [key, button] of Object.entries(this.viewButtons)) {
        button.setAttribute("aria-pressed", String(key === this.state.view));
      }
      this.resolutionSelect.replaceChildren(...VIEWS[this.state.view].resolutions.map((key) => el("option", { value: key, text: RESOLUTION_LABELS[key] })));
      this.resolutionSelect.value = this.resolution();
    }

    render() {
      this.renderControls();
      const resolution = this.resolution();

      const range = this.currentRange();
      if (!this.data || !range) {
        this.periodTitle.textContent = "Sem dados";
        this.prevButton.disabled = this.nextButton.disabled = true;
        this.setStatus(this.data ? "Não há medições deste parâmetro no recorte." : "");
        this.bounds = null;
        this.updateCharts([], resolution, null);
        return;
      }
      this.setStatus("");
      const { start, end } = range;
      const unit = VIEWS[this.state.view].unit;
      this.periodTitle.textContent = periodLabel(this.state.view, start, end);
      this.prevButton.disabled = !unit || !this.hasDataBetween(add(start, unit, -1), start);
      this.nextButton.disabled = !unit || !this.hasDataBetween(end, add(end, unit, 1));
      const extent = this.extent();
      this.latestButton.disabled = !unit || (extent.last >= start && extent.last < end);

      const buckets = this.aggregate(start, end, resolution);
      const summary = this.summarize(start, end);
      const previous = unit ? this.summarize(add(start, unit, -1), start) : null;
      this.updateKpis(summary, previous);
      this.bounds = this.robustBounds(start, end, buckets);
      this.updateCharts(buckets, resolution, summary);
      this.updateTable(buckets, resolution);

      const drill = DRILL_DOWN[this.state.view];
      this.hint.textContent = drill && resolution !== "hora"
        ? `Clique em um ponto para abrir ${drill === "mes" ? "o mês" : "a semana"}. Use ← → para navegar.`
        : unit ? "Use ← → para navegar entre períodos." : "";
    }

    updateKpis(summary, previous) {
      const unit = this.data.unidade ? ` ${this.data.unidade}` : "";
      const set = (key, value, note = "") => { this.kpis[key].value.textContent = value; this.kpis[key].note.textContent = note; };
      if (!summary.count) {
        for (const key of Object.keys(this.kpis)) set(key, "—");
        return;
      }
      set("media", `${fmtNumber.format(summary.mean)}${unit}`);
      set("minimo", `${fmtNumber.format(summary.min)}${unit}`, summary.minTime ? bucketTitle(summary.minTime, "hora") : "");
      set("maximo", `${fmtNumber.format(summary.max)}${unit}`, summary.maxTime ? bucketTitle(summary.maxTime, "hora") : "");
      set("medicoes", fmtInteger.format(summary.count));
      set("anomalias", fmtInteger.format(summary.anomalies), summary.count ? `${fmtNumber.format((100 * summary.anomalies) / summary.count)}% das medições` : "");
      this.kpis.anomalias.value.parentElement.classList.toggle("has-alerts", summary.anomalies > 0);
      if (previous && previous.count && previous.mean) {
        const delta = ((summary.mean - previous.mean) / Math.abs(previous.mean)) * 100;
        set("variacao", `${fmtPercent.format(delta)}%`, `média anterior: ${fmtNumber.format(previous.mean)}${unit}`);
      } else {
        set("variacao", "—", previous ? "sem dados no período anterior" : "não se aplica");
      }
    }

    updateCharts(buckets, resolution, summary) {
      if (!global.Chart) {
        this.setStatus("Biblioteca de gráficos indisponível (sem acesso à CDN).", true);
        return;
      }
      const colors = this.colors();
      const labels = buckets.map((bucket) => bucketLabel(bucket.start, resolution));
      const unit = this.data && this.data.unidade ? this.data.unidade : "";
      const name = this.data ? this.data.parametro : "";
      // Um marcador por balde, no valor anômalo mais distante da média; o tooltip lista todos.
      // Na escala ajustada, o marcador de um valor fora do eixo fica preso na borda.
      const bounds = this.state.fullScale ? null : this.bounds;
      const anomalyPoints = buckets.map((bucket) => {
        if (!bucket.anomalies.length) return null;
        const value = bucket.anomalies.reduce((worst, anomaly) => (
          Math.abs(anomaly.value - bucket.mean) > Math.abs(worst.value - bucket.mean) ? anomaly : worst
        )).value;
        return bounds ? Math.min(bounds.max, Math.max(bounds.min, value)) : value;
      });
      const dense = buckets.length > 60;
      this.canvas.setAttribute("aria-label", `Média de ${name} por ${RESOLUTION_LABELS[resolution].toLowerCase()} em ${this.periodTitle.textContent}, com faixa entre mínimo e máximo e anomalias marcadas.`);

      const datasets = [
        {
          label: "Máximo", data: buckets.map((bucket) => (bucket.count ? bucket.max : null)),
          borderWidth: 0, pointRadius: 0, pointHitRadius: 0, fill: "+1", backgroundColor: colors.band, order: 3,
        },
        {
          label: "Mínimo", data: buckets.map((bucket) => (bucket.count ? bucket.min : null)),
          borderWidth: 0, pointRadius: 0, pointHitRadius: 0, fill: false, order: 3,
        },
        {
          label: "Média", data: buckets.map((bucket) => bucket.mean), borderColor: colors.line, backgroundColor: colors.line,
          borderWidth: 2, pointRadius: dense ? 0 : 3, pointHoverRadius: 5, pointBorderColor: colors.surface, pointBorderWidth: 1.5,
          tension: 0.25, spanGaps: false, order: 2,
        },
        {
          label: "Anomalia", data: anomalyPoints, showLine: false, pointStyle: "triangle", pointRadius: 6, pointHoverRadius: 8,
          backgroundColor: colors.anomaly, pointBorderColor: colors.surface, pointBorderWidth: 1.5, order: 1,
        },
      ];

      if (!this.chart) {
        this.chart = new global.Chart(this.canvas, {
          type: "line",
          data: { labels, datasets },
          options: {
            maintainAspectRatio: false,
            animation: { duration: 250 },
            interaction: { mode: "index", intersect: false },
            onClick: (event, elements) => this.drillDown(elements),
            onHover: (event, elements) => {
              const clickable = DRILL_DOWN[this.state.view] && elements.length && this.resolution() !== "hora";
              event.native.target.style.cursor = clickable ? "pointer" : "default";
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                filter: (item) => item.dataset.label === "Média" || item.dataset.label === "Anomalia",
                callbacks: {
                  title: (items) => {
                    const bucket = this.buckets[items[0].dataIndex];
                    return bucket ? bucketTitle(bucket.start, this.resolution()) : "";
                  },
                  label: (context) => {
                    const unitText = this.data.unidade ? ` ${this.data.unidade}` : "";
                    if (context.dataset.label === "Anomalia") {
                      const count = this.buckets[context.dataIndex].anomalies.length;
                      return `▲ ${fmtInteger.format(count)} ${count === 1 ? "anomalia" : "anomalias"} (ver abaixo)`;
                    }
                    if (context.raw === null) return "Sem medições";
                    return `Média: ${fmtNumber.format(context.raw)}${unitText}`;
                  },
                  afterBody: (items) => {
                    const bucket = this.buckets[items[0].dataIndex];
                    if (!bucket || !bucket.count) return [];
                    const unitText = this.data.unidade ? ` ${this.data.unidade}` : "";
                    const lines = [
                      `Mínimo: ${fmtNumber.format(bucket.min)}${unitText}`,
                      `Máximo: ${fmtNumber.format(bucket.max)}${unitText}`,
                      `Medições: ${fmtInteger.format(bucket.count)}`,
                    ];
                    const shown = bucket.anomalies.slice(0, 5).map((anomaly) => (
                      `▲ ${fmtDay.format(anomaly.time)} ${String(anomaly.time.getUTCHours()).padStart(2, "0")}:${String(anomaly.time.getUTCMinutes()).padStart(2, "0")} · ${fmtNumber.format(anomaly.value)}${unitText} (${anomaly.alert})`
                    ));
                    if (bucket.anomalies.length > shown.length) shown.push(`… e mais ${bucket.anomalies.length - shown.length}`);
                    return shown.length ? [...lines, "", ...shown] : lines;
                  },
                },
              },
            },
            scales: {
              x: { type: "category", ticks: { autoSkip: true, maxTicksLimit: 10, maxRotation: 0 }, grid: { display: false } },
              y: { grace: "5%", title: { display: true } },
            },
          },
        });
      } else {
        this.chart.data.labels = labels;
        this.chart.data.datasets = datasets;
      }
      this.buckets = buckets;
      const options = this.chart.options;
      options.scales.x.ticks.color = colors.text;
      options.scales.x.border = { color: colors.grid };
      options.scales.y.ticks = { color: colors.text, callback: (value) => fmtNumber.format(value) };
      options.scales.y.grid = { color: colors.grid };
      options.scales.y.border = { display: false };
      options.scales.y.title.text = unit ? `${name} (${unit})` : name;
      options.scales.y.title.color = colors.text;
      options.scales.y.min = bounds ? bounds.min : undefined;
      options.scales.y.max = bounds ? bounds.max : undefined;
      this.updateScaleControls(buckets);
      this.chart.update();

      this.updateProfile(summary, colors, unit);
    }

    updateScaleControls(buckets) {
      this.scaleButton.hidden = !this.bounds;
      this.scaleButton.textContent = this.state.fullScale ? "Escala ajustada" : "Escala completa";
      this.scaleButton.setAttribute("aria-pressed", String(this.state.fullScale));
      this.scaleButton.title = this.state.fullScale
        ? "Ajusta o eixo à variação típica, sem deixar picos isolados achatarem a série"
        : "Mostra o eixo inteiro, do menor ao maior valor medido";
      if (!this.bounds || this.state.fullScale) { this.scaleNote.textContent = ""; return; }
      let outside = 0;
      for (const bucket of buckets) {
        for (const anomaly of bucket.anomalies) {
          if (anomaly.value < this.bounds.min || anomaly.value > this.bounds.max) outside += 1;
        }
      }
      this.scaleNote.textContent = outside
        ? `Escala ajustada: ${fmtInteger.format(outside)} ${outside === 1 ? "anomalia fica" : "anomalias ficam"} fora do eixo`
        : "Escala ajustada à variação típica";
    }

    updateProfile(summary, colors, unit) {
      const hours = summary ? summary.hours : [];
      const means = hours.map((hour) => (hour.count ? hour.sum / hour.count : null));
      const valid = means.filter((value) => value !== null);
      const peak = valid.length ? Math.max(...valid) : null;
      const labels = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, "0")}h`);
      const background = means.map((value) => (value !== null && value === peak ? colors.barHighlight : colors.bar));
      if (!this.profileChart) {
        this.profileChart = new global.Chart(this.profileCanvas, {
          type: "bar",
          data: { labels, datasets: [{ label: "Média", data: means, backgroundColor: background, borderRadius: 4, borderSkipped: "start", categoryPercentage: 0.86, barPercentage: 0.92 }] },
          options: {
            maintainAspectRatio: false,
            animation: { duration: 250 },
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (context) => `Média: ${fmtNumber.format(context.raw)}${this.data && this.data.unidade ? ` ${this.data.unidade}` : ""}` } },
            },
            scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } }, y: {} },
          },
        });
      } else {
        this.profileChart.data.datasets[0].data = means;
        this.profileChart.data.datasets[0].backgroundColor = background;
      }
      const options = this.profileChart.options;
      options.scales.x.ticks.color = colors.text;
      options.scales.x.border = { color: colors.grid };
      // Barras partem do zero só quando o parâmetro admite zero; senão a variação diária some.
      options.scales.y.beginAtZero = valid.length > 0 && Math.min(...valid) >= 0 && Math.min(...valid) < peak * 0.25;
      options.scales.y.ticks = { color: colors.text, maxTicksLimit: 5, callback: (value) => fmtNumber.format(value) };
      options.scales.y.grid = { color: colors.grid };
      options.scales.y.border = { display: false };
      this.profileTitle.textContent = peak !== null
        ? `Perfil por hora do dia · pico às ${labels[means.indexOf(peak)]} (${fmtNumber.format(peak)}${unit ? ` ${unit}` : ""})`
        : "Perfil por hora do dia";
      this.profileChart.update();
    }

    updateTable(buckets, resolution) {
      const rows = buckets.filter((bucket) => bucket.count).map((bucket) => el("tr", {}, [
        el("td", { text: bucketTitle(bucket.start, resolution) }),
        el("td", { class: "num", text: fmtNumber.format(bucket.mean) }),
        el("td", { class: "num", text: fmtNumber.format(bucket.min) }),
        el("td", { class: "num", text: fmtNumber.format(bucket.max) }),
        el("td", { class: "num", text: fmtInteger.format(bucket.count) }),
      ]));
      this.tableBody.replaceChildren(...rows);
    }

    drillDown(elements) {
      const target = DRILL_DOWN[this.state.view];
      if (!target || !elements.length || this.resolution() === "hora") return;
      const bucket = this.buckets[elements[0].index];
      if (!bucket || !bucket.count) return;
      this.state.view = target;
      this.state.resolution = null;
      this.state.anchor = startOf(bucket.start, VIEWS[target].unit);
      this.persist();
      this.render();
    }
  }

  PeriodChart.init = (selector = "[data-period-chart]") => [...document.querySelectorAll(selector)].map((root) => {
    root.periodChart = root.periodChart || new PeriodChart(root);
    return root.periodChart;
  });

  global.PeriodChart = PeriodChart;
})(window);
