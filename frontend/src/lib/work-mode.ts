/**
 * Tryb pracy kandydata: tryby akceptowane + ile dni w biurze (22.09.2026).
 *
 * Lustro reguły z `backend/app/services/candidate_notes_facts.py`: kandydat,
 * który akceptuje N dni w biurze, akceptuje każdą pracę wymagającą co
 * najwyżej N dni (0 = zdalnie, 1–4 = też hybrydowo, 5+ = też stacjonarnie).
 * Dzięki temu profil bez zapisanych trybów, ale z liczbą dni (np. wpisaną
 * wcześniej z notatek), nadal mówi, jak kandydat może pracować.
 */

import { formatIsoDatePl } from "@/lib/date-pl";

export type WorkMode = "remote" | "hybrid" | "onsite";

export const WORK_MODES: readonly WorkMode[] = ["remote", "hybrid", "onsite"];

export const WORK_MODE_LABELS: Record<WorkMode, string> = {
  remote: "Zdalnie",
  hybrid: "Hybrydowo",
  onsite: "Stacjonarnie",
};

const FULL_OFFICE_DAYS = 5;

export function orderedWorkModes(values: unknown): WorkMode[] {
  if (!Array.isArray(values)) return [];
  const wanted = new Set(
    values
      .filter((v): v is string => typeof v === "string")
      .map((v) => v.trim().toLowerCase()),
  );
  return WORK_MODES.filter((mode) => wanted.has(mode));
}

export function modesForOfficeDays(days: number): WorkMode[] {
  const modes: WorkMode[] = ["remote"];
  if (days >= 1) modes.push("hybrid");
  if (days >= FULL_OFFICE_DAYS) modes.push("onsite");
  return modes;
}

function validDays(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 7
    ? value
    : null;
}

/** Tryb pracy z profilu: `preferences.remote_modes` + kolumna dni w biurze. */
export function profileWorkMode(
  preferences: unknown,
  maxOnsiteDays: unknown,
): { modes: WorkMode[]; days: number | null } {
  const prefs =
    preferences && typeof preferences === "object" && !Array.isArray(preferences)
      ? (preferences as Record<string, unknown>)
      : {};
  return {
    modes: orderedWorkModes(prefs.remote_modes),
    days: validDays(maxOnsiteDays),
  };
}

function officeDaysPhrase(days: number): string {
  if (days === 1) return "do 1 dnia w biurze w tygodniu";
  return `do ${days} dni w biurze w tygodniu`;
}

function joinModes(modes: WorkMode[]): string {
  // Od najbardziej „biurowego” — to on jest informacją, reszta ją uzupełnia.
  const labels = [...modes].reverse().map((mode, index) => {
    const label = WORK_MODE_LABELS[mode];
    return index === 0 ? label : label.toLowerCase();
  });
  if (labels.length <= 1) return labels[0] ?? "";
  return `${labels.slice(0, -1).join(", ")} lub ${labels[labels.length - 1]}`;
}

/**
 * Zdanie do profilu, np. „Hybrydowo lub zdalnie · do 2 dni w biurze w tygodniu”.
 * `null` = nic nie wiadomo (profil pokazuje wtedy „Nie uzupełniono”).
 */
export function formatWorkMode(
  modesInput: readonly WorkMode[],
  days: number | null,
): string | null {
  let modes = [...modesInput];
  if (modes.length === 0 && days != null) modes = modesForOfficeDays(days);
  if (modes.length === 0) return null;
  if (days === 0 || (modes.length === 1 && modes[0] === "remote" && days == null)) {
    return "Tylko zdalnie";
  }
  const head = joinModes(modes);
  if (days != null) return `${head} · ${officeDaysPhrase(days)}`;
  if (modes.includes("hybrid") || modes.includes("onsite")) {
    return `${head} · liczba dni w biurze nieustalona`;
  }
  return head;
}

/** Walidacja formularza — lustro `CandidateWorkModeUpdate` po stronie serwera. */
export function workModeValidationError(
  modes: readonly WorkMode[],
  days: number | null,
): string | null {
  if (days == null || modes.length === 0) return null;
  const set = new Set(modes);
  if (set.size === 1 && set.has("remote") && days > 0) {
    return "Tylko zdalnie oznacza 0 dni w biurze — popraw tryb albo liczbę dni.";
  }
  if (days === 0 && (set.has("hybrid") || set.has("onsite"))) {
    return "0 dni w biurze oznacza pracę wyłącznie zdalną — odznacz hybrydę i pracę stacjonarną albo podaj liczbę dni.";
  }
  return null;
}

