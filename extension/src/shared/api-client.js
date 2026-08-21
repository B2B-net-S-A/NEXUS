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

/**
 * Odczytaj z backendu, które metody logowania są w tej instancji włączone.
 * Zwraca `null`, gdy endpoint nie odpowiada — wołający musi wtedy poprzestać
 * na surowym statusie HTTP.
 *
 * `/api/auth/methods` jest publiczny i NIE stoi za bramką
 * `PASSWORD_LOGIN_ENABLED`, więc działa dokładnie wtedy, gdy `/api/auth/login`
 * odmawia (backend/app/api/auth.py — handler `auth_methods`).
 */
async function fetchAuthMethods(backend) {
  try {
    const resp = await fetch(`${backend}/api/auth/methods`);
    if (!resp.ok) return null;
    return await resp.json();
  } catch (_err) {
    return null;
  }
}

/**
 * Wyciągnij `detail` z ciała odpowiedzi FastAPI.
 *
 * Wersja sprzed tej poprawki wklejała do komunikatu surowy blob
 * (`Login failed (HTTP 503): {"detail":"..."}`), który options.js renderuje
 * DOSŁOWNIE — użytkownik dostawał JSON-a zamiast zdania.
 */
function extractDetail(text) {
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail ?? parsed?.error;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (detail) return JSON.stringify(detail);
  } catch (_err) {
    // nie-JSON (np. HTML z proxy) — oddaj przycięty tekst
  }
  const trimmed = text.trim();
  return trimmed ? trimmed.slice(0, 200) : null;
}

/**
 * Zamień odpowiedź `/api/auth/login` na komunikat, z którym rekruter wie, co
 * zrobić dalej.
 *
 * Kluczowy przypadek to **503 przy `PASSWORD_LOGIN_ENABLED=false`**: na
 * produkcji jedyną drogą wejścia jest Microsoft SSO, którego ta wtyczka nie
 * obsługuje. Bez tego rozróżnienia 503 czyta się jak chwilowa awaria backendu
 * („spróbuj za chwilę") i rekruter próbuje w kółko czegoś, co nigdy nie
 * zadziała. `/api/auth/methods` odróżnia te dwa światy jednoznacznie:
 * `password:false` = bramka, brak odpowiedzi = realna niedostępność.
 *
 * @returns {{error: string, code: string}}
 */
export function describeLoginFailure(status, detail, methods) {
  if (status === 503) {
    if (methods && methods.password === false) {
      const via = methods.microsoft
        ? "Ta instancja NEXUS wpuszcza wyłącznie przez Microsoft SSO."
        : "Ta instancja NEXUS ma logowanie hasłem wyłączone.";
      return {
        code: "password_login_disabled",
        error:
          `${via} Wtyczka nie obsługuje SSO, więc logowanie e-mailem i hasłem ` +
          "nie zadziała — poproś administratora NEXUS o poświadczenie dla " +
          "wtyczki (konto serwisowe) albo dodaj swój adres do listy " +
          "break-glass.",
      };
    }
    return {
      code: "backend_unavailable",
      error:
        "Backend NEXUS jest chwilowo niedostępny (HTTP 503). Spróbuj ponownie " +
        "za kilka minut." + (detail ? ` Szczegóły: ${detail}` : ""),
    };
  }
  if (status === 401) {
    return {
      code: "invalid_credentials",
      error: "Nieprawidłowy e-mail lub hasło.",
    };
  }
  if (status === 403) {
    // 403 niesie konkretny powód (konto wyłączone / e-mail niepotwierdzony) —
    // backend zwraca go po polsku, więc przepuszczamy go bez tłumaczenia.
    return {
      code: "forbidden",
      error: detail || "Konto nie ma dostępu do NEXUS.",
    };
  }
  if (status === 429) {
    return {
      code: "rate_limited",
      error:
        "Zbyt wiele prób logowania z tej sieci. Odczekaj minutę i spróbuj " +
        "ponownie.",
    };
  }
  return {
    code: `http_${status}`,
    error:
      `Logowanie nie powiodło się (HTTP ${status}).` +
      (detail ? ` ${detail}` : ""),
  };
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
    const detail = extractDetail(await resp.text());
    // Metody logowania odpytujemy TYLKO przy porażce — logowanie na co dzień
    // udane nie ma płacić dodatkowym round-tripem.
    const methods = resp.status === 503 ? await fetchAuthMethods(backend) : null;
    const described = describeLoginFailure(resp.status, detail, methods);
    return { ok: false, status: resp.status, ...described };
  }
  const data = await resp.json();
  await setAuth({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    email,
  });
  return { ok: true, data };
}
