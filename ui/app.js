"use strict";

let state = {
  settings: {}, controller: {}, localization: {}, language: "vi", sequence: 0,
  initialized: false, launchPending: false,
};
const sessions = new Map();
let multiSession = false;
const preferenceVersions = {theme: 0, language: 0};
const pendingMessages = [];
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

async function api(method, ...args) {
  const fn = window.pywebview?.api?.[method];
  if (!fn) throw new Error("pywebview API is not ready");
  const response = await fn(...args);
  if (!response?.ok) throw new Error(response?.error || `${method} failed`);
  return response.data;
}

function sessionApi(target, method, ...args) {
  return api(method, ...args, ...(multiSession ? [target.id] : []));
}

function captureDraft(target = state) {
  if (target !== state || !state.initialized) return;
  target.draft = formPayload();
  target.accountNameDraft = $("#account-name").value;
  target.logScroll = $("#log").scrollTop;
  renderServiceContexts();
}

function renderServiceContexts() {
  const container = $("#service-contexts");
  sessions.forEach((target, id) => {
    let row = document.getElementById(`service-${id}`);
    if (!row) {
      row = document.createElement("div");
      row.id = `service-${id}`;
      row.className = "book-service-context";
      const label = document.createElement("strong");
      label.className = "context-book";
      const pill = document.createElement("div");
      pill.className = "context-pill";
      const dot = document.createElement("span");
      dot.className = "context-dot";
      dot.setAttribute("aria-hidden", "true");
      const service = document.createElement("strong");
      service.className = "context-service";
      const account = document.createElement("p");
      account.className = "context-caption";
      if (!multiSession) {
        service.id = "service-context";
        account.id = "account-context";
      }
      pill.append(dot, service);
      row.append(label, pill, account);
      container.append(row);
    }
    const settings = {...target.settings, ...target.draft};
    const account = (settings.chatgpt_accounts || []).find(item => item.id === settings.active_chatgpt_account_id);
    const serviceName = settings.service === "gemini" ? "Google Gemini" : "ChatGPT";
    const accountName = settings.service === "gemini" ? "Google Gemini" : account?.name || "—";
    setText(row.querySelector(".context-book"), t("book_tab", {number: id.split("-").at(-1)}));
    row.querySelector(".context-book").hidden = !multiSession;
    setText(row.querySelector(".context-service"), serviceName);
    setText(row.querySelector(".context-caption"), accountName);
    row.querySelector(".context-caption").title = accountName;
    row.dataset.active = String(target === state);
  });
}

function renderTabs() {
  renderServiceContexts();
  const container = $("#workflow-tabs");
  container.classList.toggle("hidden", !multiSession);
  container.setAttribute("aria-label", t("workflow_tabs"));
  sessions.forEach((target, id) => {
    let button = document.getElementById(`tab-${id}`);
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.id = `tab-${id}`;
      button.className = "workflow-tab";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", "workflow-panel");
      button.append(document.createElement("strong"), document.createElement("small"), document.createElement("small"));
      button.addEventListener("click", () => switchSession(id));
      button.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const ids = [...sessions.keys()];
        const next = event.key === "Home" ? ids[0] : event.key === "End" ? ids.at(-1) : ids[(ids.indexOf(id) + (event.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length];
        switchSession(next);
        document.getElementById(`tab-${next}`).focus();
      });
      container.append(button);
    }
    const c = target.controller;
    const attention = !!target.error || c.manual_action_required || ["error_detail", "waiting_quota_outcome", "needs_retry_outcome"].includes(c.status?.key);
    const label = t("book_tab", {number: id.split("-").at(-1)});
    const status = attention ? t("tab_attention") : c.running ? `${t("status_running")} ${c.progress_done || 0}/${c.progress_total || 0}` : c.auto_next_active ? t("tab_waiting") : t("ready");
    setText(button.firstElementChild, label);
    const folder = c.folder_progress || {};
    const folderStatus = t("tab_folder_progress", {done: folder.done ?? "—", total: folder.total ?? "—"});
    setText(button.children[1], status);
    setText(button.lastElementChild, folderStatus);
    button.title = `${label}: ${status}\n${folderStatus}\n${target.settings.image_folder || ""}`;
    button.setAttribute("aria-selected", String(target === state));
    button.tabIndex = target === state ? 0 : -1;
    button.dataset.attention = String(attention);
  });
  if (state.id) $("#workflow-panel").setAttribute("aria-labelledby", `tab-${state.id}`);
}

