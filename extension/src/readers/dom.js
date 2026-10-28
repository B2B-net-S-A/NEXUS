// Pomocnicze funkcje czytników. Działają na każdym obiekcie z API DOM
// (`Document` z DOMParsera w panelu, linkedom w testach).

import { FOREIGN_REGIONS, HIDDEN_TEXT, MAIN, NOISE_TEXT, SECTIONS, VISIBLE_TEXT } from "./selectors.js";

export function clean(text) {
  return String(text ?? "")
    .replace(/[   ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function safeQuery(root, selector) {
  try {
    return root?.querySelector?.(selector) ?? null;
  } catch {
    return null; // selektor nieobsługiwany w tym silniku — próbujemy następnego
  }
}

export function safeQueryAll(root, selector) {
  try {
    return [...(root?.querySelectorAll?.(selector) ?? [])];
  } catch {
    return [];
  }
}

/**
 * Tekst elementu tak, jak widzi go człowiek: jeśli są `span[aria-hidden=true]`
 * (LinkedIn dubluje treść dla czytników ekranu), bierzemy pierwszy z nich;
 * w przeciwnym razie tekst bez `.visually-hidden`.
 */
export function visibleText(el) {
  if (!el) return "";
  const own = el.matches?.(VISIBLE_TEXT) ? el : safeQuery(el, VISIBLE_TEXT);
  if (own && clean(own.textContent)) return clean(own.textContent);
  const hidden = safeQueryAll(el, HIDDEN_TEXT);
  if (!hidden.length) return clean(el.textContent);
  const copy = el.cloneNode(true);
  for (const h of safeQueryAll(copy, HIDDEN_TEXT)) h.remove();
  return clean(copy.textContent);
}

export function firstText(root, selectors) {
  for (const sel of selectors) {
    for (const el of safeQueryAll(root, sel)) {
      const t = visibleText(el);
      if (t) return t;
    }
  }
  return "";
}

export function firstElement(root, selectors) {
  for (const sel of selectors) {
    const el = safeQuery(root, sel);
    if (el) return el;
  }
  return null;
}

export function mainRoot(doc) {
  return firstElement(doc, MAIN) || doc;
}

export function inForeignRegion(el) {
  try {
    return Boolean(el.closest?.(FOREIGN_REGIONS));
  } catch {
    return false;
  }
}

export function isNoise(text) {
  return !text || NOISE_TEXT.some((re) => re.test(text));
}

/**
 * Teksty bloków w kolejności dokumentu: każdy `span[aria-hidden]`, a gdy ich
 * nie ma — liście drzewa (elementy bez dzieci-elementów). Bez duplikatów
 * sąsiednich i bez szumu (przyciski, stopnie kontaktu).
 */
export function textBlocks(root, { skip = null } = {}) {
  if (!root) return [];
  let nodes = safeQueryAll(root, VISIBLE_TEXT);
  if (!nodes.length) {
    nodes = safeQueryAll(root, "*").filter(
      (el) => !el.children?.length && !["SCRIPT", "STYLE", "BUTTON"].includes(el.tagName),
    );
  }
  const out = [];
  for (const n of nodes) {
    if (skip && skip(n)) continue;
    try {
      if (n.closest?.(HIDDEN_TEXT) || n.closest?.("button")) continue;
    } catch {
      /* ignoruj */
    }
    const t = clean(n.textContent);
    if (!t || isNoise(t)) continue;
    if (out[out.length - 1] === t) continue;
    out.push(t);
  }
  return out;
}

function headingMatches(el, headings) {
  const t = clean(el.textContent).toLowerCase();
  return headings.some((h) => t === h.toLowerCase() || t.startsWith(`${h.toLowerCase()} `));
}

/**
 * Sekcja profilu (doświadczenie, umiejętności, informacje):
 * 1) kotwica `<div id="experience">` → najbliższa `section`,
 * 2) atrybuty `data-test-…` z selectors.js,
 * 3) nagłówek h2/h3 o znanym tekście → jego `section` (albo rodzic).
 */
export function findSection(doc, name) {
  const spec = SECTIONS[name];
  for (const id of spec.anchors) {
    const anchor = safeQuery(doc, `#${id}`);
    if (anchor) {
      const section = anchor.closest?.("section") || anchor.parentElement;
      if (section) return section;
    }
  }
  for (const sel of spec.dataAttrs) {
    const el = safeQuery(doc, sel);
    if (el) return el;
  }
  for (const h of safeQueryAll(doc, "h2, h3")) {
    if (inForeignRegion(h)) continue;
    if (headingMatches(h, spec.headings)) {
      return h.closest?.("section") || h.parentElement?.parentElement || h.parentElement;
    }
  }
  return null;
}

/** Bezpośrednie pozycje listy sekcji (bez zagnieżdżonych podlist). */
export function topLevelItems(section, itemSelectors) {
  if (!section) return [];
  for (const sel of itemSelectors) {
    const all = safeQueryAll(section, sel);
    if (!all.length) continue;
    const top = all.filter((li) => {
      let p = li.parentElement;
      while (p && p !== section) {
        if (all.includes(p)) return false;
        p = p.parentElement;
      }
      return true;
    });
    if (top.length) return top;
  }
  return [];
}

export function slugFromHref(href) {
  const raw = String(href || "");
  const m = raw.match(/linkedin\.com\/in\/([^/?#]+)/) || raw.match(/^\/in\/([^/?#]+)/);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return m[1];
  }
}

export function publicUrlFromSlug(slug) {
  return slug ? `https://www.linkedin.com/in/${encodeURIComponent(slug)}` : null;
}

function normalizeForMatch(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[Łł]/g, "l")
    .toLowerCase();
}

/**
 * Czy slug na pewno NIE należy do tej osoby? Slug nieprzezroczysty
 * (`ACoAA…`, same cyfry) albo krótkie nazwisko → brak dowodu → `false`.
 * Chroni przed wzięciem linku do cudzego profilu z „Inni oglądali też”.
 */
export function slugContradictsName(slug, fullName) {
  const s = normalizeForMatch(slug);
  if (!s || /^ac[a-z]a/i.test(slug) || !/[a-z]{3,}/.test(s)) return false;
  const tokens = normalizeForMatch(fullName)
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 3);
  if (!tokens.length) return false;
  return !tokens.some((t) => s.includes(t));
}
