/**
 * Krótki wiersz listy rekrutacji (02.10.2026): sama nazwa stanowiska i tryb
 * pracy. Wymagania, lata, nazwa od klienta i numery — które automat dokleja
 * do tytułu roboczego — stoją w Podglądzie (`JobPreviewDetails`), nie w wierszu.
 */
import { jobDisplayTitle, type JobNames } from "@/lib/job-names";
import { parseJobLocationCities } from "@/lib/job-search-prefill";
import { extractSkills } from "@/lib/job-skills";
import { officeDaysLabel } from "@/lib/office-days";
import { WORK_MODE_LABELS, type WorkMode } from "@/lib/work-mode";

/** Ten sam separator, którym `composeWorkingTitle` łączy człony tytułu. */
const SEPARATOR = " · ";
const MUST_IN_TITLE = 2;

export interface JobRowSource extends JobNames {
  /** `false` = tytuł roboczy wpisał człowiek; inaczej składa go automat. */
  working_title_auto?: boolean | null;
  must_skills?: unknown;
  remote_policy?: string | null;
  location?: string | null;
  onsite_days_per_week?: number | null;
  onsite_days_per_month?: number | null;
}

function clean(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function sameText(a: string, b: string): boolean {
  return a.toLocaleLowerCase("pl") === b.toLocaleLowerCase("pl");
}

/**
 * Nazwa stanowiska w wierszu. Tytuł roboczy z automatu ma kształt
 * „rola · must · lata · dziedzina” — wiersz pokazuje sam pierwszy człon.
 * Tytuł wpisany ręcznie zostaje w całości (ktoś chciał widzieć dokładnie to).
 */
export function jobRowTitle(job: JobRowSource): string {
  const full = jobDisplayTitle(job);
  const working = clean(job.working_title);
  if (!working || job.working_title_auto === false) return full;
  const first = working.split(SEPARATOR)[0].trim();
  if (!first) return full;
  // Rekrutacja bez roli: automat zaczyna tytuł od must-have („Java, Kafka”),
  // a to nie jest nazwa stanowiska — wtedy nazwa od klienta.
  const must = extractSkills(job.must_skills).slice(0, MUST_IN_TITLE).join(", ");
  if (must && sameText(first, must)) return clean(job.title) || full;
  return first;
}

function modeLabel(policy: string | null | undefined): string | null {
  return policy && policy in WORK_MODE_LABELS
    ? WORK_MODE_LABELS[policy as WorkMode]
    : null;
}

export interface JobWorkModeParts {
  /** „Zdalnie” / „Hybrydowo” / „Stacjonarnie”; `null` = rekrutacja bez trybu. */
  mode: string | null;
  /** Pierwsze miasto i „+N”; przy pracy zdalnej miasto nie ma znaczenia. */
  city: string | null;
}

/**
 * Tryb pracy w wierszu w dwóch częściach — wiersz przycina najpierw miasto,
 * a nazwę trybu zostawia całą.
 */
export function jobWorkModeParts(job: JobRowSource): JobWorkModeParts {
  const cities =
    job.remote_policy === "remote" ? [] : parseJobLocationCities(job.location);
  return {
    mode: modeLabel(job.remote_policy),
    city:
      cities.length > 1
        ? `${cities[0]} +${cities.length - 1}`
        : (cities[0] ?? null),
  };
}

/**
 * Tryb pracy jednym napisem: „Zdalnie”, „Hybrydowo · Warszawa +2”. Samo miasto
 * bez trybu też się liczy. `null` = rekrutacja nie ma ani trybu, ani miasta.
 */
export function jobWorkModeShort(job: JobRowSource): string | null {
  const { mode, city } = jobWorkModeParts(job);
  return [mode, city].filter(Boolean).join(SEPARATOR) || null;
}

/** Pełny zapis do Podglądu: tryb, dni w biurze i wszystkie miasta. */
export function jobWorkModeFull(job: JobRowSource): string | null {
  const mode = modeLabel(job.remote_policy);
  const days =
    job.remote_policy === "remote"
      ? null
      : officeDaysLabel(job.onsite_days_per_week, job.onsite_days_per_month);
  const cities =
    parseJobLocationCities(job.location).join(", ") || clean(job.location);
  return [mode, days, cities].filter(Boolean).join(SEPARATOR) || null;
}
