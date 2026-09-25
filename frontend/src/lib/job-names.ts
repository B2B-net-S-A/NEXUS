/**
 * Trzy nazwy rekrutacji (0378, 25.09.2026).
 *
 * - `title` — nazwa od klienta. Idzie do klienta (CV, plik, Cpro).
 * - `client_reference` — numer zapytania klienta (ZOB, SAP, numer w Cpro).
 * - `working_title` — tytuł dla rekrutera („Java Developer · Java, Kafka ·
 *   5+ lat · Payments”). Tylko ekrany wewnętrzne, nigdy do klienta.
 *
 * `composeWorkingTitle` jest lustrem `backend/app/services/job_working_title.py`
 * — oba czytają `__fixtures__/job-working-title-cases.json`.
 */

const SEPARATOR = " · ";
const MAX_LEN = 255;
const MUST_IN_TITLE = 2;

type MustItem = string | { name?: string | null } | null | undefined;

function clean(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function yearsLabel(years: number): string {
  if (years === 1) return "1+ rok";
  if ([2, 3, 4].includes(years % 10) && ![12, 13, 14].includes(years % 100))
    return `${years}+ lata`;
  return `${years}+ lat`;
}

export function composeWorkingTitle(
  role: string | null | undefined,
  must: readonly MustItem[] = [],
  minYears: number | null | undefined = null,
  domain: string | null | undefined = null,
): string | null {
  const roleText = clean(role);
  const names: string[] = [];
  const seen = new Set<string>();
  for (const item of must ?? []) {
    const name = clean(typeof item === "object" && item !== null ? item.name : item);
    const key = name.toLocaleLowerCase("pl");
    if (name && !seen.has(key)) {
      seen.add(key);
      names.push(name);
    }
    if (names.length === MUST_IN_TITLE) break;
  }
  if (!roleText && names.length === 0) return null;
  const parts = [roleText, names.join(", ")];
  if (typeof minYears === "number" && Number.isInteger(minYears) && minYears > 0)
    parts.push(yearsLabel(minYears));
  parts.push(clean(domain));
  const kept = parts.filter(Boolean);
  while (kept.length > 1 && kept.join(SEPARATOR).length > MAX_LEN) kept.pop();
  return kept.join(SEPARATOR).slice(0, MAX_LEN).trimEnd();
}

export interface JobNames {
  id?: number | null;
  title?: string | null;
  working_title?: string | null;
  client_reference?: string | null;
  client_name?: string | null;
}

/** Tytuł na ekranach wewnętrznych: tytuł dla rekrutera, a bez niego nazwa od klienta. */
export function jobDisplayTitle(job: JobNames): string {
  return (
    clean(job.working_title) ||
    clean(job.title) ||
    (job.id != null ? `Rekrutacja #${job.id}` : "Rekrutacja")
  );
}

/**
 * Nazwa od klienta pod tytułem — tylko gdy różni się od tego, co już widać
 * (rekrutacja bez tytułu dla rekrutera pokazuje ją w pierwszej linii).
 */
export function jobClientTitle(job: JobNames): string | null {
  const title = clean(job.title);
  if (!title) return null;
  return title.toLocaleLowerCase("pl") === jobDisplayTitle(job).toLocaleLowerCase("pl")
    ? null
    : title;
}

/** Druga linia: `klient · „nazwa od klienta” · numer u klienta` (puste człony znikają). */
export function jobClientLine(job: JobNames): string {
  const clientTitle = jobClientTitle(job);
  return [
    clean(job.client_name),
    clientTitle ? `„${clientTitle}”` : "",
    clean(job.client_reference),
  ]
    .filter(Boolean)
    .join(" · ");
}

export interface JobNamesDraft {
  clientReference: string;
  workingTitle: string;
  /** `true` = tytuł wpisany ręcznie (automat wyłączony). */
  workingTitleManual: boolean;
}

export function jobNamesDraft(job: JobNames & { working_title_auto?: boolean | null }): JobNamesDraft {
  return {
    clientReference: job.client_reference ?? "",
    workingTitle: job.working_title ?? "",
    workingTitleManual: job.working_title_auto === false,
  };
}

/**
 * Pola PATCH `/api/jobs/{id}` dla nazw — WYŁĄCZNIE to, co się zmieniło.
 * Pusty `working_title` przywraca automat (serwer przelicza tytuł sam).
 */
export function jobNamesPatch(
  job: JobNames & { working_title_auto?: boolean | null },
  draft: JobNamesDraft,
): Record<string, string | null> {
  const before = jobNamesDraft(job);
  const patch: Record<string, string | null> = {};
  const reference = draft.clientReference.trim();
  if (reference !== before.clientReference.trim()) patch.client_reference = reference || null;
  if (draft.workingTitleManual) {
    const title = draft.workingTitle.trim();
    if (title && (!before.workingTitleManual || title !== before.workingTitle.trim()))
      patch.working_title = title;
  } else if (before.workingTitleManual) {
    patch.working_title = "";
  }
  return patch;
}
