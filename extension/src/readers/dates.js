// Linie dat z doświadczenia LinkedIna → {start: "RRRR-MM", end: "RRRR-MM" | null, current}.

import { MONTHS, PRESENT_WORDS } from "./selectors.js";
import { clean } from "./dom.js";

const pad = (n) => String(n).padStart(2, "0");

function parsePoint(text, { isEnd }) {
  const t = clean(text).toLowerCase().replace(/\.$/, "");
  if (!t) return null;
  if (PRESENT_WORDS.some((w) => t === w || t.startsWith(`${w} `))) return { present: true };
  const ym = t.match(/^([a-ząćęłńóśźż]+)\.?\s+(\d{4})$/);
  if (ym && MONTHS[ym[1]]) return { value: `${ym[2]}-${pad(MONTHS[ym[1]])}` };
  const numeric = t.match(/^(\d{1,2})[./](\d{4})$/);
  if (numeric && +numeric[1] >= 1 && +numeric[1] <= 12) return { value: `${numeric[2]}-${pad(+numeric[1])}` };
  const year = t.match(/^(\d{4})$/);
  // Sam rok: start liczymy od stycznia, koniec od grudnia (staż nie wychodzi zawyżony o rok).
  if (year) return { value: `${year[1]}-${isEnd ? "12" : "01"}` };
  return null;
}

/**
 * „mar 2022 – obecnie · 2 lata 8 mies.” → {start: "2022-03", end: null, current: true}
 * „Jan 2018 - Dec 2021 · 4 yrs” → {start: "2018-01", end: "2021-12", current: false}
 * Zwraca null, gdy linia nie jest zakresem dat.
 */
export function parseDateRange(line) {
  const range = clean(line).split("·")[0].trim();
  const parts = range.split(/\s+[–—-]\s+|\s*[–—]\s*/);
  if (parts.length === 1) {
    const single = parsePoint(parts[0], { isEnd: false });
    if (single?.value) return { start: single.value, end: single.value, current: false };
    return null;
  }
  if (parts.length !== 2) return null;
  const start = parsePoint(parts[0], { isEnd: false });
  const end = parsePoint(parts[1], { isEnd: true });
  if (!start?.value || !end) return null;
  if (end.present) return { start: start.value, end: null, current: true };
  return { start: start.value, end: end.value, current: false };
}

export function isDateLine(line) {
  return parseDateRange(line) !== null;
}

/** Czas trwania po kropce („2 lata 8 mies.”, „5 yrs”) — sam w sobie nie jest datą. */
export function isDurationLine(line) {
  return /^\d+\s*(yrs?|years?|lat[a]?|rok|mos?|months?|mies)/i.test(clean(line));
}
