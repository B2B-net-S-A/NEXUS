// Serwery NEXUSA i walidacja tego, co przychodzi ze strony połączenia.
// Moduł bez `chrome.*` — testowany w node.

export const SERVERS = Object.freeze({
  production: Object.freeze({
    id: "production",
    label: "Produkcja",
    frontUrl: "https://nexus.b2bnetwork.pl",
  }),
  staging: Object.freeze({
    id: "staging",
    label: "Staging na laptopie",
    frontUrl: "http://localhost:3100",
    apiBase: "http://localhost:8100",
  }),
});

export const DEFAULT_SERVER = "production";

// Te same originy co `externally_connectable.matches` w manifeście.
export const ALLOWED_FRONT_ORIGINS = Object.freeze([
  "https://nexus.b2bnetwork.pl",
  "http://localhost:3100",
  "http://localhost:3101",
]);

// Klucz ma trafić wyłącznie do hostów z `host_permissions`. Strona połączenia
// podaje `apiBase` sama, więc bez tej listy podstawiona strona mogłaby
// skierować klucz (i odczyty z LinkedIna) pod dowolny adres.
const API_HOST_RULES = [
  (u) => u.protocol === "https:" && (u.hostname === "b2bnetwork.pl" || u.hostname.endsWith(".b2bnetwork.pl")),
  (u) => u.protocol === "https:" && u.hostname === "api.nexus.dynaminds.pl",
  (u) => u.protocol === "http:" && u.hostname === "localhost" && u.port === "8100",
];

export const KEY_PATTERN = /^nxe_v1_[0-9a-f]{24}_[A-Za-z0-9_-]{32,128}$/;

function parseUrl(value) {
  if (typeof value !== "string" || !value) return null;
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/** Origin bez końcowego ukośnika albo null, gdy adres jest zły. */
export function originOf(value) {
  const u = parseUrl(value);
  return u ? u.origin : null;
}

export function isAllowedFrontOrigin(value) {
  const origin = originOf(value);
  return origin !== null && ALLOWED_FRONT_ORIGINS.includes(origin);
}

export function isAllowedApiBase(value) {
  const u = parseUrl(value);
  if (!u || u.username || u.password) return false;
  return API_HOST_RULES.some((rule) => rule(u));
}

/** `https://api.x/` i `https://api.x/api` → `https://api.x` (trasy dokładają `/api/...`). */
export function normalizeApiBase(value) {
  const u = parseUrl(value);
  if (!u) return null;
  let path = u.pathname.replace(/\/+$/, "");
  if (path.endsWith("/api")) path = path.slice(0, -4);
  return `${u.origin}${path}`;
}

export function connectUrl(frontUrl, extensionId, version) {
  const base = originOf(frontUrl) || SERVERS[DEFAULT_SERVER].frontUrl;
  const params = new URLSearchParams({ ext: extensionId, v: version });
  return `${base}/extension/connect?${params.toString()}`;
}

/**
 * Sprawdza wiadomość `nexus-extension-key` ze strony połączenia.
 * `sender` to obiekt z `chrome.runtime.onMessageExternal` (origin albo url).
 * Zwraca `{ok: true, connection}` albo `{ok: false, reason}`.
 */
export function validateKeyMessage(message, sender) {
  if (!message || typeof message !== "object" || message.type !== "nexus-extension-key") {
    return { ok: false, reason: "wrong_type" };
  }
  const senderOrigin = originOf(sender?.origin) || originOf(sender?.url);
  if (!senderOrigin || !ALLOWED_FRONT_ORIGINS.includes(senderOrigin)) {
    return { ok: false, reason: "sender_not_allowed" };
  }
  const key = typeof message.key === "string" ? message.key.trim() : "";
  if (!KEY_PATTERN.test(key)) return { ok: false, reason: "bad_key" };
  if (!isAllowedApiBase(message.apiBase)) return { ok: false, reason: "bad_api_base" };
  const frontUrl = isAllowedFrontOrigin(message.frontUrl) ? originOf(message.frontUrl) : senderOrigin;
  return {
    ok: true,
    connection: {
      key,
      apiBase: normalizeApiBase(message.apiBase),
      frontUrl,
    },
  };
}