function renderSession() {
  renderSettings();
  setText($("#log"), state.controller.log_history || "");
  $("#log").scrollTop = state.logScroll ?? $("#log").scrollHeight;
  setNoticeText(state.error || "");
  $("#notice").classList.toggle("hidden", !state.error);
}

function switchSession(id) {
  if (!sessions.has(id) || state.id === id) return;
  captureDraft();
  state = sessions.get(id);
  renderSession();
}

function acceptSnapshot(target, snapshot) {
  if (!snapshot || (snapshot.sequence || 0) < target.sequence) return;
  const previousLog = target.controller.log_history || "";
  target.controller = {...snapshot};
  target.sequence = snapshot.sequence || 0;
  const nextLog = target.controller.log_history || "";
  if (nextLog !== previousLog) {
    const appended = nextLog.startsWith(previousLog);
    updateLog(target, appended ? nextLog.slice(previousLog.length) : nextLog, !appended);
  }
}

function updateLog(target, text, clear = false) {
  if (target !== state) {
    if (clear) target.logScroll = 0;
    return;
  }
  const log = $("#log");
  const followTail = log.scrollHeight - log.clientHeight - log.scrollTop <= 2;
  // Keep existing text nodes (and selections) intact as worker output arrives.
  if (clear) log.replaceChildren();
  if (text) log.append(document.createTextNode(text));
  if (clear || followTail) log.scrollTop = log.scrollHeight;
  target.logScroll = log.scrollTop;
}

async function refreshSession(target) {
  if (target.refreshing) return;
  target.refreshing = true;
  try {
    const initial = await sessionApi(target, "get_initial_state");
    if ((initial.controller.sequence || 0) >= target.sequence) {
      target.settings = initial.settings;
      acceptSnapshot(target, initial.controller);
      if (target === state) renderSession();
    }
  } catch (error) { showError(error, target); }
  finally { target.refreshing = false; renderTabs(); }
}

function t(key, params = {}) {
  let value = state.localization[state.language]?.[key] || state.localization.vi?.[key] || key;
  Object.entries(params).forEach(([name, replacement]) => {
    value = value.replace(`{${name}}`, replacement);
  });
  return value;
}

function setNoticeText(text) {
  const notice = $("#notice");
  const copy = notice.querySelector(".notice-copy");
  if (copy) setText(copy, text);
  else setText(notice, text);
}

function showError(error, target = state) {
  target.error = `${t("error")}: ${error?.message || error}`;
  if (target === state) {
    setNoticeText(target.error);
    $("#notice").classList.remove("hidden");
  }
  renderTabs();
}

function clearError() {
  state.error = "";
  $("#notice").classList.add("hidden");
}

function setTheme(theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
}

function updatePathPresentation() {
  ["source-folder", "output-folder", "profile-folder"].forEach((id) => {
    const input = $(`#${id}`);
    input.title = input.value || "";
    input.classList.toggle("is-empty", !input.value.trim());
  });
}

function renderText() {
  document.documentElement.lang = state.language;
  $$('[data-i18n]').forEach((node) => {
    setText(node, t(node.dataset.i18n));
  });
  $$('.batch-dock [data-full-label]').forEach((button) => {
    button.title = t(button.dataset.fullLabel);
    button.setAttribute("aria-label", button.title);
  });
  $$('[data-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.placeholder);
  });
  renderController();
}

function renderSettings() {
  const settings = {...state.settings, ...state.draft};
  $("#service").value = settings.service;
  $("#batch-size").value = settings.batch_size;
  $("#start-from").value = settings.start_from;
  $("#source-folder").value = settings.image_folder;
  $("#output-folder").value = settings.download_folder;
  $("#profile-folder").value = settings.profile_dir;
  $("#fallback").checked = !!settings.auto_account_fallback_enabled;
  $("#auto-next").checked = !!settings.auto_next_enabled;
  $("#auto-delay").value = settings.auto_next_delay_minutes;
  $("#language").value = settings.language;
  $("#theme").value = settings.theme;
  state.language = settings.language;
  setTheme(settings.theme);
  $("#accounts-card").classList.toggle("hidden", settings.service !== "chatgpt");
  renderAccounts();
  if (state.accountNameDraft !== undefined) $("#account-name").value = state.accountNameDraft;
  updatePathPresentation();
  renderText();
}

