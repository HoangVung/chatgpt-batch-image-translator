"use strict";

const elements = {};
let initialized = false;

window.pocReceiveFromPython = (payload) => {
  const output = document.querySelector("#python-event-output");
  if (output) {
    output.textContent = `#${payload.id}: ${payload.message}\n${payload.source}`;
  }
};

function getSystemAppearance() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "Dark" : "Light";
}

function updateAppearance() {
  const selected = elements.themeSelect.value;
  if (selected === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.dataset.theme = selected;
  }
  elements.appearanceValue.textContent = getSystemAppearance();
  elements.themeModeValue.textContent = `Mode: ${selected[0].toUpperCase()}${selected.slice(1)}`;
}

async function callPython(method, ...args) {
  if (!window.pywebview?.api?.[method]) {
    throw new Error("pywebview API is not ready");
  }
  const response = await window.pywebview.api[method](...args);
  if (!response || response.ok !== true) {
    throw new Error(response?.error || `Python API ${method} failed`);
  }
  return response.data;
}

function showError(output, error) {
  output.textContent = `Error: ${error instanceof Error ? error.message : String(error)}`;
}

async function initializeBridge() {
  if (initialized) return;
  initialized = true;

  try {
    const state = await callPython("get_initial_state");
    const info = state.platform;
    elements.platformValue.textContent = `${info.system} ${info.release}`;
    elements.machineValue.textContent = `${info.machine} · Python ${info.python}`;
    elements.rendererValue.textContent = window.pywebview.platform || info.renderer;
    elements.frozenValue.textContent = info.frozen ? "PyInstaller frozen mode" : "Source mode";
    elements.statusBadge.textContent = "Bridge ready";
    elements.statusBadge.classList.remove("pending");
  } catch (error) {
    initialized = false;
    elements.statusBadge.textContent = "Bridge error";
    showError(elements.echoOutput, error);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  Object.assign(elements, {
    statusBadge: document.querySelector("#status-badge"),
    platformValue: document.querySelector("#platform-value"),
    machineValue: document.querySelector("#machine-value"),
    rendererValue: document.querySelector("#renderer-value"),
    frozenValue: document.querySelector("#frozen-value"),
    appearanceValue: document.querySelector("#appearance-value"),
    themeModeValue: document.querySelector("#theme-mode-value"),
    themeSelect: document.querySelector("#theme-select"),
    echoInput: document.querySelector("#echo-input"),
    echoOutput: document.querySelector("#echo-output"),
    folderOutput: document.querySelector("#folder-output"),
  });

  elements.themeSelect.addEventListener("change", updateAppearance);
  const colorScheme = window.matchMedia("(prefers-color-scheme: dark)");
  colorScheme.addEventListener?.("change", updateAppearance);
  updateAppearance();

  document.querySelector("#echo-button").addEventListener("click", async () => {
    try {
      const data = await callPython("echo", elements.echoInput.value);
      elements.echoOutput.textContent = `Python echoed: ${data.message}`;
    } catch (error) {
      showError(elements.echoOutput, error);
    }
  });

  document.querySelector("#python-js-button").addEventListener("click", async () => {
    try {
      await callPython("trigger_python_to_javascript", "Button requested this Python → JS event");
    } catch (error) {
      showError(document.querySelector("#python-event-output"), error);
    }
  });

  document.querySelector("#folder-button").addEventListener("click", async () => {
    try {
      const data = await callPython("choose_folder");
      elements.folderOutput.textContent = data.cancelled ? "Selection cancelled" : data.path;
    } catch (error) {
      showError(elements.folderOutput, error);
    }
  });

  if (window.pywebview?.api) {
    initializeBridge();
  }
});

window.addEventListener("pywebviewready", initializeBridge);
