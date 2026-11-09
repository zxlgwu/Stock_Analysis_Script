(function () {
  const screens = ["week", "ideas", "company", "run", "settings"];
  const chartPattern = /^\/charts\/\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]+\.png$/;
  const logLines = [];
  let generation = null;
  let companyTimer = null;

  const storyList = document.getElementById("story-list");
  const storyDetail = document.getElementById("story-detail");
  const weekEnding = document.getElementById("week-ending");
  const ideasEnding = document.getElementById("ideas-ending");
  const companyMatches = document.getElementById("company-matches");
  const companyDetail = document.getElementById("company-detail");
  const companyQuery = document.getElementById("company-query");
  const runLog = document.getElementById("run-log");
  const runStatus = document.getElementById("run-status");
  const collectButton = document.getElementById("collect-button");
  const weeklyButton = document.getElementById("weekly-button");
  const settingsForm = document.getElementById("settings-form");
  const settingsStatus = document.getElementById("settings-status");
  const settingsSave = document.getElementById("settings-save");
  const emailStatus = document.getElementById("email-status");
  const analysisModel = document.getElementById("analysis-model");

  document.querySelectorAll(".nav button").forEach((button) => {
    button.addEventListener("click", () => show(button.dataset.screen));
  });
  document.getElementById("company-form").addEventListener("submit", (event) => {
    event.preventDefault();
    searchCompanies();
  });
  companyQuery.addEventListener("input", () => {
    window.clearTimeout(companyTimer);
    companyTimer = window.setTimeout(searchCompanies, 250);
  });
  collectButton.addEventListener("click", () => startJob("collect"));
  weeklyButton.addEventListener("click", () => startJob("weekly"));
  settingsForm.addEventListener("submit", saveSettings);
  document.body.addEventListener("click", openExternal);
  window.addEventListener("hashchange", () => show(location.hash.slice(1), false));

  show(location.hash.slice(1) || "week", false);
  connectLog();

  function show(name, updateHash) {
    const screen = screens.includes(name) ? name : "week";
    screens.forEach((item) => {
      document.getElementById("screen-" + item).hidden = item !== screen;
      const button = document.getElementById("nav-" + item);
      if (item === screen) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (updateHash !== false && location.hash !== "#" + screen) {
      history.replaceState(null, "", "#" + screen);
    }
    if (screen === "week") loadWeek();
    if (screen === "ideas") loadIdeas();
    if (screen === "settings") loadSettings();
    if (screen === "run") runLog.scrollTop = runLog.scrollHeight;
  }

  async function loadWeek() {
    storyDetail.hidden = true;
    storyList.hidden = false;
    try {
      const payload = await api("/api/week");
      weekEnding.textContent = payload.week_ending
        ? "Week ending " + payload.week_ending + ". Open a story to see how the effect spreads."
        : "Stories the agent analyzed, with the way each effect spreads.";
      storyList.replaceChildren();
      if (!payload.stories.length) {
        storyList.append(el("p", { class: "empty" }, ["Analyzed stories appear here after a weekly run."]));
        return;
      }
      const withEffects = payload.stories.filter((story) => story.effect_count > 0);
      const quiet = payload.stories.filter((story) => story.effect_count === 0);
      withEffects.forEach((story) => storyList.append(storyButton(story)));
      if (quiet.length) {
        storyList.append(el("h2", {}, ["Reviewed, with no concrete revenue effect on a tracked company"]));
        quiet.forEach((story) => storyList.append(storyButton(story)));
      }
    } catch (error) {
      storyList.replaceChildren(el("p", { class: "empty" }, [error.message]));
    }
  }

  function storyButton(story) {
    const count = story.effect_count
      ? story.effect_count + (story.effect_count === 1 ? " company effect" : " company effects")
      : "No concrete revenue effect";
    return el("button", { class: "story-button", type: "button", onclick: () => openStory(story.cluster_id) }, [
      el("strong", {}, [story.title]),
      el("div", {}, [el("small", {}, [count])]),
    ]);
  }

  async function openStory(clusterId) {
    try {
      const story = await api("/api/story?id=" + encodeURIComponent(clusterId));
      storyList.hidden = true;
      storyDetail.hidden = false;
      const blocks = [
        el("button", { class: "back", type: "button", onclick: () => { storyDetail.hidden = true; storyList.hidden = false; } }, ["All stories"]),
        el("h2", {}, [story.title]),
      ];
      if (story.summary && story.summary !== story.title) blocks.push(el("p", {}, [story.summary]));
      if (safeHttp(story.url)) blocks.push(externalLink(story.url, "Source"));
      blocks.push(el("h3", {}, ["How the effect spreads"]));
      if (story.steps.length) {
        blocks.push(el("ol", { class: "steps" }, story.steps.map(stepItem)));
      } else {
        blocks.push(el("p", { class: "empty" }, ["The spread for this story appears here after analysis records it."]));
      }
      blocks.push(el("h3", {}, ["Revenue effects"]));
      if (story.effects.length) {
        blocks.push(el("ul", { class: "effects" }, story.effects.map(effectItem)));
      } else {
        blocks.push(el("p", { class: "empty" }, ["This story has no concrete revenue effect on a tracked company."]));
      }
      storyDetail.replaceChildren(el("article", { class: "card" }, blocks));
    } catch (error) {
      storyDetail.hidden = false;
      storyDetail.replaceChildren(el("p", { class: "empty" }, [error.message]));
    }
  }

  function stepItem(step) {
    const reached = step.tickers.length ? " Tracked companies: " + step.tickers.join(", ") + "." : "";
    return el("li", {}, [
      el("strong", {}, [step.label]),
      " — " + step.target + " (" + step.relation + ", " + step.direction + "): " + step.mechanism + reached,
    ]);
  }

  function effectItem(effect) {
    const bits = [
      el("strong", {}, [effect.name + " (" + effect.ticker + ")"]),
      " — " + effect.direction + ", " + effect.horizon_label + ", " + effect.relation_label + ". ",
      "Revenue line: " + (effect.revenue_line || "not named") + ". ",
      "Estimated impact: " + effect.estimated_impact + ". ",
      "Confidence: " + Number(effect.confidence).toFixed(2) + ". ",
      "Already in the price: " + (effect.priced_in || "not stated") + ".",
    ];
    const item = el("li", {}, bits);
    if (effect.reasoning) item.append(el("div", {}, ["Logic: " + effect.reasoning]));
    const source = effect.source_url || "";
    if (safeHttp(source)) item.append(el("div", {}, [externalLink(source, effect.source_title || "Source")]));
    return item;
  }

  async function loadIdeas() {
    try {
      const payload = await api("/api/ideas");
      ideasEnding.textContent = payload.week_ending
        ? "Week ending " + payload.week_ending + ". Each card has the thesis and the price chart from that run."
        : "Long-term, mid-term, and risk ideas appear here after a weekly run.";
      renderIdeaList("ideas-long", payload.long, "Long-term ideas appear here after a weekly run.");
      renderIdeaList("ideas-mid", payload.mid, "Mid-term ideas appear here after a weekly run.");
      renderIdeaList("ideas-risk", payload.risk, "Risk ideas appear here after a weekly run.");
    } catch (error) {
      ["ideas-long", "ideas-mid", "ideas-risk"].forEach((id) => {
        document.getElementById(id).replaceChildren(el("p", { class: "empty" }, [error.message]));
      });
    }
  }

  function renderIdeaList(id, rows, emptyText) {
    const host = document.getElementById(id);
    host.replaceChildren();
    if (!rows || !rows.length) {
      host.append(el("p", { class: "empty" }, [emptyText]));
      return;
    }
    rows.forEach((row) => host.append(ideaCard(row)));
  }

  function ideaCard(row) {
    const children = [
      el("h3", {}, [row.rank + ". " + row.ticker + " — " + row.name]),
      el("p", { class: "meta" }, ["Score " + row.composite_display + " · Net revenue impact " + row.net_revenue_display]),
      el("p", {}, [row.thesis || "The thesis appears here after the weekly write-up."]),
    ];
    if (row.risks) children.push(el("p", {}, [el("strong", {}, ["Risks. "]), row.risks]));
    if (chartPattern.test(row.chart_url || "")) {
      children.push(el("img", { class: "chart", alt: row.ticker + " price chart", src: row.chart_url }));
    } else {
      children.push(el("p", { class: "empty" }, ["The price chart appears here after a weekly run includes this company."]));
    }
    return el("article", { class: "card" }, children);
  }

  async function searchCompanies() {
    const query = companyQuery.value.trim();
    companyMatches.replaceChildren();
    if (!query) {
      companyMatches.append(el("p", { class: "empty" }, ["Enter a ticker or company name."]));
      return;
    }
    try {
      const payload = await api("/api/companies?q=" + encodeURIComponent(query));
      if (!payload.companies.length) {
        companyMatches.append(el("p", { class: "empty" }, ["No company matches that search."]));
        return;
      }
      payload.companies.forEach((company) => {
        const label = company.ticker + " — " + company.name;
        const extra = [company.sector, company.industry].filter(Boolean).join(" · ");
        companyMatches.append(el("button", {
          class: "match-button",
          type: "button",
          onclick: () => loadCompany(company.ticker),
        }, [el("strong", {}, [label]), extra ? el("div", {}, [el("small", {}, [extra])]) : ""]));
      });
    } catch (error) {
      companyMatches.append(el("p", { class: "empty" }, [error.message]));
    }
  }

  async function loadCompany(ticker) {
    try {
      const company = await api("/api/company?ticker=" + encodeURIComponent(ticker));
      const blocks = [
        el("h2", {}, [company.ticker + " — " + company.name]),
        el("p", { class: "meta" }, [[company.exchange, company.sector, company.industry].filter(Boolean).join(" · ")]),
        el("h3", {}, ["Price statistics"]),
      ];
      if (company.price_lines && company.price_lines.length) {
        blocks.push(el("ul", { class: "stats" }, company.price_lines.map((line) => el("li", {}, [el("span", {}, [line.label]), el("strong", {}, [line.value])]))));
      } else {
        blocks.push(el("p", { class: "empty" }, ["Price statistics appear here after a collection run."]));
      }
      blocks.push(el("h3", {}, ["Revenue effects"]));
      if (company.impacts.length) {
        blocks.push(el("ul", { class: "effects" }, company.impacts.map(effectItem)));
      } else {
        blocks.push(el("p", { class: "empty" }, ["No revenue effects are stored for this company yet."]));
      }
      blocks.push(el("h3", {}, ["Chart"]));
      if (chartPattern.test(company.chart_url || "")) {
        blocks.push(el("img", { class: "chart", alt: company.ticker + " price chart", src: company.chart_url }));
      } else {
        blocks.push(el("p", { class: "empty" }, ["The price chart appears here after a weekly run includes this company."]));
      }
      companyDetail.replaceChildren(el("article", { class: "card" }, blocks));
    } catch (error) {
      companyDetail.replaceChildren(el("p", { class: "empty" }, [error.message]));
    }
  }

  async function startJob(kind) {
    runStatus.textContent = kind === "weekly" ? "Starting the weekly analysis." : "Starting collection.";
    try {
      await api("/api/run/" + kind, { method: "POST" });
    } catch (error) {
      runStatus.textContent = error.message;
    }
  }

  function connectLog() {
    if (!window.EventSource) {
      window.setInterval(pullLog, 1000);
      return;
    }
    const source = new EventSource("/api/run/stream");
    source.addEventListener("status", (event) => {
      const status = JSON.parse(event.data);
      if (generation !== null && status.generation !== generation) {
        logLines.length = 0;
        renderLog();
      }
      generation = status.generation;
      applyStatus(status);
    });
    source.addEventListener("line", (event) => {
      logLines.push(JSON.parse(event.data).line);
      renderLog();
    });
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) window.setInterval(pullLog, 1000);
    };
  }

  async function pullLog() {
    try {
      const snap = await api("/api/run");
      logLines.length = 0;
      snap.lines.forEach((line) => logLines.push(line));
      renderLog();
      applyStatus(snap);
    } catch (error) {
      runStatus.textContent = error.message;
    }
  }

  function renderLog() {
    runLog.textContent = logLines.length ? logLines.join("\n") : "Job output appears here, including each Mapping line.";
    runLog.scrollTop = runLog.scrollHeight;
  }

  function applyStatus(status) {
    const running = status.status === "running";
    collectButton.disabled = running;
    weeklyButton.disabled = running;
    settingsSave.disabled = running;
    const labels = {
      idle: "Ready for a job.",
      running: status.job === "weekly" ? "Weekly analysis is running." : "Collection is running.",
      finished: "The job finished.",
      failed: "The job stopped before it finished. The log has the detail.",
    };
    runStatus.textContent = labels[status.status] || "Ready for a job.";
  }

  async function loadSettings() {
    try {
      const payload = await api("/api/settings");
      analysisModel.replaceChildren();
      payload.models.forEach((model) => {
        const label = modelLabel(model);
        const option = el("option", { value: model.model }, [label]);
        if (!model.selectable) option.disabled = true;
        if (model.model === payload.analysis_model && model.selectable) option.selected = true;
        analysisModel.append(option);
      });
      if (![...analysisModel.options].some((option) => option.selected && !option.disabled)) {
        const current = [...analysisModel.options].find((option) => option.value === payload.analysis_model && !option.disabled);
        if (current) current.selected = true;
      }
      document.getElementById("stories-per-week").value = payload.max_stories_per_week;
      document.getElementById("fetch-article-text").checked = Boolean(payload.fetch_article_text);
      document.getElementById("top-n").value = payload.top_n;
      const selected = new Set(payload.news_sources || []);
      settingsForm.querySelectorAll('input[name="news"]').forEach((box) => {
        box.checked = selected.has(box.value);
      });
      document.getElementById("recipient").value = (payload.recipients || []).join(", ");
      emailStatus.textContent = payload.email_configured ? "Email is configured." : "Email is not configured yet.";
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
  }

  function modelLabel(model) {
    const size = model.size ? " (" + model.size + ")" : "";
    if (model.kind === "too_large") return model.name + size + " — too large for this 8 GB Mac";
    if (model.note) return model.name + size + " — " + model.note;
    return model.name + size;
  }

  async function saveSettings(event) {
    event.preventDefault();
    settingsStatus.textContent = "Saving settings.";
    const news = [...settingsForm.querySelectorAll('input[name="news"]:checked')].map((box) => box.value);
    const body = {
      analysis_model: analysisModel.value,
      max_stories_per_week: Number(document.getElementById("stories-per-week").value),
      fetch_article_text: document.getElementById("fetch-article-text").checked,
      top_n: Number(document.getElementById("top-n").value),
      news_sources: news,
      recipients: document.getElementById("recipient").value.split(",").map((part) => part.trim()).filter(Boolean),
    };
    try {
      await api("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      settingsStatus.textContent = "Settings saved. The next run uses them.";
      loadSettings();
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
  }

  function openExternal(event) {
    const link = event.target.closest("a[data-external]");
    if (!link) return;
    event.preventDefault();
    const url = link.getAttribute("href") || "";
    if (!safeHttp(url)) return;
    const bridge = window.pywebview && window.pywebview.api;
    if (bridge && bridge.open_link) bridge.open_link(url);
    else window.open(url, "_blank", "noopener");
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The local server did not respond.");
    return data;
  }

  function externalLink(url, label) {
    return el("a", { href: url, "data-external": "true" }, [label]);
  }

  function safeHttp(url) {
    return /^https?:\/\//i.test(url || "");
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else if (key === "onclick") node.addEventListener("click", value);
      else if (key in node && key !== "value") node[key] = value;
      else node.setAttribute(key, value);
    });
    (children || []).forEach((child) => {
      if (child === null || child === undefined || child === "") return;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return node;
  }
})();
