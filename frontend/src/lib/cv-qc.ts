// QC CV (Rekrutacja v5, decyzje Artura 23.09.2026) — prezentacja wyniku.
//
// Sprawdzenia liczy serwer (`GET /api/pipeline/stages/{id}/qc`); tu wyłącznie
// czyste funkcje: podświetlenie terminów w tekście CV, podział CV na
// stanowiska (krawędź przy roli z brakiem), podział sprawdzeń na „do poprawy
// / warto poprawić / w porządku”, powody obejścia, rozbiór `**pogrubienia**`
// z propozycji AI i kody błędów. Wszystko zwraca TEKST — nic nie trafia na
// stronę jako HTML.

import type { QcCheck, QcCvBlock, QcFixKind, QcItem } from "@/lib/api/cvQc";

// ── Podświetlenie terminów ───────────────────────────────────────────────────
//
// Reguła granic słowa jest lustrem `backend/app/services/keyword_terms.py`
// (`py_regex`): granica tylko po stronie litery/cyfry, więc „Java" nie
// podświetla „JavaScript", a „C++" podświetla „C++17".

export interface TextPart {
  text: string;
  /** Który termin trafił — `null` = zwykły tekst. */
  match: string | null;
}

const WORD = /[\p{L}\p{N}_]/u;

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function termSource(term: string): string | null {
  const text = term.trim();
  if (!text) return null;
  const core = text
    .split(/\s+/)
    .map(escapeRegex)
    .join("[\\s\\-/]+");
  const left = WORD.test(text[0]) ? "(?<![\\p{L}\\p{N}_])" : "";
  const right = WORD.test(text[text.length - 1]) ? "(?![\\p{L}\\p{N}_])" : "";
  return `${left}${core}${right}`;
}

/** Alternatywy wymagania („Java lub Kotlin") — jak `requirement_contract.alternatives`. */
export function requirementAlternatives(label: string): string[] {
  return label
    .split(/\s+(?:lub|albo|or)\s+/i)
    .map((p) => p.trim())
    .filter(Boolean);
}

/** Dzieli tekst na kawałki z zaznaczonymi trafieniami terminów. */
export function highlightTerms(text: string, labels: string[]): TextPart[] {
  const sources: Array<{ label: string; source: string }> = [];
  for (const label of labels) {
    for (const alt of requirementAlternatives(label)) {
      const source = termSource(alt);
      if (source) sources.push({ label, source });
    }
  }
  if (!text || sources.length === 0) return [{ text, match: null }];
  // Dłuższe najpierw: „Spring Boot" wygrywa ze „Spring".
  sources.sort((a, b) => b.source.length - a.source.length);
  const pattern = new RegExp(sources.map((s) => `(${s.source})`).join("|"), "giu");
  const parts: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const index = m.index ?? 0;
    if (m[0].length === 0) continue;
    if (index > last) parts.push({ text: text.slice(last, index), match: null });
    const group = m.slice(1).findIndex((g) => g !== undefined);
    parts.push({ text: m[0], match: sources[group]?.label ?? null });
    last = index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), match: null });
  return parts;
}

// ── Propozycje AI: `**x**` = pogrubienie ─────────────────────────────────────

export interface MarkupRun {
  t: string;
  b: boolean;
}

/** `Rozwijała moduł w **Java 11**` → kawałki tekstu z flagą pogrubienia. */
export function parseBoldMarkup(text: string): MarkupRun[] {
  const runs: MarkupRun[] = [];
  const pattern = /\*\*([^*]+?)\*\*/g;
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const index = m.index ?? 0;
    if (index > last) runs.push({ t: text.slice(last, index), b: false });
    runs.push({ t: m[1], b: true });
    last = index + m[0].length;
  }
  if (last < text.length) runs.push({ t: text.slice(last), b: false });
  return runs.filter((r) => r.t.length > 0);
}

// ── Terminy do podświetlenia i stanowiska z brakami ──────────────────────────

const BOLD_CHECKS = new Set(["must_bolded", "nice_bolded"]);

/** Terminy, które NIE są pogrubione tam, gdzie powinny — żółte w CV. */
export function unboldedTerms(checks: QcCheck[]): string[] {
  const terms = new Set<string>();
  for (const check of checks) {
    if (!BOLD_CHECKS.has(check.key) || check.status !== "fail") continue;
    for (const item of check.items) {
      const term = (item.term ?? item.requirement ?? "").trim();
      if (term) terms.add(term);
    }
  }
  return [...terms];
}

