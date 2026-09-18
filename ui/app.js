"use strict";

const state = {
  settings: {}, controller: {}, localization: {}, language: "vi", sequence: 0,
  initialized: false, launchPending: false,
};
const pendingMessages = [];
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(method, ...args) {
  const fn = window.pywebview?.api?.[method];
  if (!fn) throw new Error("pywebview API is not ready");
  const response = await fn(...args);
  if (!response?.ok) throw new Error(response?.error || `${method} failed`);
  return response.data;
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
  if (copy) copy.textContent = text;
  else notice.textContent = text;
}

function showError(error) {
  setNoticeText(`${t("error")}: ${error?.message || error}`);
  $("#notice").classList.remove("hidden");
}

function clearError() {
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
    node.textContent = t(node.dataset.i18n);
  });
  $$('[data-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.placeholder);
  });
  renderStatus();
}

function renderSettings() {
  const settings = state.settings;
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
  $("#service-context").textContent = settings.service === "gemini" ? "Google Gemini" : "ChatGPT";
  renderAccounts();
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
  $("#account-context").textContent = state.settings.service === "chatgpt" ? active?.name || "—" : "Google Gemini";
  $("#account-context").title = $("#account-context").textContent;
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

async function save(showSavedStatus = false) {
  const data = await api("save_settings", formPayload());
  state.settings = data.settings;
  renderSettings();
  if (showSavedStatus) {
    const copy = $("#status .status-copy");
    if (copy) copy.textContent = t("saved");
  }
}

function renderStatus() {
  const status = state.controller.status || {key: "ready", params: {}};
  const copy = $("#status .status-copy");
  if (copy) copy.textContent = t(status.key, status.params);
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

  document.body.classList.toggle("is-running", running);
  $("#progress").value = percent;
  $("#progress").setAttribute("aria-valuetext", `${done} / ${total} (${Math.round(percent)}%)`);
  $("#progress-text").textContent = `${done} / ${total} (${Math.round(percent)}%)`;
  $("#manual-banner").classList.toggle("hidden", !manual);
  $("#continue").disabled = !manual;
  $("#stop").disabled = !running && !autoNext;
  $$('[data-mode]').forEach((button) => { button.disabled = running || launchPending; });
  ["account-select", "account-name", "account-add", "account-rename", "account-remove", "account-login"].forEach((id) => {
    $(`#${id}`).disabled = running || launchPending;
  });

  const runCopy = $("#run-indicator span:last-child");
  runCopy.textContent = running ? t("status_running") : t("ready");
  $("#run-indicator").classList.toggle("active", running);
  const statusEl = $("#status");
  if (statusEl) statusEl.dataset.state = manual ? "warning" : running ? "running" : "idle";
  renderStatus();
}

window.batchTranslatorReceive = (message) => {
  if (!state.initialized) {
    pendingMessages.push(message);
    return;
  }
  if (!message || message.sequence <= state.sequence) return;
  if (state.sequence && message.sequence !== state.sequence + 1) {
    setNoticeText(t("event_gap", {expected: state.sequence + 1, actual: message.sequence}));
    $("#notice").classList.remove("hidden");
  }

  state.sequence = message.sequence;
  const payload = message.payload || {};
  if (message.type === "log_appended") {
    $("#log").textContent += payload.text || "";
    $("#log").scrollTop = $("#log").scrollHeight;
  }
  if (message.type === "log_cleared") $("#log").textContent = "";
  if (message.type === "progress_changed") {
    state.controller.progress_done = payload.done;
    state.controller.progress_total = payload.total;
  }
  if (message.type === "process_started") state.controller.running = true;
  if (message.type === "process_completed") state.controller.running = false;
  if (message.type === "manual_action_required") state.controller.manual_action_required = true;
  if (message.type === "continue_sent" || message.type === "process_completed") state.controller.manual_action_required = false;
  if (message.type === "batch_result") state.controller.current_batch_result = payload.result;
  if (message.type === "status_changed") state.controller.status = payload;
  if (message.type === "auto_next_scheduled") {
    state.controller.auto_next_active = true;
    $("#auto-panel").classList.remove("hidden");
  }
  if (message.type === "auto_next_tick") {
    const remaining = payload.remaining || 0;
    const time = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
    $("#countdown").textContent = t("auto_countdown", {time});
  }
  if (message.type === "auto_next_cancelled" || message.type === "auto_next_running") {
    state.controller.auto_next_active = false;
    $("#auto-panel").classList.add("hidden");
  }
  if (message.type === "account_event" && payload.event?.event === "account_switched") {
    state.settings.active_chatgpt_account_id = payload.event.account_id;
    const account = state.settings.chatgpt_accounts.find((item) => item.id === payload.event.account_id);
    if (account) state.settings.profile_dir = account.profile_dir;
    renderSettings();
  }
  if (["bridge_error", "reader_error", "continue_error"].includes(message.type)) {
    showError(payload.error || message.type);
  }
  renderController();
};

async function initialize() {
  try {
    const initial = await api("get_initial_state");
    Object.assign(state, initial);
    state.language = initial.settings.language;
    state.sequence = initial.controller.sequence || 0;
    $("#backend").textContent = initial.capabilities.webview_backend;
    $("#log").textContent = initial.controller.log_history || "";
    renderSettings();
    renderController();
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
  $("#save").addEventListener("click", () => save(true).catch(showError));
  $$('[data-folder]').forEach((button) => button.addEventListener("click", async () => {
    try {
      const result = await api("choose_folder", button.dataset.folder);
      if (!result.cancelled) {
        $(`#${button.dataset.folder}-folder`).value = result.path;
        updatePathPresentation();
      }
    } catch (error) {
      showError(error);
    }
  }));
  $$('[data-mode]').forEach((button) => button.addEventListener("click", async () => {
    if (state.launchPending || state.controller.running) return;
    state.launchPending = true;
    renderController();
    try {
      clearError();
      await save();
      const data = await api("start_batch", button.dataset.mode);
      if (data?.state) state.controller = {...state.controller, ...data.state};
    } catch (error) {
      showError(error);
    } finally {
      state.launchPending = false;
      renderController();
    }
  }));
  $("#stop").addEventListener("click", () => api("stop_process").catch(showError));
  $("#continue").addEventListener("click", () => api("continue_manual_intervention").catch(showError));
  $("#cancel-auto").addEventListener("click", () => api("cancel_auto_next").catch(showError));
  $("#run-now").addEventListener("click", () => api("run_auto_next_now").catch(showError));
  $("#open-output").addEventListener("click", async () => {
    try {
      await api("open_output_folder");
    } catch (error) {
      showError(error);
    }
  });
  $("#copy-log").addEventListener("click", () => api("copy_log").catch(showError));
  $("#export-log").addEventListener("click", () => api("export_log").catch(showError));
  $("#clear-log").addEventListener("click", () => api("clear_log").catch(showError));
  $("#theme").addEventListener("change", async (event) => {
    setTheme(event.target.value);
    try { await save(); } catch (error) { showError(error); }
  });
  $("#language").addEventListener("change", async (event) => {
    state.language = event.target.value;
    renderText();
    try { await save(); } catch (error) { showError(error); }
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
    $("#service-context").textContent = service === "gemini" ? "Google Gemini" : "ChatGPT";
    updatePathPresentation();
  });
  $("#account-select").addEventListener("change", async (event) => {
    try {
      const data = await api("select_account", event.target.value);
      state.settings.chatgpt_accounts = data.accounts;
      state.settings.active_chatgpt_account_id = data.active_id;
      const account = data.accounts.find((item) => item.id === data.active_id);
      state.settings.profile_dir = account.profile_dir;
      renderSettings();
    } catch (error) {
      showError(error);
    }
  });
  $("#account-add").addEventListener("click", () => accountAction("add_account", null, $("#account-name").value));
  $("#account-rename").addEventListener("click", () => accountAction("rename_account", $("#account-select").value, $("#account-name").value));
  $("#account-remove").addEventListener("click", () => {
    if (confirm(t("remove"))) accountAction("remove_account", $("#account-select").value);
  });
  $("#account-login").addEventListener("click", () => api("login_account", $("#account-select").value).catch(showError));
  $$('[data-scroll-target]').forEach((button) => button.addEventListener("click", () => {
    const target = document.getElementById(button.dataset.scrollTarget);
    if (target) target.scrollIntoView({behavior: "smooth", block: "start"});
    $$('.nav').forEach((item) => item.classList.toggle("active", item === button));
  }));
  ["source-folder", "output-folder", "profile-folder"].forEach((id) => {
    $(`#${id}`).addEventListener("input", updatePathPresentation);
  });
}

async function accountAction(method, id, name) {
  try {
    const args = method === "add_account" ? [name] : method === "rename_account" ? [id, name] : [id];
    const data = await api(method, ...args);
    state.settings.chatgpt_accounts = data.accounts;
    state.settings.active_chatgpt_account_id = data.active_id;
    const account = data.accounts.find((item) => item.id === data.active_id);
    state.settings.profile_dir = account.profile_dir;
    renderSettings();
  } catch (error) {
    showError(error);
  }
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

