// `chrome.storage.local`: połączenie (klucz, adres API, adres frontu) i wybrany serwer.

import { DEFAULT_SERVER, SERVERS } from "./config.js";

const KEY_CONNECTION = "connection";
const KEY_SERVER = "server";

/** @returns {Promise<{key: string, apiBase: string, frontUrl: string, connectedAt: string} | null>} */
export async function getConnection() {
  const items = await chrome.storage.local.get(KEY_CONNECTION);
  const c = items[KEY_CONNECTION];
  return c && c.key && c.apiBase ? c : null;
}

export async function saveConnection(connection) {
  await chrome.storage.local.set({
    [KEY_CONNECTION]: { ...connection, connectedAt: new Date().toISOString() },
  });
}

export async function clearConnection() {
  await chrome.storage.local.remove(KEY_CONNECTION);
}

export async function getServerId() {
  const items = await chrome.storage.local.get(KEY_SERVER);
  return SERVERS[items[KEY_SERVER]] ? items[KEY_SERVER] : DEFAULT_SERVER;
}

export async function setServerId(id) {
  if (!SERVERS[id]) throw new Error(`Nieznany serwer: ${id}`);
  await chrome.storage.local.set({ [KEY_SERVER]: id });
}

/** Zmiana połączenia (zapis z service workera albo „Odłącz”) — panel odświeża się sam. */
export function onConnectionChanged(callback) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && KEY_CONNECTION in changes) callback(changes[KEY_CONNECTION].newValue || null);
  });
}