export interface RoleGap {
  /** Etykieta roli z serwera („Allegro — Senior Java Developer"). */
  role: string;
  /** Numer stanowiska w CV (`role_index` z serwera) — pewniejszy niż etykieta. */
  roleIndex: number | null;
  /** Wszystkie braki w tej roli — krytyczne pierwsze. */
  requirements: string[];
  /** Umiejętności krytyczne bez opisu w tej roli — te zatrzymują wysyłkę. */
  blocking: string[];
}

/** Sprawdzenia z brakami w stanowiskach; krytyczne przed pozostałymi must-have. */
const ROLE_GAP_CHECKS = ["critical_skills", "must_in_roles"];

/** Braki w stanowiskach (krytyczne i pozostałe must-have) pogrupowane po roli. */
export function roleGaps(checks: QcCheck[]): RoleGap[] {
  const byRole = new Map<string, RoleGap>();
  for (const key of ROLE_GAP_CHECKS) {
    for (const check of checks) {
      if (check.key !== key || check.status !== "fail") continue;
      for (const item of check.items) {
        const role = item.role?.trim();
        if (!role) continue;
        const roleIndex = typeof item.role_index === "number" ? item.role_index : null;
        const id = roleIndex != null ? `#${roleIndex}` : role;
        const gap = byRole.get(id) ?? { role, roleIndex, requirements: [], blocking: [] };
        const req = item.requirement?.trim();
        if (req && !gap.requirements.includes(req)) gap.requirements.push(req);
        if (req && check.severity === "blocking" && !gap.blocking.includes(req)) gap.blocking.push(req);
        byRole.set(id, gap);
      }
    }
  }
  return [...byRole.values()];
}

function normalize(value: string): string {
  return value
    .toLocaleLowerCase("pl")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Części etykiety roli: „Allegro — Senior Java Dev · 2019–2022" → [allegro, senior java dev].
 *  Lata odpadają — CV pisze daty w innym formacie niż etykieta. */
function roleParts(role: string): string[] {
  return role
    .split(/\s+[—–\-·|]\s+|,\s+/)
    .map(normalize)
    .filter((p) => p.length >= 2 && !/\d{4}/.test(p));
}

/** Sekcja bloku z klauzulą zgody RODO (lustro `dz_review.RODO_SECTION`). */
export const RODO_SECTION = "rodo";

export interface CvSegment {
  /** Kolejne bloki CV należące do segmentu. */
  blocks: QcCvBlock[];
  /** Brak w tym stanowisku (krawędź z boku) — `null` = segment bez braków. */
  gap: RoleGap | null;
}

/**
 * Dzieli CV na segmenty: stanowisko = blok `section: "role"` + wszystko do
 * następnej roli, nagłówka albo klauzuli zgody RODO (stoi tuż po ostatnim
 * stanowisku, ale nie jest jego treścią). Brak trafia do segmentu po `role_index`
 * (n-te stanowisko w sekcji doświadczenia — lustro `cv_qc.cv_roles`), a bez
 * numeru — gdy tekst segmentu zawiera KAŻDĄ część etykiety roli (pracodawca
 * i stanowisko bywają w dwóch blokach). Brak bez dopasowania nie znika —
 * zostaje na liście sprawdzeń po prawej.
 */
export function segmentCv(blocks: QcCvBlock[], gaps: RoleGap[]): CvSegment[] {
  const segments: CvSegment[] = [];
  const ordinals = new Map<CvSegment, number>();
  let current: CvSegment | null = null;
  let inExperience = false;
  let roleCount = 0;
  for (const block of blocks) {
    // Nagłówek sekcji stoi sam — nie należy do stanowiska nad nim.
    if (block.kind === "h") {
      segments.push({ blocks: [block], gap: null });
      inExperience = block.section === "experience";
      current = null;
      continue;
    }
    if (block.section === RODO_SECTION) {
      segments.push({ blocks: [block], gap: null });
      inExperience = false;
      current = null;
      continue;
    }
    if (block.section === "role" || current === null) {
      current = { blocks: [], gap: null };
      segments.push(current);
      if (block.section === "role" && inExperience) ordinals.set(current, roleCount++);
    }
    current.blocks.push(block);
  }
  const used = new Set<RoleGap>();
  for (const [segment, ordinal] of ordinals) {
    const gap = gaps.find((g) => g.roleIndex === ordinal);
    if (gap) {
      segment.gap = gap;
      used.add(gap);
    }
  }
  for (const segment of segments) {
    if (segment.gap || !segment.blocks.some((b) => b.section === "role")) continue;
    const text = normalize(segment.blocks.map((b) => b.runs.map((r) => r.t).join("")).join(" "));
    const gap = gaps.find((g) => {
      if (used.has(g) || g.roleIndex != null) return false;
      const parts = roleParts(g.role);
      return parts.length > 0 && parts.every((p) => text.includes(p));
    });
    if (gap) {
      segment.gap = gap;
      used.add(gap);
    }
  }
  return segments;
}

// ── Co jest do poprawy, co jest uwagą, co jest w porządku ────────────────────

export interface QcTask {
  /** Stabilny klucz: sprawdzenie + nazwa. */
  id: string;
  check: QcCheck;
  /** Wymaganie albo termin; `null` = pozycja bez nazwy (np. brak CV, stawka w CV). */
  name: string | null;
  items: QcItem[];
}

/**
 * Rzeczy do poprawy w jednym niezaliczonym sprawdzeniu: jedno wymaganie (także
 * w kilku rolach) to jedna rzecz, pozycja bez nazwy liczy się sama. Lustro
 * `cv_qc._tasks` — suma po blokujących = `blocking_failed` z serwera, więc
 * okno, chip na Tablicy i komunikat bramki podają tę samą liczbę.
 */
export function checkTasks(check: QcCheck): QcTask[] {
  const groups = new Map<string, QcTask>();
  check.items.forEach((item, n) => {
    const name = item.requirement || item.term || null;
    const key = name ?? `#${n}`;
    const task = groups.get(key) ?? { id: `${check.key}:${key}`, check, name, items: [] };
    task.items.push(item);
    groups.set(key, task);
  });
  if (groups.size === 0) return [{ id: `${check.key}:#0`, check, name: null, items: [] }];
  return [...groups.values()];
}

export interface QcSplit {
  /** Zatrzymują wysyłkę — „Do poprawy przed wysłaniem". */
  tasks: QcTask[];
  /** Uwagi i sprawdzenia do obejrzenia ręcznie — „Warto poprawić — nie blokuje". */
  notes: QcCheck[];
  /** Zaliczone. */
  passed: QcCheck[];
  /** Nie dotyczą tego CV albo tej rekrutacji. */
  skipped: QcCheck[];
}

export function splitChecks(checks: QcCheck[]): QcSplit {
  const split: QcSplit = { tasks: [], notes: [], passed: [], skipped: [] };
  for (const check of checks) {
    if (check.status === "pass") split.passed.push(check);
    else if (check.status === "skip") split.skipped.push(check);
    else if (check.status === "fail" && check.severity === "blocking") split.tasks.push(...checkTasks(check));
    else split.notes.push(check);
  }
  return split;
}

export function blockingTasks(checks: QcCheck[]): QcTask[] {
  return splitChecks(checks).tasks;
}

/** „1 rzecz", „2 rzeczy", „5 rzeczy". */
export function thingsLabel(count: number): string {
  return count === 1 ? "1 rzecz" : `${count} rzeczy`;
}

/** Odmiana po liczbie: `[1, 2–4, 5+]` → „1 inna", „3 inne", „7 innych". */
export function countForm(count: number, forms: [string, string, string]): string {
  if (count === 1) return `1 ${forms[0]}`;
  const few = count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14);
  return `${count} ${few ? forms[1] : forms[2]}`;
}

