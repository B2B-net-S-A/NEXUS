/**
 * Podgląd strony w edytorze nowego CV (22.11.2026) — czysta logika: kiedy
 * prosić serwer o PDF, co mówią nagłówki renderu i gdzie na stronie stoi
 * edytowany blok.
 *
 * Trasa `…/cv/branded/preview-pdf` ma limit 20 żądań na minutę na osobę
 * (render nowego CV to 1–3 s procesora), a dzielą go podgląd w formularzu,
 * „Jak u klienta” i „Pobierz PDF”. Formularz prosi więc o PDF dopiero
 * `PREVIEW_DEBOUNCE_MS` po ostatniej zmianie i najwyżej
 * `PREVIEW_MAX_PER_MINUTE` razy na minutę.
 */

export const PREVIEW_DEBOUNCE_MS = 4000;
export const PREVIEW_MAX_PER_MINUTE = 8;
const MINUTE_MS = 60_000;

/**
 * Za ile milisekund wolno poprosić o nowy PDF. `lastChangeAt: null` = nic się
 * nie zmieniło od otwarcia (pierwszy podgląd od razu); `sent` — chwile
 * poprzednich żądań, rosnąco.
 */
export function previewDelay({
  now,
  lastChangeAt,
  sent,
  debounceMs = PREVIEW_DEBOUNCE_MS,
  maxPerMinute = PREVIEW_MAX_PER_MINUTE,
}: {
  now: number;
  lastChangeAt: number | null;
  sent: readonly number[];
  debounceMs?: number;
  maxPerMinute?: number;
}): number {
  let wait = lastChangeAt === null ? 0 : Math.max(0, lastChangeAt + debounceMs - now);
  const recent = sent.filter((at) => now - at < MINUTE_MS);
  if (recent.length >= maxPerMinute) {
    const expires = recent[recent.length - maxPerMinute] + MINUTE_MS;
    wait = Math.max(wait, expires - now);
  }
  return wait;
}

export interface NewCvRenderInfo {
  /** `null` = render nie powiedział (klasyczny PDF albo zapas). */
  fits: boolean | null;
  fontPt: number | null;
  unmapped: number;
}

/** Nagłówki `X-CV-Page1-*` z odpowiedzi podglądu nowego CV. */
export function renderInfo(headers: Headers | null | undefined): NewCvRenderInfo {
  const fits = headers?.get("X-CV-Page1-Fits");
  const font = Number.parseFloat(headers?.get("X-CV-Page1-Font") ?? "");
  const unmapped = Number.parseInt(headers?.get("X-CV-Unmapped-Sections") ?? "", 10);
  return {
    fits: fits === "1" ? true : fits === "0" ? false : null,
    fontPt: Number.isFinite(font) ? font : null,
    unmapped: Number.isFinite(unmapped) ? unmapped : 0,
  };
}

/** „Strona 1 z 3 · mieści się · pismo 10 pt” — chip nad podglądem. */
export function pageChip(page: number, pages: number | null, info?: NewCvRenderInfo | null): string {
  const parts = [pages ? `Strona ${page} z ${pages}` : `Strona ${page}`];
  if (page === 1 && info?.fits != null) {
    parts.push(info.fits ? "mieści się" : "nie mieści się");
    if (info.fontPt !== null) parts.push(`pismo ${String(info.fontPt).replace(".", ",")} pt`);
  }
  return parts.join(" · ");
}

// ── Gdzie na stronie stoi blok ───────────────────────────────────────────────