function renderAccounts() {
  const accounts = state.settings.chatgpt_accounts || [];
  const select = $("#account-select");
  select.replaceChildren();
  accounts.forEach((account) => {
    const option = document.createElement("option");
    option.value = account.id;
    option.textContent = account.name;
    option.selected = account.id === state.settings.active_chatgpt_account_id;
    select.append(option);
  });
  const active = accounts.find((item) => item.id === select.value);
  $("#account-name").value = active?.name || "";
  renderServiceContexts();
  $("#account-count").textContent = String(accounts.length);
}

function formPayload() {
  return {
    image_folder: $("#source-folder").value,
    download_folder: $("#output-folder").value,
    profile_dir: $("#profile-folder").value,
    batch_size: $("#batch-size").value,
    start_from: $("#start-from").value,
    auto_next_enabled: $("#auto-next").checked,
    auto_next_delay_minutes: $("#auto-delay").value,
    auto_account_fallback_enabled: $("#fallback").checked,
    service: $("#service").value,
    theme: $("#theme").value,
    language: $("#language").value,
  };
}

async function save(showSavedStatus = false, target = state) {
  captureDraft(target);
  const payload = {...(target.draft || target.settings)};
  const data = await sessionApi(target, "save_settings", payload);
  target.settings = data.settings;
  if (JSON.stringify(target.draft) === JSON.stringify(payload)) target.draft = null;
  if (target === state) renderSettings();
  if (showSavedStatus && target === state) {
    const copy = $("#status .status-copy");
    if (copy) copy.textContent = t("saved");
  }
}

function renderStatus() {
  const status = state.controller.status || {key: "ready", params: {}};
  const copy = $("#status .status-copy");
  if (copy) setText(copy, t(status.key, status.params));
}

function renderController() {
  const controller = state.controller;
  const done = controller.progress_done || 0;
  const total = controller.progress_total || 0;
  const percent = total ? done / total * 100 : 0;
  const running = !!controller.running;
  const launchPending = !!state.launchPending;
  const manual = !!controller.manual_action_required;
  const autoNext = !!controller.auto_next_active;
  setText($("#active-book"), t("book_tab", {number: state.id?.split("-").at(-1) || 1}));
  $("#auto-panel").classList.toggle("hidden", !autoNext);
  const remaining = state.remaining || 0;
  const time = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
  setText($("#countdown"), controller.status?.key === "auto_countdown" ? t("auto_countdown", controller.status.params) : t("auto_countdown", {time}));
  $("#confirm-output").disabled = running || autoNext || launchPending;
  $$('#configuration-card input, #configuration-card select, #configuration-card button').forEach((node) => { node.disabled = running || launchPending; });
  $("#confirm-output").disabled = running || autoNext || launchPending;

  document.body.classList.toggle("is-running", running);
  $("#progress").value = percent;
  $("#progress").setAttribute("aria-valuetext", `${done} / ${total} (${Math.round(percent)}%)`);
  setText($("#progress-text"), `${done} / ${total} (${Math.round(percent)}%)`);
  $("#manual-banner").classList.toggle("hidden", !manual);
  $("#continue").disabled = !manual;
  $("#stop").disabled = !running && !autoNext;
  $$('[data-mode]').forEach((button) => { button.disabled = running || launchPending; });
  ["account-select", "account-name", "account-add", "account-rename", "account-remove", "account-login"].forEach((id) => {
    $(`#${id}`).disabled = running || launchPending;
  });

  const runCopy = $("#run-indicator span:last-child");
  setText(runCopy, manual ? t("tab_attention") : running ? t("status_running") : autoNext ? t("tab_waiting") : t(controller.status?.key || "ready", controller.status?.params));
  $("#run-indicator").classList.toggle("active", running);
  $("#run-indicator").title = t(controller.status?.key || "ready", controller.status?.params);
  const statusEl = $("#status");
  if (statusEl) statusEl.dataset.state = manual ? "warning" : running ? "running" : "idle";
  renderStatus();
  renderTabs();
}

