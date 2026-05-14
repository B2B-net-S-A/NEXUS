// Centralized fetch wrapper used exclusively by the background service
// worker. Handles JWT injection, silent 401 → refresh → retry, and
// normalized error envelopes.

import {
  getAuth,
  setAuth,
  clearAuth,
  getBackendUrl,
} from "./storage.js";

function buildHeaders(token, extra) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return Object.assign(headers, extra || {});
}

async function tryRefresh() {
  const auth = await getAuth();
  if (!auth || !auth.refresh_token) return false;
  const backend = await getBackendUrl();
  // /api/auth/refresh accepts refresh_token as a query param, NOT body
  // (verified in backend/app/api/auth.py:121).
  const url = `${backend}/api/auth/refresh?refresh_token=${encodeURIComponent(
    auth.refresh_token,
  )}`;
  try {
    const resp = await fetch(url, { method: "POST" });
    if (!resp.ok) return false;
    const data = await resp.json();
    await setAuth({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      email: auth.email,
    });
    return true;
  } catch (_err) {
    return false;
  }
}

/**
 * Fetch wrapper for the backend.
 *
 * @param {string} path   - API path, e.g. "/api/candidates/from-linkedin"
 * @param {object} opts   - { method, body, retry401 }
 * @returns {Promise<{ok:boolean, status?:number, data?:any, error?:string, code?:string}>}
 */
export async function apiFetch(path, opts = {}) {
  const { method = "GET", body, retry401 = true } = opts;
  const auth = await getAuth();
  const backend = await getBackendUrl();
  const url = `${backend}${path}`;
  let resp;
  try {
    resp = await fetch(url, {
      method,
      headers: buildHeaders(auth?.access_token),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    return {
      ok: false,
      error: err?.message || "Network error",
      code: "network",
    };
  }

  if (resp.status === 401 && retry401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiFetch(path, { ...opts, retry401: false });
    }
    await clearAuth();
    return { ok: false, error: "Unauthorized", code: "unauthorized", status: 401 };
  }

  let data = null;
  const text = await resp.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_err) {
      data = text;
    }
  }

  if (!resp.ok) {
    const detail =
      (data && (data.detail || data.error)) ||
      `HTTP ${resp.status}`;
    return {
      ok: false,
      error: typeof detail === "string" ? detail : JSON.stringify(detail),
      code: `http_${resp.status}`,
      status: resp.status,
      data,
    };
  }

  return { ok: true, status: resp.status, data };
}

export async function login(email, password) {
  const backend = await getBackendUrl();
  let resp;
  try {
    resp = await fetch(`${backend}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch (err) {
    return { ok: false, error: err?.message || "Network error", code: "network" };
  }
  if (!resp.ok) {
    const text = await resp.text();
    return {
      ok: false,
      error: `Login failed (HTTP ${resp.status}): ${text.slice(0, 200)}`,
      code: `http_${resp.status}`,
    };
  }
  const data = await resp.json();
  await setAuth({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    email,
  });
  return { ok: true, data };
}
