// NEXUS extension background service worker.
//
// Manifest V3 service workers are short-lived (~30s idle eviction). Every
// handler reads state from chrome.storage on entry — we never cache in
// module scope, otherwise reload between events breaks.

import { MSG } from "../shared/messages.js";
import {
  getAuth,
  clearAuth,
  getBackendUrl,
  setBackendUrl,
  getFrontendUrl,
} from "../shared/storage.js";
import { apiFetch, login } from "../shared/api-client.js";

// ── Toolbar icon → open options page (no popup) ─────────────────────────────
chrome.action.onClicked.addListener(() => {
  chrome.runtime.openOptionsPage();
});

// ── Broadcast auth changes to all open linkedin.com tabs ────────────────────
async function broadcastAuthChanged(authed) {
  const tabs = await chrome.tabs.query({ url: "https://www.linkedin.com/*" });
  for (const tab of tabs) {
    if (tab.id !== undefined) {
      try {
        await chrome.tabs.sendMessage(tab.id, {
          type: MSG.AUTH_CHANGED,
          authed,
        });
      } catch (_err) {
        // tab might not have the content script loaded — ignore
      }
    }
  }
}

// ── Message dispatcher ──────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // Wrap async handler to keep the message channel open until resolve.
  handleMessage(msg)
    .then((reply) => sendResponse(reply))
    .catch((err) => {
      console.error("[NEXUS-BG] handler error", err);
      sendResponse({
        ok: false,
        error: err?.message || "Internal error",
        code: "internal",
      });
    });
  return true; // keep channel open
});

async function handleMessage(msg) {
  switch (msg?.type) {
    case MSG.GET_AUTH_STATE:
      return handleGetAuthState();
    case MSG.LOGIN:
      return handleLogin(msg.email, msg.password);
    case MSG.LOGOUT:
      return handleLogout();
    case MSG.GET_BACKEND_URL:
      return { ok: true, data: { url: await getBackendUrl() } };
    case MSG.SET_BACKEND_URL:
      await setBackendUrl(msg.url);
      return { ok: true };
    case MSG.SEARCH_JOBS:
      return handleSearchJobs(msg.q);
    case MSG.ADD_CANDIDATE:
      return handleAddCandidate(msg.payload);
    case MSG.SYNC_LINKEDIN:
      return handleSyncLinkedin(msg.candidate_id);
    case MSG.OPEN_OPTIONS:
      chrome.runtime.openOptionsPage();
      return { ok: true };
    default:
      return { ok: false, error: "Unknown message type", code: "bad_request" };
  }
}

async function handleGetAuthState() {
  const auth = await getAuth();
  return {
    ok: true,
    authed: !!auth?.access_token,
    email: auth?.email || null,
  };
}

async function handleLogin(email, password) {
  const result = await login(email, password);
  if (result.ok) {
    await broadcastAuthChanged(true);
  }
  return result;
}

async function handleLogout() {
  await clearAuth();
  await broadcastAuthChanged(false);
  return { ok: true };
}

async function handleSearchJobs(q) {
  const params = new URLSearchParams({
    status: "published",
    page_size: "20",
  });
  if (q) params.append("q", q);
  const resp = await apiFetch(`/api/jobs?${params.toString()}`);
  if (!resp.ok) return resp;
  const items = (resp.data?.items || []).map((j) => ({
    id: j.id,
    title: j.title,
    client_name: j.client_name || j.client?.name || null,
  }));
  return { ok: true, items };
}

async function handleAddCandidate(payload) {
  if (!payload || !payload.linkedin_url) {
    return { ok: false, error: "Missing linkedin_url", code: "bad_request" };
  }
  const resp = await apiFetch("/api/candidates/from-linkedin", {
    method: "POST",
    body: payload,
  });
  if (!resp.ok) return resp;
  const frontendBase = await getFrontendUrl();
  const candidate = resp.data;
  return {
    ok: true,
    action: candidate.action,
    candidate,
    frontend_url: `${frontendBase}${candidate.profile_url_path}`,
    status: resp.status,
  };
}

async function handleSyncLinkedin(candidateId) {
  if (!candidateId) {
    return { ok: false, error: "Missing candidate_id", code: "bad_request" };
  }
  const resp = await apiFetch(
    `/api/candidates/${candidateId}/sync-linkedin`,
    { method: "POST" },
  );
  if (!resp.ok) return resp;
  return { ok: true, data: resp.data };
}