window.batchTranslatorReceive = (message) => {
  if (!state.initialized) {
    pendingMessages.push(message);
    return;
  }
  const target = sessions.get(message?.session_id || "book-1");
  if (!target || !message || message.sequence <= target.sequence) return;
  if (target.sequence && message.sequence !== target.sequence + 1) {
    showError(t("event_gap", {expected: target.sequence + 1, actual: message.sequence}), target);
    refreshSession(target);
  }
  target.sequence = message.sequence;
  target.controller.sequence = message.sequence;
  if (message.run_id) target.controller.run_id = message.run_id;
  const payload = message.payload || {};
  if (message.type === "log_appended" || message.type === "log_cleared") {
    const clear = message.type === "log_cleared";
    const text = clear ? "" : payload.text || "";
    target.controller.log_history = clear ? "" : (target.controller.log_history || "") + text;
    updateLog(target, text, clear);
    // Logs do not change controls, tabs, accounts, or progress.
    return;
  }
  if (message.type === "progress_changed") {
    target.controller.progress_done = payload.done;
    target.controller.progress_total = payload.total;
  }
  if (message.type === "folder_progress_changed") target.controller.folder_progress = payload;
  if (message.type === "process_started") target.controller.running = true;
  if (message.type === "process_completed") target.controller.running = false;
  if (message.type === "manual_action_required") target.controller.manual_action_required = true;
  if (message.type === "continue_sent" || message.type === "process_completed") target.controller.manual_action_required = false;
  if (message.type === "batch_result") target.controller.current_batch_result = payload.result;
  if (message.type === "status_changed") target.controller.status = payload;
  if (message.type === "auto_next_scheduled") {
    target.controller.auto_next_active = true;
  }
  if (message.type === "auto_next_tick") {
    target.remaining = payload.remaining || 0;
  }
  if (message.type === "auto_next_cancelled" || message.type === "auto_next_running") {
    target.controller.auto_next_active = false;
  }
  if (message.type === "account_event" && payload.event?.event === "account_switched") {
    target.settings.active_chatgpt_account_id = payload.event.account_id;
    const account = target.settings.chatgpt_accounts.find((item) => item.id === payload.event.account_id);
    if (account) {
      target.settings.profile_dir = account.profile_dir;
      if (target.draft) target.draft.profile_dir = account.profile_dir;
    }
    delete target.accountNameDraft;
    if (target === state) renderSettings();
  }
  if (message.type === "preferences_changed") {
    sessions.forEach((item) => {
      Object.assign(item.settings, payload);
      if (item.draft) Object.assign(item.draft, payload);
      if (payload.language) item.language = payload.language;
    });
    renderSettings();
  }
  if (["bridge_error", "reader_error", "continue_error"].includes(message.type)) {
    showError(payload.error || message.type, target);
  }
  if (target === state) {
    renderController();
  } else renderTabs();
};

async function initialize() {
  try {
    const initial = await api("get_initial_state");
    multiSession = !!initial.sessions;
    Object.entries(initial.sessions || {"book-1": initial}).forEach(([id, item]) => {
      sessions.set(id, {...item, id, localization: initial.localization, language: initial.settings.language,
        sequence: item.controller.sequence || 0, initialized: true, launchPending: false});
    });
    state = sessions.get(initial.active_session_id || "book-1");
    $("#backend").textContent = initial.capabilities.webview_backend;
    renderSession();
    bind();
    state.initialized = true;
    pendingMessages
      .splice(0)
      .sort((left, right) => (left?.sequence || 0) - (right?.sequence || 0))
      .forEach((message) => window.batchTranslatorReceive(message));
  } catch (error) {
    showError(error);
  }
}

