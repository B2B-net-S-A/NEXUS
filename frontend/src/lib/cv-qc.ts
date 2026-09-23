// QC CV (Rekrutacja v5, decyzje Artura 23.09.2026) — prezentacja wyniku.
//
// Sprawdzenia liczy serwer (`GET /api/pipeline/stages/{id}/qc`); tu wyłącznie
// czyste funkcje: podświetlenie terminów w tekście CV, podział CV na
// stanowiska (czerwona krawędź przy roli z brakiem), rozbiór `**pogrubienia**`
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
  requirements: string[];
}

/** Braki w stanowiskach (`must_in_roles`) pogrupowane po roli. */
export function roleGaps(checks: QcCheck[]): RoleGap[] {
  const byRole = new Map<string, RoleGap>();
  for (const check of checks) {
    if (check.key !== "must_in_roles" || check.status !== "fail") continue;
    for (const item of check.items) {
      const role = item.role?.trim();
      if (!role) continue;
      const roleIndex = typeof item.role_index === "number" ? item.role_index : null;
      const key = roleIndex != null ? `#${roleIndex}` : role;
      const gap = byRole.get(key) ?? { role, roleIndex, requirements: [] };
      const req = item.requirement?.trim();
      if (req && !gap.requirements.includes(req)) gap.requirements.push(req);
      byRole.set(key, gap);
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

export interface CvSegment {
  /** Kolejne bloki CV należące do segmentu. */
  blocks: QcCvBlock[];
  /** Brak w tym stanowisku (czerwona krawędź) — `null` = segment bez braków. */
  gap: RoleGap | null;
}

/**
 * Dzieli CV na segmenty: stanowisko = blok `section: "role"` + wszystko do
 * następnej roli albo nagłówka. Brak trafia do segmentu po `role_index`
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
