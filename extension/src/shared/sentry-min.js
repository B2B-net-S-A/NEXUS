// Minimal Sentry client for the NEXUS extension — bundled, zero deps,
// MV3-CSP-safe (no remote script load, no eval).
//
// Why not the official @sentry/browser SDK?
//   1. MV3 service workers run with strict CSP — `<script src="https://...">`
//      and `eval` are blocked. The full SDK has tree-shaking-resistant code
//      paths that hit those.
//   2. We need ~5% of the SDK surface (captureException, captureMessage,
//      user context, tags). Hand-rolling stays ~120 lines vs 50 KB bundle.
//   3. No build step. Zero dependencies.
//
// Sends Sentry events via the Store API:
//   POST https://<orgId>.ingest.sentry.io/api/<projectId>/store/
//   Header X-Sentry-Auth: Sentry sentry_version=7, sentry_key=<publicKey>,
//          sentry_client=nexus-extension/<version>
//
// Disabled unless a DSN is configured in chrome.storage (the options page
// has a field for it).

import { getAuth } from "./storage.js";

const KEY_DSN = "sentry_dsn";
const KEY_DSN_ENABLED = "sentry_enabled";

let cachedDsn = null;
let cachedEnabled = null;
let cachedContext = {};

function get(keys) {
  return new Promise((resolve) =>
    chrome.storage.local.get(keys, (items) => resolve(items)),
  );
}

function set(items) {
  return new Promise((resolve) =>
    chrome.storage.local.set(items, () => resolve()),
  );
}

export async function getSentryDsn() {
  if (cachedDsn !== null) return cachedDsn;
  const items = await get([KEY_DSN]);
  cachedDsn = items[KEY_DSN] || "";
  return cachedDsn;
}

export async function setSentryDsn(dsn) {
  cachedDsn = (dsn || "").trim();
  await set({ [KEY_DSN]: cachedDsn });
}

export async function isSentryEnabled() {
  if (cachedEnabled !== null) return cachedEnabled;
  const items = await get([KEY_DSN_ENABLED]);
  cachedEnabled = items[KEY_DSN_ENABLED] !== false; // default: true
  return cachedEnabled;
}

export async function setSentryEnabled(on) {
  cachedEnabled = !!on;
  await set({ [KEY_DSN_ENABLED]: cachedEnabled });
}

export function setContext(ctx) {
  cachedContext = Object.assign({}, cachedContext, ctx || {});
}

function parseDsn(dsn) {
  // DSN format: https://<publicKey>@<orgId>.ingest.sentry.io/<projectId>
  try {
    const u = new URL(dsn);
    const publicKey = u.username;
    const projectId = u.pathname.replace(/^\/+/, "");
    const storeUrl = `${u.protocol}//${u.host}/api/${projectId}/store/`;
    return { publicKey, projectId, storeUrl };
  } catch (_err) {
    return null;
  }
}

function uuid4() {
  // RFC4122-ish — Sentry only needs a 32-char hex event_id.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  // version + variant bits
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function parseStack(err) {
  if (!err || !err.stack) return null;
  const lines = String(err.stack).split("\n").slice(1, 30);
  return {
    frames: lines.map((raw) => {
      const m = raw.match(/at\s+(?:(.*?)\s+\()?(.+?):(\d+):(\d+)\)?$/);
      if (!m) return { function: raw.trim() };
      return {
        function: m[1] || "?",
        filename: m[2],
        lineno: Number(m[3]),
        colno: Number(m[4]),
        in_app: true,
      };
    }),
  };
}

async function buildEnvelope(payload) {
  const dsn = await getSentryDsn();
  if (!dsn) return null;
  if (!(await isSentryEnabled())) return null;
  const parsed = parseDsn(dsn);
  if (!parsed) return null;
  const auth = await getAuth().catch(() => null);
  const event = {
    event_id: uuid4(),
    timestamp: Math.floor(Date.now() / 1000),
    platform: "javascript",
    sdk: { name: "nexus-extension-min", version: "0.2.0" },
    environment: "production",
    release: chrome.runtime.getManifest().version,
    user: auth?.email ? { email: auth.email } : undefined,
    tags: Object.assign(
      { extension_version: chrome.runtime.getManifest().version },
      cachedContext.tags || {},
    ),
    extra: cachedContext.extra || {},
    ...payload,
  };
  return { event, parsed };
}

async function send(envelope) {
  if (!envelope) return;
  const { event, parsed } = envelope;
  const auth = `Sentry sentry_version=7, sentry_key=${parsed.publicKey}, sentry_client=nexus-extension-min/0.2.0`;
  try {
    await fetch(parsed.storeUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Sentry-Auth": auth,
      },
      body: JSON.stringify(event),
    });
  } catch (_err) {
    // Swallow — never throw out of a Sentry call (would mask the original error).
  }
}

export async function captureException(err, ctx) {
  const envelope = await buildEnvelope({
    level: "error",
    exception: {
      values: [
        {
          type: err?.name || "Error",
          value: String(err?.message || err || "(no message)"),
          stacktrace: parseStack(err),
        },
      ],
    },
    extra: Object.assign({}, cachedContext.extra || {}, ctx || {}),
  });
  await send(envelope);
}

export async function captureMessage(message, level = "info", ctx) {
  const envelope = await buildEnvelope({
    level,
    message: { formatted: String(message) },
    extra: Object.assign({}, cachedContext.extra || {}, ctx || {}),
  });
  await send(envelope);
}