function bind() {
  $("#save").addEventListener("click", () => {
    const target = state;
    save(true, target).catch((error) => showError(error, target));
  });
  $$('[data-folder]').forEach((button) => button.addEventListener("click", async () => {
    const target = state;
    captureDraft(target);
    try {
      const result = await sessionApi(target, "choose_folder", button.dataset.folder);
      if (!result.cancelled) {
        const key = {source: "image_folder", output: "download_folder", profile: "profile_dir"}[button.dataset.folder];
        target.draft = {...(target.draft || {}), [key]: result.path};
        if (target === state) renderSettings();
      }
    } catch (error) {
      showError(error, target);
    }
  }));
  $$('[data-mode]').forEach((button) => button.addEventListener("click", async () => {
    const target = state;
    if (target.launchPending || target.controller.running) return;
    captureDraft(target);
    target.launchPending = true;
    renderController();
    try {
      clearError();
      await save(false, target);
      const data = await sessionApi(target, "start_batch", button.dataset.mode);
      if (data?.state) acceptSnapshot(target, data.state);
    } catch (error) {
      showError(error, target);
    } finally {
      target.launchPending = false;
      renderController();
    }
  }));
  Object.entries({stop: "stop_process", continue: "continue_manual_intervention", "cancel-auto": "cancel_auto_next",
    "run-now": "run_auto_next_now", "open-output": "open_output_folder", "copy-log": "copy_log", "export-log": "export_log", "clear-log": "clear_log"}).forEach(([id, method]) => {
    $(`#${id}`).addEventListener("click", async () => {
      const target = state;
      try {
        const data = await sessionApi(target, method);
        if (data.state) acceptSnapshot(target, data.state);
        if (target === state) renderController();
      } catch (error) { showError(error, target); }
    });
  });
  $("#confirm-output").addEventListener("click", async () => {
    const target = state;
    captureDraft(target);
    if (!confirm(`${t("confirm_output_question")}\n\n${target.draft.image_folder}\n→ ${target.draft.download_folder}`)) return;
    target.launchPending = true;
    renderController();
    try {
      await save(false, target);
      await sessionApi(target, "confirm_existing_output");
      target.error = "";
      if (target === state) { setNoticeText(t("output_confirmed")); $("#notice").classList.remove("hidden"); }
    } catch (error) { showError(error, target); }
    finally { target.launchPending = false; renderController(); }
  });
  $("#theme").addEventListener("change", async (event) => {
    const theme = event.target.value;
    const version = ++preferenceVersions.theme;
    setTheme(theme);
    try {
      await api("set_theme", theme);
      if (version === preferenceVersions.theme) {
        sessions.forEach((target) => { target.settings.theme = theme; if (target.draft) target.draft.theme = theme; });
      }
    } catch (error) { showError(error); }
  });
  $("#language").addEventListener("change", async (event) => {
    const version = ++preferenceVersions.language;
    state.language = event.target.value;
    renderText();
    try {
      const language = event.target.value;
      await api("set_language", language);
      if (version === preferenceVersions.language) {
        sessions.forEach((target) => { target.settings.language = language; target.language = language; if (target.draft) target.draft.language = language; });
      }
      renderTabs();
    } catch (error) { showError(error); }
  });
  $("#service").addEventListener("change", () => {
    const service = $("#service").value;
    if (service === "chatgpt") {
      const active = state.settings.chatgpt_accounts.find((item) => item.id === state.settings.active_chatgpt_account_id);
      if (active) $("#profile-folder").value = active.profile_dir;
    } else {
      $("#profile-folder").value = state.settings.gemini_profile_dir;
    }
    $("#accounts-card").classList.toggle("hidden", service !== "chatgpt");
    captureDraft();
    updatePathPresentation();
  });
  $("#account-select").addEventListener("change", (event) => accountAction("select_account", event.target.value));
  $("#account-add").addEventListener("click", () => accountAction("add_account", null, $("#account-name").value));
  $("#account-rename").addEventListener("click", () => accountAction("rename_account", $("#account-select").value, $("#account-name").value));
  $("#account-remove").addEventListener("click", () => {
    if (confirm(t("remove"))) accountAction("remove_account", $("#account-select").value);
  });
  $("#account-login").addEventListener("click", async () => {
    const target = state;
    const accountId = $("#account-select").value;
    target.launchPending = true;
    renderController();
    try {
      const data = await sessionApi(target, "login_account", accountId);
      acceptSnapshot(target, data.state);
    } catch (error) { showError(error, target); }
    finally { target.launchPending = false; renderController(); }
  });
  // Keep navigation and keyboard focus below the pinned header as text wraps.
  const workspaceHeader = $(".workspace-header");
  const updateDockPosition = () => {
    const bounds = workspaceHeader.getBoundingClientRect();
    document.documentElement.style.setProperty("--batch-dock-center-x", `${bounds.left + bounds.width / 2}px`);
    document.documentElement.style.setProperty("--batch-dock-available-width", `${Math.max(0, bounds.width - 24)}px`);
  };
  const headerObserver = new ResizeObserver(() => {
    const offset = workspaceHeader.getBoundingClientRect().height + $(".titlebar").getBoundingClientRect().height + 12;
    document.documentElement.style.setProperty("--workspace-scroll-offset", `${offset}px`);
    updateDockPosition();
  });
  headerObserver.observe(workspaceHeader);
  headerObserver.observe($(".titlebar"));
  window.addEventListener("resize", updateDockPosition);
  updateDockPosition();
  const batchDock = $(".batch-dock");
  const updateDockHeight = () => {
    document.documentElement.style.setProperty("--batch-dock-height", `${Math.ceil(batchDock.getBoundingClientRect().height)}px`);
  };
  const dockObserver = new ResizeObserver(updateDockHeight);
  dockObserver.observe(batchDock, {box: "border-box"});
  updateDockHeight();
  $$('[data-scroll-target]').forEach((button) => button.addEventListener("click", () => {
    const target = document.getElementById(button.dataset.scrollTarget);
    if (target) target.scrollIntoView({behavior: "smooth", block: "start"});
    $$('.nav').forEach((item) => item.classList.toggle("active", item === button));
  }));
  ["source-folder", "output-folder", "profile-folder"].forEach((id) => {
    $(`#${id}`).addEventListener("input", updatePathPresentation);
  });
  $$('#configuration-card input, #configuration-card select, #account-name').forEach((node) => {
    node.addEventListener("input", () => captureDraft());
    node.addEventListener("change", () => captureDraft());
  });
}

