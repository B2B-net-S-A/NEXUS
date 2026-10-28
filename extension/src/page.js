// Odczyt aktywnej karty LinkedIna — wyłącznie na żądanie panelu
// (otwarcie panelu, zmiana adresu karty, klik „Sprawdź tę stronę”).
//
// Do karty wstrzykujemy jedną samodzielną funkcję, która oddaje kopię DOM-u
// bez skryptów, obrazków i bloków <code> (tam LinkedIn trzyma dane swojego
// wewnętrznego API — ich nie czytamy). Czytniki działają już w panelu na
// dokumencie z DOMParsera, więc są zwykłymi modułami ES z testami w node.

import { readPage } from "./readers/index.js";

/* Ta funkcja jest serializowana i uruchamiana w karcie — nie może używać
   niczego spoza swojego ciała. */
function capturePage() {
  const clone = document.documentElement.cloneNode(true);
  clone
    .querySelectorAll("script, style, code, svg, img, picture, video, iframe, noscript, link, meta, template, canvas")
    .forEach((n) => n.remove());
  return { url: location.href, html: `<!doctype html>${clone.outerHTML}` };
}

export async function captureTab(tabId) {
  const [injection] = await chrome.scripting.executeScript({ target: { tabId }, func: capturePage });
  if (!injection || !injection.result || typeof injection.result.html !== "string") {
    throw new Error("Pusta odpowiedź z karty");
  }
  return injection.result;
}

export async function readTab(tabId) {
  const { url, html } = await captureTab(tabId);
  const doc = new DOMParser().parseFromString(html, "text/html");
  return readPage(doc, url);
}