/** Ile nazw pokazuje jedna linia uwagi — reszta jako „i N innych". */
const NOTE_NAMES_SHOWN = 3;

/** Jedna linia pod uwagą: nazwy pozycji („Kafka, JUnit i 4 inne") albo opis jedynej pozycji. */
export function notePreview(check: QcCheck): string | null {
  const names: string[] = [];
  for (const item of check.items) {
    const name = (item.requirement || item.term || "").trim();
    if (name && !names.includes(name)) names.push(name);
  }
  if (names.length === 0) return check.items[0]?.detail?.trim() || null;
  const rest = names.length - NOTE_NAMES_SHOWN;
  const head = names.slice(0, NOTE_NAMES_SHOWN).join(", ");
  return rest > 0 ? `${head} i ${countForm(rest, ["inne", "inne", "innych"])}` : head;
}

/** Krótki tytuł rzeczy do poprawy (karta w oknie QC, lista w oknie obejścia). */
export function taskTitle(task: QcTask): string {
  const { check, name, items } = task;
  if (!name) return items[0]?.detail?.trim() || check.label;
  if (check.key === "critical_skills") {
    const roles = items.filter((i) => i.role).length;
    if (roles === 1) return `${name} — brak opisu w 1 roli`;
    if (roles > 1) return `${name} — brak opisu w ${roles} rolach`;
    return items.some((i) => i.fix === "ask_candidate")
      ? `${name} — brak w CV i w oryginale`
      : `${name} — brak w CV`;
  }
  if (check.key === "no_unsupported") {
    const term = (items[0]?.term ?? name).trim() || name;
    return `${term} — jest w CV, a nie ma tego w oryginale`;
  }
  return name;
}