async function accountAction(method, id, name) {
  const target = state;
  captureDraft(target);
  target.launchPending = true;
  renderController();
  try {
    const args = method === "add_account" ? [name] : method === "rename_account" ? [id, name] : [id];
    const data = await sessionApi(target, method, ...args);
    target.settings.chatgpt_accounts = data.accounts;
    target.settings.active_chatgpt_account_id = data.active_id;
    const account = data.accounts.find((item) => item.id === data.active_id);
    target.settings.profile_dir = account.profile_dir;
    if (target.draft) target.draft.profile_dir = account.profile_dir;
    delete target.accountNameDraft;
    if (target === state) renderSettings();
  } catch (error) {
    showError(error, target);
  }
  finally { target.launchPending = false; renderController(); renderServiceContexts(); }
}

if (window.pywebview?.api) initialize();
else window.addEventListener("pywebviewready", initialize, {once: true});

/* =====================================================================
 * Mac OS Aqua Pass — traffic-light chrome + drag-region hints
 * ===================================================================== */

/* Detect whether we are running inside the pywebview shell. When opened in
   a regular browser (dev preview, tests), we hide the custom titlebar via a
   body class so the page still looks correct. */
function applyChromeEnvironment() {
  const inWebview = !!(window.pywebview?.api);
  document.body.classList.toggle("in-webview", inWebview);
  document.body.classList.toggle("no-custom-chrome", !inWebview);
}

applyChromeEnvironment();
window.addEventListener("pywebviewready", applyChromeEnvironment, {once: true});

/* Prevent pywebview easy_drag from hijacking clicks on window controls and interactive elements */
document.addEventListener("mousedown", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  if (target.closest('[data-window-drag="no"], button, input, select, textarea, label')) {
    event.stopPropagation();
  }
}, true);

function updateMaximizeState(isMax) {
  document.body.classList.toggle("is-maximized", Boolean(isMax));
  const zoom = document.querySelector('[data-action="toggle-maximize-window"]');
  if (zoom) {
    zoom.setAttribute("aria-label", isMax ? "Restore window" : "Maximize window");
    zoom.title = isMax ? "Khôi phục" : "Phóng to";
  }
}

