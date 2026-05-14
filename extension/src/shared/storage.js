// Thin Promise-based wrappers around chrome.storage.local. The service
// worker, options page, and content script (via the SW) all share state
// through this module.

import { DEFAULT_BACKEND_URL, DEFAULT_FRONTEND_URL } from "./messages.js";

const KEY_AUTH = "auth"; // { access_token, refresh_token, email }
const KEY_BACKEND = "backend_url";
const KEY_FRONTEND = "frontend_url";

function get(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, (items) => resolve(items));
  });
}

function set(items) {
  return new Promise((resolve) => {
    chrome.storage.local.set(items, () => resolve());
  });
}

function remove(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.remove(keys, () => resolve());
  });
}

export async function getAuth() {
  const items = await get([KEY_AUTH]);
  return items[KEY_AUTH] || null;
}

export async function setAuth(auth) {
  await set({ [KEY_AUTH]: auth });
}

export async function clearAuth() {
  await remove([KEY_AUTH]);
}

export async function getBackendUrl() {
  const items = await get([KEY_BACKEND]);
  return items[KEY_BACKEND] || DEFAULT_BACKEND_URL;
}

export async function setBackendUrl(url) {
  // Strip trailing slash to keep path joining predictable.
  const cleaned = (url || "").trim().replace(/\/+$/, "");
  await set({ [KEY_BACKEND]: cleaned || DEFAULT_BACKEND_URL });
}

export async function getFrontendUrl() {
  const items = await get([KEY_FRONTEND]);
  return items[KEY_FRONTEND] || DEFAULT_FRONTEND_URL;
}

export async function setFrontendUrl(url) {
  const cleaned = (url || "").trim().replace(/\/+$/, "");
  await set({ [KEY_FRONTEND]: cleaned || DEFAULT_FRONTEND_URL });
}
