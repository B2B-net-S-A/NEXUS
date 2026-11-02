// `chrome.storage.local`: połączenie (klucz, adres API, adres frontu) i wybrany serwer.

import { DEFAULT_SERVER, SERVERS } from "./config.js";

const KEY_CONNECTION = "connection";
const KEY_SERVER = "server";
const KEY_ACTIVE_JOBS = "activeJobs";

const ACTIVE_JOBS_LIMIT = 50;

/**
 * Rekrutacja, nad którą osoba pracuje w danym kontekście (projekt Recruitera
 * albo „global”). Osobno na serwer, bo id ze stagingu nic nie znaczy na produkcji.
 */
export async function getActiveJob(serverId, context) {
  const items = await chrome.storage.local.get(KEY_ACTIVE_JOBS);
  return items[KEY_ACTIVE_JOBS]?.[serverId]?.[context] || null;
}

export async function setActiveJob(serverId, context, job) {
  const items = await chrome.storage.local.get(KEY_ACTIVE_JOBS);
  const all = items[KEY_ACTIVE_JOBS] || {};
  // Klucze w kolejności zapisu: przy nadmiarze odpadają najdawniej wybrane projekty.
  const { [context]: _previous, ...others } = all[serverId] || {};
  const entries = Object.entries(others).slice(-(ACTIVE_JOBS_LIMIT - 1));
  if (job) entries.push([context, job]);
  await chrome.storage.local.set({ [KEY_ACTIVE_JOBS]: { ...all, [serverId]: Object.fromEntries(entries) } });
}

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