/** Skąd rzecz pochodzi — plakietka na karcie. */
export const QC_TASK_TAG: Record<string, string> = {
  cv_present: "CV firmowe",
  critical_skills: "umiejętność krytyczna",
  no_unsupported: "zgodność z oryginałem",
  client_rules: "reguły klienta",
};

// ── „Przepuść mimo QC" ───────────────────────────────────────────────────────

/** Lustro `cv_qc.OVERRIDE_REASONS` (pilnuje `test_qc_override_reasons_mirror`). */
export const QC_OVERRIDE_REASONS = [
  { code: "client_short_cv", label: "Klient prosił o krótsze CV" },
  { code: "confirmed_in_call", label: "Kandydat potwierdził to w rozmowie, w CV tego nie ma" },
  { code: "requirement_not_applicable", label: "To wymaganie nie dotyczy tej roli" },
  { code: "other", label: "Inny powód" },
];

export type QcOverrideReason = "client_short_cv" | "confirmed_in_call" | "requirement_not_applicable" | "other";

export const QC_OVERRIDE_NOTE_MAX = 900;

/** Zdanie błędu formularza obejścia albo `null`, gdy można wysłać. */
export function qcOverrideError(reason: QcOverrideReason | null, note: string): string | null {
  if (!reason) return "Wybierz powód.";
  const clean = note.trim();
  if (clean.length > QC_OVERRIDE_NOTE_MAX) return `Opis może mieć najwyżej ${QC_OVERRIDE_NOTE_MAX} znaków.`;
  if (reason === "other" && !clean) return "Przy „Inny powód” napisz, dlaczego przepuszczasz.";
  return null;
}

// ── Akcje naprawy ────────────────────────────────────────────────────────────

/** Naprawy robione raz dla całego sprawdzenia (przycisk w nagłówku grupy). */
export const CHECK_LEVEL_FIXES: ReadonlySet<QcFixKind> = new Set(["bold_all", "spelling", "ai"]);

export function checkLevelFixes(check: QcCheck): QcFixKind[] {
  const kinds: QcFixKind[] = [];
  for (const item of check.items) {
    if (item.fix && CHECK_LEVEL_FIXES.has(item.fix) && !kinds.includes(item.fix)) kinds.push(item.fix);
  }
  return kinds;
}

/** Pytanie do kandydata kopiowane do schowka — nic nie jest wysyłane. */
export function candidateQuestion(item: QcItem): string {
  const term = (item.term ?? item.requirement ?? "").trim() || "tej technologii";
  const role = item.role?.trim();
  return role ? `Czy używał(a) ${term} w ${role}?` : `Czy używał(a) ${term}? W którym projekcie?`;
}

// ── Kody błędów API ──────────────────────────────────────────────────────────

/** Kod z odpowiedzi błędu: `detail.code` (HTTPException) albo `code` w ciele. */
export function apiErrorCode(error: unknown): string | null {
  const data = (error as { response?: { data?: unknown } } | null)?.response?.data;
  if (!data || typeof data !== "object") return null;
  const detail = (data as { detail?: unknown }).detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  const code = (data as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

export const CV_NOT_EDITABLE_CODE = "CV_NOT_EDITABLE";
export const CV_QC_FAILED_CODE = "CV_QC_FAILED";

export const CV_NOT_EDITABLE_MESSAGE =
  "To CV jest plikiem Word/PDF spoza NEXUSA — popraw plik i wgraj ponownie albo wygeneruj CV w NEXUSIE.";

/** Etap do otwarcia QC z odmowy ruchu 409 `CV_QC_FAILED` (`null` = nie ta odmowa). */
export function qcFailedStageId(error: unknown): number | null | undefined {
  if (apiErrorCode(error) !== CV_QC_FAILED_CODE) return undefined;
  const detail = (error as { response?: { data?: { detail?: { stage_id?: unknown } } } }).response?.data?.detail;
  const stageId = detail?.stage_id;
  return typeof stageId === "number" ? stageId : null;
}

export const QC_CV_SOURCE_LABEL: Record<string, string> = {
  branded_finalized: "Zatwierdzone CV firmowe",
  branded_draft: "Szkic CV firmowego",
  generated: "CV z generatora (jeszcze nie na etapie)",
  document: "Plik kandydata spoza NEXUSA",
};

export type QcCardStatus = "passed" | "failed" | "overridden" | "unchecked";

export const QC_STATUS_LABEL: Record<QcCardStatus, string> = {
  passed: "QC ✓",
  failed: "QC do poprawy",
  overridden: "Przepuszczone mimo QC",
  unchecked: "QC nie sprawdzone",
};