/* easy_drag only handles mouse events. Capture touch/pen on the titlebar and
   use screen coordinates so moving the window cannot feed back into deltas. */
const titlebar = $(".titlebar");
let chromeDrag = null;
let pendingWindowPosition = null;
let movingWindow = false;

async function flushWindowPosition() {
  if (movingWindow) return;
  movingWindow = true;
  try {
    // Coalesce moves while the native bridge is busy; never reorder positions.
    while (pendingWindowPosition) {
      const position = pendingWindowPosition;
      pendingWindowPosition = null;
      await api("move_window", position.x, position.y);
    }
  } catch (error) {
    pendingWindowPosition = null;
    console.error("Window drag failed:", error);
  } finally {
    movingWindow = false;
  }
}

titlebar.addEventListener("pointerdown", (event) => {
  if (!["touch", "pen"].includes(event.pointerType) || !event.isPrimary || chromeDrag) return;
  if (event.target.closest('[data-window-drag="no"], button, input, select, textarea, label')) return;
  if (!window.pywebview?.api?.move_window || document.body.classList.contains("is-maximized")) return;
  titlebar.setPointerCapture(event.pointerId);
  chromeDrag = {id: event.pointerId, x: event.clientX, y: event.clientY,
    startX: event.screenX, startY: event.screenY, moved: false};
  event.preventDefault(); // Suppress compatibility mouse events and duplicate easy_drag.
});

function moveChromePointer(event) {
  if (!chromeDrag || chromeDrag.id !== event.pointerId) return;
  event.preventDefault();
  if (!chromeDrag.moved && Math.hypot(event.screenX - chromeDrag.startX, event.screenY - chromeDrag.startY) < 4) return;
  chromeDrag.moved = true;
  pendingWindowPosition = {x: Math.round(event.screenX - chromeDrag.x),
    y: Math.round(event.screenY - chromeDrag.y)};
  void flushWindowPosition();
}
titlebar.addEventListener("pointermove", moveChromePointer);
titlebar.addEventListener("pointerup", (event) => {
  if (!chromeDrag || chromeDrag.id !== event.pointerId) return;
  moveChromePointer(event);
  chromeDrag = null;
  if (titlebar.hasPointerCapture(event.pointerId)) titlebar.releasePointerCapture(event.pointerId);
});
function cancelChromeDrag(event) {
  if (event && chromeDrag?.id !== event.pointerId) return;
  chromeDrag = null;
  pendingWindowPosition = null;
}
titlebar.addEventListener("pointercancel", cancelChromeDrag);
titlebar.addEventListener("lostpointercapture", cancelChromeDrag);
window.addEventListener("blur", () => cancelChromeDrag());
titlebar.addEventListener("contextmenu", (event) => {
  if (!event.target.closest('[data-window-drag="no"]')) event.preventDefault();
});

async function handleWindowAction(action) {
  try {
    if (action === "minimize-window") {
      await api("minimize_window");
    } else if (action === "toggle-maximize-window") {
      const res = await api("toggle_maximize_window");
      if (res && typeof res.maximized === "boolean") {
        updateMaximizeState(res.maximized);
      }
    } else if (action === "close-window") {
      await api("close_window");
    }
  } catch (error) {
    console.error(`Window action "${action}" failed:`, error);
  }
}

document.addEventListener("click", (event) => {
  const target = event.target instanceof Element
    ? event.target.closest("[data-action]")
    : null;
  if (!target) return;
  event.preventDefault();
  event.stopPropagation();
  handleWindowAction(target.dataset.action);
});

/* Double-clicking the titlebar toggles maximize/restore (native OS behavior) */
document.addEventListener("dblclick", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  if (target.closest('[data-window-drag="no"], button, input, select, textarea')) return;
  if (target.closest(".titlebar")) {
    handleWindowAction("toggle-maximize-window");
  }
});

/* When pywebview is ready, initialize window control attributes. */
window.addEventListener("pywebviewready", () => {
  const zoom = document.querySelector('[data-action="toggle-maximize-window"]');
  if (!zoom) return;
  zoom.setAttribute("aria-label", "Maximize window");
  zoom.title = "Phóng to";
});