// ── Odrzucenie „Nie akceptuje trybu pracy” (14.10.2026) ────────────────────

/** Najwięcej dni w biurze do wyboru w oknie odrzucenia — 5 to już biuro. */
export const MAX_REJECTION_OFFICE_DAYS = 4;

/**
 * Ile dni w biurze można wskazać przy odrzuceniu za tryb pracy: tylko mniej,
 * niż wymaga rekrutacja (tyle samo albo więcej nie byłoby powodem), a gdy
 * wymóg jest nieznany — od 0 do 4.
 */
export function officeDaysChoices(requiredDays: number | null | undefined): number[] {
  const known =
    typeof requiredDays === "number" && Number.isInteger(requiredDays) && requiredDays >= 1;
  const top = known
    ? Math.min(requiredDays - 1, MAX_REJECTION_OFFICE_DAYS)
    : MAX_REJECTION_OFFICE_DAYS;
  return Array.from({ length: top + 1 }, (_, days) => days);
}

/** „Tylko zdalnie”, „Do 1 dnia”, „Do 3 dni”. */
export function officeDaysChoiceLabel(days: number): string {
  if (days === 0) return "Tylko zdalnie";
  return days === 1 ? "Do 1 dnia" : `Do ${days} dni`;
}

/** Tryb pracy zapisany na profilu po odrzuceniu z wybraną liczbą dni. */
export function workModeAfterRejection(days: number): string {
  return formatWorkMode(modesForOfficeDays(days), days) ?? "";
}

const JOB_POLICY_LABELS: Record<WorkMode, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "stacjonarnie",
};

/** „hybrydowo · 2 dni w biurze w tygodniu” — `null`, gdy nic nie wiadomo. */
export function jobWorkModeLine(
  remotePolicy: string | null | undefined,
  onsiteDays: number | null | undefined,
): string | null {
  const policy =
    remotePolicy && remotePolicy in JOB_POLICY_LABELS
      ? JOB_POLICY_LABELS[remotePolicy as WorkMode]
      : null;
  const days =
    typeof onsiteDays === "number" && onsiteDays > 0
      ? onsiteDays === 1
        ? "1 dzień w biurze w tygodniu"
        : `${onsiteDays} dni w biurze w tygodniu`
      : null;
  const parts = [policy, days].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** Klucz źródła trybu pracy w `preferences` — lustro `WORK_MODE_ORIGIN_KEY`. */
export const WORK_MODE_ORIGIN_KEY = "_work_mode_origin";

/**
 * „z odrzucenia · 14.10.2026 · Java Developer” pod „Tryb pracy” na profilu.
 * Serwer zdejmuje źródło przy każdej innej zmianie trybu pracy, więc jego
 * obecność znaczy, że wartość wciąż pochodzi z tego odrzucenia.
 */
export function rejectionWorkModeOrigin(
  preferences: unknown,
): { text: string; title: string } | undefined {
  if (!preferences || typeof preferences !== "object" || Array.isArray(preferences)) {
    return undefined;
  }
  const origin = (preferences as Record<string, unknown>)[WORK_MODE_ORIGIN_KEY];
  if (!origin || typeof origin !== "object") return undefined;
  const { source, at, job_title: jobTitle, by_name: byName } = origin as Record<
    string,
    unknown
  >;
  if (source !== "rejection") return undefined;
  const date = typeof at === "string" ? formatIsoDatePl(at) : null;
  const title = typeof jobTitle === "string" && jobTitle.trim() ? jobTitle.trim() : null;
  const text = ["z odrzucenia", date && date !== "—" ? date : null, title]
    .filter(Boolean)
    .join(" · ");
  const author = typeof byName === "string" && byName.trim() ? byName.trim() : null;
  return {
    text,
    title: ["Powód odrzucenia: Nie akceptuje trybu pracy", author, title]
      .filter(Boolean)
      .join(" · "),
  };
}
