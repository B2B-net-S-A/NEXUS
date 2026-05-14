import { MSG, DEFAULT_BACKEND_URL } from "../shared/messages.js";

function send(payload) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(payload, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(resp || { ok: false, error: "no response" });
    });
  });
}

async function refreshAccountView() {
  const accountView = document.getElementById("account-view");
  const loginForm = document.getElementById("login-form");
  const emailEl = document.getElementById("account-email");

  const state = await send({ type: MSG.GET_AUTH_STATE });
  if (state.authed) {
    accountView.hidden = false;
    loginForm.hidden = true;
    emailEl.textContent = state.email || "(brak email)";
  } else {
    accountView.hidden = true;
    loginForm.hidden = false;
  }
}

async function refreshBackendView() {
  const input = document.getElementById("backend-url");
  const resp = await send({ type: MSG.GET_BACKEND_URL });
  input.value = (resp && resp.data && resp.data.url) || DEFAULT_BACKEND_URL;
}

function attachLogin() {
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");
  const btn = document.getElementById("btn-login");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;
    btn.disabled = true;
    btn.textContent = "Loguję…";
    const email = document.getElementById("login-email").value.trim();
    const password = document.getElementById("login-password").value;
    const resp = await send({ type: MSG.LOGIN, email, password });
    btn.disabled = false;
    btn.textContent = "Zaloguj";
    if (!resp.ok) {
      errorEl.textContent = resp.error || "Nie udało się zalogować.";
      errorEl.hidden = false;
      return;
    }
    await refreshAccountView();
    document.getElementById("login-password").value = "";
  });
}

function attachLogout() {
  document.getElementById("btn-logout").addEventListener("click", async () => {
    await send({ type: MSG.LOGOUT });
    await refreshAccountView();
  });
}

function attachBackend() {
  const form = document.getElementById("backend-form");
  const saved = document.getElementById("backend-saved");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = document.getElementById("backend-url").value.trim();
    await send({ type: MSG.SET_BACKEND_URL, url });
    saved.hidden = false;
    setTimeout(() => {
      saved.hidden = true;
    }, 1800);
  });
}

(async function init() {
  attachLogin();
  attachLogout();
  attachBackend();
  await refreshAccountView();
  await refreshBackendView();
})();
