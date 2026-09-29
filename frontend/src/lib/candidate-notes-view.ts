/**
 * Czytelność notatek kandydata (decyzje Artura 29.09.2026).
 *
 * Historia kandydata zarastała wpisami automatów („Auto-match score: …”),
 * a długie notatki z Traffita zajmowały po pół ekranu. Tu mieszkają czyste
 * reguły listy: które notatki widać (filtr rekrutacji, „Pokaż systemowe”),
 * jak podpisać datę i kiedy zwinąć treść. Komponent tylko je rysuje.
 */

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki z luźno typowanego endpointu */

export interface CandidateNoteLike {
  id: number;
  job_id?: number | null;
  job_title?: string | null;
  is_system?: boolean | null;
  pinned_at?: string | null;
  replies?: CandidateNoteLike[] | null;
}

/** Filtr rekrutacji: `all` = wszystkie, `none` = notatki bez rekrutacji. */
export type NoteRecruitmentFilter = "all" | "none" | number;

export interface NoteRecruitmentOption {
  value: NoteRecruitmentFilter;
  label: string;
  count: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;
/** Notatki starsze niż tydzień dostają pełną datę zamiast „3 tyg. temu”. */
export const ABSOLUTE_DATE_AFTER_DAYS = 7;
/** Powyżej tylu znaków albo linii treść jest zwinięta za „Pokaż więcej”. */
export const LONG_NOTE_CHARS = 320;
export const LONG_NOTE_LINES = 5;

const pad = (n: number) => String(n).padStart(2, "0");

/** DD.MM.RRRR HH:MM w strefie przeglądarki. */
export function formatAbsoluteNoteDate(date: Date): string {
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

/**
 * Podpis daty notatki: względny dla ostatnich 7 dni („2 godz. temu”),
 * starsze — pełna data z godziną. `relative` wstrzykiwany (utils zna już
 * polskie odmiany), żeby reguła była testowalna bez zegara.
 */
export function noteDateLabel(
  iso: string | null | undefined,
  now: Date,
  relative: (iso: string) => string,
): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  if (now.getTime() - date.getTime() >= ABSOLUTE_DATE_AFTER_DAYS * DAY_MS) {
    return formatAbsoluteNoteDate(date);
  }
  return relative(iso);
}

export function isLongNote(text: string | null | undefined): boolean {
  if (!text) return false;
  return (
    text.length > LONG_NOTE_CHARS || text.split(/\n/).length > LONG_NOTE_LINES
  );
}

export function systemNoteCount(notes: readonly CandidateNoteLike[]): number {
  return notes.filter((n) => Boolean(n.is_system)).length;
}

/** Notatki widoczne na liście — bez odpowiedzi (te jadą pod notatką). */
export function humanNoteCount(notes: readonly CandidateNoteLike[]): number {
  return notes.length - systemNoteCount(notes);
}

/**
 * Opcje filtra rekrutacji — WYŁĄCZNIE rekrutacje obecne w notatkach (plus
 * „Bez rekrutacji”, gdy są takie notatki). Liczy tylko notatki, które przejdą
 * przełącznik systemowych, żeby liczba przy opcji zgadzała się z listą.
 */
export function noteRecruitmentOptions(
  notes: readonly CandidateNoteLike[],
  { showSystem }: { showSystem: boolean },
  titleFor?: (jobId: number) => string | undefined,
): NoteRecruitmentOption[] {
  const counted = notes.filter((n) => showSystem || !n.is_system);
  const byJob = new Map<number, { label: string; count: number }>();
  let withoutJob = 0;
  for (const note of counted) {
    if (note.job_id == null) {
      withoutJob += 1;
      continue;
    }
    const jobId = Number(note.job_id);
    const entry = byJob.get(jobId);
    if (entry) {
      entry.count += 1;
    } else {
      byJob.set(jobId, {
        label: note.job_title ?? titleFor?.(jobId) ?? `Rekrutacja #${jobId}`,
        count: 1,
      });
    }
  }
  const options: NoteRecruitmentOption[] = [
    { value: "all", label: "Wszystkie rekrutacje", count: counted.length },
  ];
  for (const [jobId, entry] of [...byJob.entries()].sort((a, b) =>
    a[1].label.localeCompare(b[1].label, "pl"),
  )) {
    options.push({ value: jobId, label: entry.label, count: entry.count });
  }
  if (withoutJob > 0 && byJob.size > 0) {
    options.push({ value: "none", label: "Bez rekrutacji", count: withoutJob });
  }
  return options;
}

/** Lista po filtrach. Kolejność z API (przypięte pierwsze) zostaje. */
export function visibleNotes<T extends CandidateNoteLike>(
  notes: readonly T[],
  {
    recruitment,
    showSystem,
  }: { recruitment: NoteRecruitmentFilter; showSystem: boolean },
): T[] {
  return notes.filter((n) => {
    if (!showSystem && n.is_system) return false;
    if (recruitment === "all") return true;
    if (recruitment === "none") return n.job_id == null;
    return n.job_id != null && Number(n.job_id) === recruitment;
  });
}

/** Wartość `<select>` → filtr (i z powrotem). */
export function parseRecruitmentFilter(raw: string): NoteRecruitmentFilter {
  if (raw === "none") return "none";
  const n = Number(raw);
  return Number.isSafeInteger(n) && n > 0 ? n : "all";
}

/** Notatka wskazana w adresie może być odpowiedzią — wskaż wtedy jej wątek. */
export function threadContainsNote(note: CandidateNoteLike, noteId: number): boolean {
  if (Number(note.id) === noteId) return true;
  return (note.replies ?? []).some((r) => Number(r.id) === noteId);
}

/** Etykieta plakietki auto-matcha przy procesie („Auto-match 67/100 · JJIT”). */
export function autoMatchBadgeLabel(meta: any): string | null {
  if (!meta || typeof meta !== "object") return null;
  const score = Number(meta.score);
  if (!Number.isFinite(score)) return null;
  const source = typeof meta.source === "string" ? meta.source : "";
  const sourceLabel =
    source === "jjit" ? "JJIT" : source && source !== "nexus" ? source.toUpperCase() : "";
  return sourceLabel
    ? `Auto-match ${Math.round(score)}/100 · ${sourceLabel}`
    : `Auto-match ${Math.round(score)}/100`;
}

/** Podpowiedź do plakietki: trafione must-have. */
export function autoMatchBadgeTitle(meta: any): string | undefined {
  if (!meta || typeof meta !== "object") return undefined;
  const hit: string[] = Array.isArray(meta.must_hit) ? meta.must_hit : [];
  const total = typeof meta.must_total === "number" ? meta.must_total : null;
  const parts = ["Dodany automatycznie — wynik dopasowania do rekrutacji."];
  if (total != null && total > 0) {
    parts.push(`Must-have: ${hit.length}/${total}${hit.length ? ` (${hit.join(", ")})` : ""}.`);
  } else if (hit.length) {
    parts.push(`Must-have trafione: ${hit.join(", ")}.`);
  }
  return parts.join(" ");
}
