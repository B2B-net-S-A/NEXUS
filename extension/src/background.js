// Service worker: klik ikony otwiera panel, a strona NEXUSA „Połącz wtyczkę”
// oddaje tu klucz. Nic tu nie czyta LinkedIna i nic nie działa w tle.

import { isPingFromNexus, validateKeyMessage } from "./config.js";
import { saveConnection } from "./storage.js";

const CLOSE_CONNECT_TAB_AFTER_MS = 1500;

function enablePanelOnActionClick() {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error("NEXUS: nie udało się ustawić panelu bocznego", err));
}

chrome.runtime.onInstalled.addListener(enablePanelOnActionClick);
chrome.runtime.onStartup.addListener(enablePanelOnActionClick);

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (message?.type === "nexus-ping") {
    sendResponse({ ok: isPingFromNexus(message, sender), version: chrome.runtime.getManifest().version });
    return false;
  }
  const result = validateKeyMessage(message, sender);
  if (!result.ok) {
    console.warn("NEXUS: odrzucona wiadomość połączenia", result.reason);
    sendResponse({ ok: false, reason: result.reason });
    return false;
  }
  saveConnection(result.connection)
    .then(() => {
      sendResponse({ ok: true });
      // Strona pokazuje „Połączono” — zamykamy ją dopiero po chwili.
      const tabId = sender.tab?.id;
      if (typeof tabId === "number") {
        setTimeout(() => {
          chrome.tabs.remove(tabId).catch(() => {});
        }, CLOSE_CONNECT_TAB_AFTER_MS);
      }
    })
    .catch((err) => {
      console.error("NEXUS: nie udało się zapisać połączenia", err);
      sendResponse({ ok: false, reason: "storage_failed" });
    });
  return true; // odpowiedź asynchroniczna
});