/** Fragment warstwy tekstu pdf.js: początek linii bazowej i rozmiar w jednostkach PDF. */
export interface PdfTextItem {
  str: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PdfBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface PdfLine extends PdfBox {
  text: string;
}

export function normalizeForMatch(text: string): string {
  return text
    .normalize("NFC")
    .replace(/\*\*/g, "")
    .replace(/­/g, "")
    .replace(/[–—]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Fragmenty jednej linii (ta sama linia bazowa) sklejone w tekst z ramką. */
export function textLines(items: readonly PdfTextItem[]): PdfLine[] {
  const lines: PdfLine[] = [];
  for (const item of items) {
    if (!item.str.trim()) continue;
    const tolerance = Math.max(1, item.height * 0.4);
    const line = lines.find((candidate) => Math.abs(candidate.y0 - item.y) <= tolerance);
    if (line) {
      line.text = `${line.text} ${item.str}`;
      line.x0 = Math.min(line.x0, item.x);
      line.x1 = Math.max(line.x1, item.x + item.width);
      line.y1 = Math.max(line.y1, item.y + item.height);
    } else {
      lines.push({
        text: item.str,
        x0: item.x,
        x1: item.x + item.width,
        y0: item.y,
        y1: item.y + item.height,
      });
    }
  }
  return lines.map((line) => ({ ...line, text: normalizeForMatch(line.text) }));
}

const NEEDLE_CHARS = 28;
const NEEDLE_MIN = 6;

interface NeedleKey {
  /** Początek tekstu — po nim szukamy linii, w której punkt się zaczyna. */
  key: string;
  /** Cały tekst — po nim doliczamy linie, do których punkt się zawinął. */
  full: string;
}

function needleKeys(needles: readonly string[]): NeedleKey[] {
  return needles
    .map((needle) => {
      const full = normalizeForMatch(needle);
      return { key: full.slice(0, NEEDLE_CHARS).trim(), full };
    })
    .filter(({ key }) => key.length >= NEEDLE_MIN);
}

/** Tekst bez spacji i łączników: pdf.js dzieli linię na fragmenty (pogrubienia) i przenosi wyrazy. */
function compact(text: string): string {
  return text.replace(/[\s-]/g, "");
}

/**
 * Linie pod `start`, do których zawinął się szukany punkt: ta sama kolumna,
 * odstęp najwyżej dwóch wysokości linii, a tekst to dalszy ciąg punktu.
 * Bez tego ramka kończyła się na pierwszej linii ostatniego punktu.
 */
function wrappedLines(lines: readonly PdfLine[], start: PdfLine, { key, full }: NeedleKey): PdfLine[] {
  const own = compact(start.text);
  const at = own.indexOf(compact(key));
  let rest = compact(full).slice(own.length - Math.max(at, 0));
  const out: PdfLine[] = [];
  let current = start;
  while (rest) {
    const gap = Math.max(1, current.y1 - current.y0) * 2;
    const below = lines.filter(
      (line) =>
        line.y0 < current.y0 &&
        current.y0 - line.y0 <= gap &&
        line.x0 < start.x1 &&
        line.x1 > start.x0,
    );
    if (!below.length) break;
    const next = below.reduce((best, line) => (line.y0 > best.y0 ? line : best));
    const text = compact(next.text);
    if (!text || !(rest.startsWith(text) || text.startsWith(rest))) break;
    out.push(next);
    rest = rest.slice(text.length);
    current = next;
  }
  return out;
}

/** Porównanie bez spacji: sklejenie fragmentów daje „it , w” po pogrubieniu tuż przed przecinkiem. */
function matches(line: PdfLine, key: string): boolean {
  const text = compact(line.text);
  const wanted = compact(key);
  return text.includes(wanted) || (text.length >= 10 && wanted.startsWith(text));
}

/**
 * Linie strony, w których zaczyna się któryś z szukanych tekstów (z liniami,
 * do których się zawinął), i ich wspólna ramka. Pierwszy tekst to kotwica (pierwszy punkt, firma); dla pozostałych
 * bierzemy linię najbliżej kotwicy — „Java Developer” stoi też w linii
 * „Senior Java Developer” innego stanowiska.
 */
export function findBlock(lines: readonly PdfLine[], needles: readonly string[]): { box: PdfBox; hits: number } | null {
  const keys = needleKeys(needles);
  let box: PdfBox | null = null;
  let hits = 0;
  let anchor: PdfLine | null = null;
  for (const needle of keys) {
    const found = lines.filter((candidate) => matches(candidate, needle.key));
    if (!found.length) continue;
    const near = anchor;
    const line: PdfLine = near
      ? found.reduce((best, candidate) =>
          Math.abs(candidate.y0 - near.y0) < Math.abs(best.y0 - near.y0) ? candidate : best,
        )
      : found[0];
    anchor ??= line;
    hits += 1;
    for (const part of [line, ...wrappedLines(lines, line, needle)]) {
      box = box
        ? {
            x0: Math.min(box.x0, part.x0),
            y0: Math.min(box.y0, part.y0),
            x1: Math.max(box.x1, part.x1),
            y1: Math.max(box.y1, part.y1),
          }
        : { x0: part.x0, y0: part.y0, x1: part.x1, y1: part.y1 };
    }
  }
  return box ? { box, hits } : null;
}

/** Strona (od 1) z największą liczbą trafień; przy remisie wcześniejsza. */
export function bestPage(
  pages: readonly (readonly PdfLine[])[],
  needles: readonly string[],
): { page: number; box: PdfBox } | null {
  let best: { page: number; box: PdfBox; hits: number } | null = null;
  for (let index = 0; index < pages.length; index += 1) {
    const found = findBlock(pages[index], needles);
    if (found && (!best || found.hits > best.hits)) best = { page: index + 1, ...found };
  }
  return best ? { page: best.page, box: best.box } : null;
}
