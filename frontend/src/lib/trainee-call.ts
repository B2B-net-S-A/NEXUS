/**
 * „Telefony na dziś” — czysta logika ekranu praktykanta (0371).
 *
 * Bez Reacta i bez sieci: stan formularza rozmowy → ciało żądania, walidacja,
 * etykiety braków i wyników, kolejność listy. Komponenty tylko to renderują.
 */

import type {
  B2bWillingness,
  CallAvailability,
  OpenToOffers,
  RateUnit,
  RemoteMode,
  TraineeCallBody,
  TraineeItem,
  TraineeItemFacts,
  TraineeMissingCode,
  TraineeOutcome,
  TraineeToday,
  WorkTimePreference,
} from "@/lib/api/trainee";

// ── Etykiety ─────────────────────────────────────────────────────────────────

export const MISSING_LABEL: Record<TraineeMissingCode, string> = {
  rate_missing: "brak minimalnej stawki",
  rate_stale: "stawka nieaktualna",
  b2b: "B2B?",
  work_time: "full-time czy part-time?",
  work_mode: "brak trybu pracy",
  below_min_consent: "zgoda poniżej stawki?",
  office_consent: "zgoda na więcej dni w biurze?",
  availability: "brak dostępności",
};

/** Nieznany kod z backendu (nowa reguła) nie może wyjść surowym napisem. */
export function missingLabel(code: string): string {
  return MISSING_LABEL[code as TraineeMissingCode] ?? "brak danych w profilu";
}

export const OUTCOME_LABEL: Record<TraineeOutcome, string> = {
  call: "Rozmowa",
  noanswer: "Nie odbiera (2 próby)",
  later: "Telefon innego dnia",
  wrong: "Zły numer",
  declined: "Niezainteresowany",
};

export const B2B_OPTIONS: ReadonlyArray<{ value: B2bWillingness; label: string }> = [
  { value: "b2b", label: "Tak, już na B2B" },
  { value: "would_switch", label: "Tak, przejdzie z etatu" },
  { value: "employment_only", label: "Nie, tylko etat" },
];

export const YES_NO_CALL_OPTIONS: ReadonlyArray<{ value: boolean; label: string }> = [
  { value: true, label: "Tak, dzwonić" },
  { value: false, label: "Nie dzwonić" },
];

export const REMOTE_MODE_OPTIONS: ReadonlyArray<{ value: RemoteMode; label: string }> = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybrydowo" },
  { value: "onsite", label: "Biuro" },
];

export const WORK_TIME_OPTIONS: ReadonlyArray<{ value: WorkTimePreference; label: string }> = [
  { value: "full_time_only", label: "Tylko full-time" },
  { value: "also_part_time", label: "Też part-time" },
  { value: "part_time_only", label: "Tylko part-time" },
];

export const AVAILABILITY_OPTIONS: ReadonlyArray<{ value: CallAvailability; label: string }> = [
  { value: "now", label: "Od zaraz" },
  { value: "within_1m", label: "Do 1 mies." },
  { value: "within_3m", label: "1–3 mies." },
  { value: "later", label: "Później" },
];

export const OPEN_TO_OFFERS_OPTIONS: ReadonlyArray<{ value: OpenToOffers; label: string }> = [
  { value: "yes", label: "Tak, szuka" },
  { value: "maybe", label: "Rozważy" },
  { value: "no", label: "Nie teraz" },
];

export const RATE_UNIT_OPTIONS: ReadonlyArray<{ value: RateUnit; label: string }> = [
  { value: "hour", label: "zł / godz." },
  { value: "day", label: "zł / dzień (MD)" },
  { value: "month", label: "zł / mies." },
];

export const WANTS_MAX = 1000;

// ── Formularz rozmowy ────────────────────────────────────────────────────────

export interface TraineeCallForm {
  b2b: B2bWillingness | null;
  /** Tekst z pola — dopiero walidacja zamienia go na liczbę. */
  rateValue: string;
  rateUnit: RateUnit;
  acceptsBelowMin: boolean | null;
  remoteModes: RemoteMode[];
  maxOnsiteDays: string;
  officeCities: string;
  acceptsMoreOfficeDays: boolean | null;
  workTime: WorkTimePreference | null;
  availability: CallAvailability | null;
  openToOffers: OpenToOffers | null;
  wants: string;
}

/**
 * Formularz startuje PUSTY. Praktykant ma zapytać, a nie przepisać, co już
 * jest — stare dane pokazujemy obok pola („W profilu: …”).
 */
export function emptyCallForm(): TraineeCallForm {
  return {
    b2b: null,
    rateValue: "",
    rateUnit: "hour",
    acceptsBelowMin: null,
    remoteModes: [],
    maxOnsiteDays: "",
    officeCities: "",
    acceptsMoreOfficeDays: null,
    workTime: null,
    availability: null,
    openToOffers: null,
    wants: "",
  };
}

/** Kliknięcie wybranej opcji zdejmuje wybór (jak w makiecie). */
export function toggleValue<T>(current: T | null, next: T): T | null {
  return current === next ? null : next;
}

export function toggleInList<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** „Nie, tylko etat” — reszta formularza nie ma znaczenia. */
export function isEmploymentOnly(form: Pick<TraineeCallForm, "b2b">): boolean {
  return form.b2b === "employment_only";
}

/**
 * Liczba z pola stawki: „135”, „135,50”, „1 400”. `null` = puste pole,
 * `NaN` = coś, czego nie da się przeczytać jako kwoty.
 */
export function parseRate(raw: string): number | null {
  const cleaned = raw.replace(/[\s ]/g, "").replace(",", ".");
  if (cleaned === "") return null;
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return Number.NaN;
  return Number(cleaned);
}

export function parseOnsiteDays(raw: string): number | null {
  const cleaned = raw.trim();
  if (cleaned === "") return null;
  if (!/^\d+$/.test(cleaned)) return Number.NaN;
  return Number(cleaned);
}

/** „Kraków; zdalnie z całej Polski” → ["Kraków", "zdalnie z całej Polski"]. */
export function parseCities(raw: string): string[] {
  return raw
    .split(/[;,\n]/)
    .map((c) => c.trim())
    .filter(Boolean);
}

export type CallFormField = "b2b" | "rate" | "maxOnsiteDays" | "wants";

export interface CallFormValidation {
  ok: boolean;
  errors: Partial<Record<CallFormField, string>>;
}

export function validateCallForm(form: TraineeCallForm): CallFormValidation {
  const errors: CallFormValidation["errors"] = {};
  if (form.b2b === null) {
    errors.b2b = "Zaznacz, czy pracuje na B2B — bez tego rozmowy nie da się zapisać.";
  }
  if (!isEmploymentOnly(form)) {
    const rate = parseRate(form.rateValue);
    if (rate !== null && (!Number.isFinite(rate) || rate <= 0)) {
      errors.rate = "Stawka musi być liczbą większą od zera.";
    }
    const days = parseOnsiteDays(form.maxOnsiteDays);
    if (days !== null && (!Number.isFinite(days) || days < 0 || days > 5)) {
      errors.maxOnsiteDays = "Dni w biurze: od 0 do 5.";
    }
    if (form.wants.trim().length > WANTS_MAX) {
      errors.wants = `Najwyżej ${WANTS_MAX} znaków.`;
    }
  }
  return { ok: Object.keys(errors).length === 0, errors };
}

/**
 * Ciało `POST /items/{id}/call`. Przy „tylko etat” backend ignoruje resztę —
 * i tak wysyłamy puste wartości, żeby ukryte pola nie przemyciły danych.
 * Wołać po `validateCallForm` (brak B2B rzuca).
 */
export function toCallBody(form: TraineeCallForm): TraineeCallBody {
  if (form.b2b === null) {
    throw new Error("Brak odpowiedzi o B2B — najpierw validateCallForm.");
  }
  if (isEmploymentOnly(form)) {
    return {
      b2b_willingness: "employment_only",
      min_rate: null,
      accepts_below_min_rate: null,
      remote_modes: [],
      max_onsite_days: null,
      accepts_more_office_days: null,
      office_cities: [],
      work_time_preference: null,
      availability: null,
      open_to_offers: null,
      wants: null,
    };
  }
  const rate = parseRate(form.rateValue);
  const days = parseOnsiteDays(form.maxOnsiteDays);
  const wants = form.wants.trim();
  return {
    b2b_willingness: form.b2b,
    min_rate:
      rate !== null && Number.isFinite(rate) && rate > 0
        ? { value: rate, unit: form.rateUnit }
        : null,
    accepts_below_min_rate: form.acceptsBelowMin,
    remote_modes: [...form.remoteModes],
    max_onsite_days: days !== null && Number.isFinite(days) ? days : null,
    accepts_more_office_days: form.acceptsMoreOfficeDays,
    office_cities: parseCities(form.officeCities),
    work_time_preference: form.workTime,
    availability: form.availability,
    open_to_offers: form.openToOffers,
    wants: wants === "" ? null : wants,
  };
}

// ── Stawka w profilu ─────────────────────────────────────────────────────────

function monthYear(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`;
}

const PLN = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 2 });

/** „140 zł/h — z 03.2025, nieaktualna” albo „brak”. */
export function profileRateLabel(item: Pick<TraineeItem, "facts" | "reasons">): string {
  const rate = item.facts.min_rate_hourly;
  if (rate == null) return "brak";
  const parts = [`${PLN.format(rate)} zł/h`];
  const when = monthYear(item.facts.rate_updated_at);
  const stale = item.reasons.missing.includes("rate_stale");
  if (when) parts.push(`z ${when}${stale ? ", nieaktualna" : ""}`);
  else if (stale) parts.push("nieaktualna");
  return parts.join(" — ");
}

// ── Lista ────────────────────────────────────────────────────────────────────

export function isClosed(item: Pick<TraineeItem, "closed_at">): boolean {
  return item.closed_at != null;
}

/** Pierwsza próba bez odpowiedzi, czeka na ponowny telefon. */
export function isWaitingForRetry(
  item: Pick<TraineeItem, "closed_at" | "retry_after">,
): boolean {
  return !isClosed(item) && item.retry_after != null;
}

/**
 * Kolejność serwera zostaje (otwarte → odłożone → zamknięte); tu tylko podział
 * na zakładki. Odłożone („zadzwoń ponownie po…”) są w „Do zrobienia” na końcu.
 */
export function splitItems(items: readonly TraineeItem[]): {
  open: TraineeItem[];
  closed: TraineeItem[];
} {
  const fresh = items.filter((i) => !isClosed(i) && !isWaitingForRetry(i));
  const waiting = items.filter(isWaitingForRetry);
  const closed = items.filter(isClosed);
  return { open: [...fresh, ...waiting], closed };
}

/**
 * Następna osoba po zapisie: pierwsza otwarta inna niż bieżąca. Osoba, do
 * której trzeba zadzwonić ponownie PÓŹNIEJ, idzie dopiero, gdy nikogo innego
 * nie ma — inaczej praktykant dzwoniłby do niej zaraz po pierwszej próbie.
 */
export function nextOpenItemId(
  items: readonly TraineeItem[],
  currentId: number | null,
  now: Date = new Date(),
): number | null {
  const { open } = splitItems(items);
  const others = open.filter((i) => i.id !== currentId);
  const ready = others.find(
    (i) => !i.retry_after || new Date(i.retry_after).getTime() <= now.getTime(),
  );
  return (ready ?? others[0])?.id ?? null;
}

const RETRY_DELAY_MS = 3 * 60 * 60 * 1000;

function clock(date: Date): string {
  return date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

/**
 * „1. próba 10:42 — zadzwoń ponownie po 13:42”. Godzinę próby liczymy
 * z `retry_after` (backend odkłada o 3 h), bo API jej osobno nie podaje.
 */
export function retryLabel(item: Pick<TraineeItem, "retry_after" | "closed_at">): string | null {
  if (!isWaitingForRetry(item) || !item.retry_after) return null;
  const retry = new Date(item.retry_after);
  if (Number.isNaN(retry.getTime())) return null;
  const tried = new Date(retry.getTime() - RETRY_DELAY_MS);
  return `1. próba ${clock(tried)} — zadzwoń ponownie po ${clock(retry)}`;
}

/** Liczniki z pozycji — ta sama reguła co serwer, żeby UI nie czekał. */
export function recountToday(today: TraineeToday): TraineeToday {
  const closed = today.items.filter(isClosed);
  const count = (outcome: TraineeOutcome) =>
    closed.filter((i) => i.outcome === outcome).length;
  const total = Math.max(today.counts.total, today.items.length);
  return {
    ...today,
    counts: {
      total,
      closed: closed.length,
      open: total - closed.length,
      call: count("call"),
      noanswer: count("noanswer"),
      later: count("later"),
      wrong: count("wrong"),
      declined: count("declined"),
    },
  };
}

/**
 * Pełny profil po rozmowie: wiadomo, czy B2B, a przy B2B — stawka, tryb
 * pracy, wymiar i dostępność. „Tylko etat” jest kompletny sam w sobie.
 */
export function isCompleteProfile(facts: TraineeItemFacts): boolean {
  if (facts.b2b_willingness === "employment_only") return true;
  return (
    facts.b2b_willingness != null &&
    facts.min_rate_hourly != null &&
    facts.remote_modes.length > 0 &&
    facts.work_time_preference != null &&
    facts.availability_status != null &&
    facts.availability_status !== "unknown"
  );
}

export function telHref(phone: string | null): string | null {
  if (!phone) return null;
  const digits = phone.replace(/[^\d+]/g, "");
  return digits ? `tel:${digits}` : null;
}

/** „Pasuje do 6 rekrutacji z ostatnich 18 miesięcy (Java, Spring). 2 z nich są otwarte teraz.” */
export function whyThisPerson(
  reasons: TraineeItem["reasons"],
  windowMonths = 18,
): string {
  const stack = reasons.stack.length ? ` (${reasons.stack.join(", ")})` : "";
  const open =
    reasons.open_fits === 0
      ? "Żadna nie jest dziś otwarta."
      : reasons.open_fits === 1
        ? "1 z nich jest otwarta teraz."
        : `${reasons.open_fits} z nich są otwarte teraz.`;
  return `Pasuje do ${reasons.fits} rekrutacji z ostatnich ${windowMonths} miesięcy${stack}. ${open}`;
}

/** „14 mies. temu”, „2 lata temu”, „nigdy”. */
export function lastContactLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "brak";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "brak";
  const months =
    (now.getFullYear() - date.getFullYear()) * 12 + (now.getMonth() - date.getMonth());
  if (months < 1) return "w tym miesiącu";
  if (months < 24) return `${months} mies. temu`;
  const years = Math.floor(months / 12);
  return `${years} ${years <= 4 ? "lata" : "lat"} temu`;
}

// ── Telefon innego dnia ──────────────────────────────────────────────────────

function isoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseIsoDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return isoDate(date) === value ? date : null;
}

function isWeekend(date: Date): boolean {
  const day = date.getDay();
  return day === 0 || day === 6;
}

/** Najbliższy dzień roboczy po `today` (bez weekendów; święta sprawdza serwer). */
export function nextBusinessDay(today: string): string {
  const start = parseIsoDate(today) ?? new Date();
  const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1);
  while (isWeekend(date)) date.setDate(date.getDate() + 1);
  return isoDate(date);
}

/** `null` = data poprawna; inaczej komunikat po polsku. */
export function laterDateError(value: string, today: string): string | null {
  const date = parseIsoDate(value);
  if (!date) return "Wybierz datę.";
  const base = parseIsoDate(today);
  if (base && date.getTime() <= base.getTime()) return "Wybierz dzień po dzisiejszym.";
  if (isWeekend(date)) return "Wybierz dzień roboczy — sobota i niedziela odpadają.";
  return null;
}

// ── Przekazanie rekruterowi ──────────────────────────────────────────────────

const B2B_NOTE: Record<B2bWillingness, string> = {
  b2b: "Pracuje na B2B.",
  would_switch: "Przejdzie z etatu na B2B.",
  employment_only: "Tylko etat — nie przejdzie na B2B.",
};

const WORK_TIME_NOTE: Record<WorkTimePreference, string> = {
  full_time_only: "Tylko full-time.",
  also_part_time: "Full-time albo part-time.",
  part_time_only: "Tylko part-time.",
};

const AVAILABILITY_NOTE: Record<CallAvailability, string> = {
  now: "Może zacząć od zaraz.",
  within_1m: "Może zacząć w ciągu miesiąca.",
  within_3m: "Może zacząć za 1–3 miesiące.",
  later: "Może zacząć później niż za 3 miesiące.",
};

const OPEN_NOTE: Record<OpenToOffers, string> = {
  yes: "Szuka projektu.",
  maybe: "Rozważy projekt.",
  no: "Teraz nie szuka.",
};

const REMOTE_NOTE: Record<RemoteMode, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "w biurze",
};

const UNIT_NOTE: Record<RateUnit, string> = {
  hour: "zł/h",
  day: "zł/dzień",
  month: "zł/mies.",
};

/**
 * Szkic notatki dla rekrutera z formularza rozmowy (praktykant poprawia ją
 * w oknie „Przekaż rekruterowi”). Tylko fakty z rozmowy, bez ocen.
 */
export function handoverNoteFromForm(form: TraineeCallForm): string {
  const lines: string[] = [];
  if (form.openToOffers) lines.push(OPEN_NOTE[form.openToOffers]);
  if (form.b2b) lines.push(B2B_NOTE[form.b2b]);
  if (!isEmploymentOnly(form)) {
    const rate = parseRate(form.rateValue);
    if (rate !== null && Number.isFinite(rate) && rate > 0) {
      const below =
        form.acceptsBelowMin === true
          ? " — przy niższym budżecie można dzwonić"
          : form.acceptsBelowMin === false
            ? " — poniżej nie dzwonić"
            : "";
      lines.push(`Minimum ${PLN.format(rate)} ${UNIT_NOTE[form.rateUnit]} netto B2B${below}.`);
    }
    if (form.workTime) lines.push(WORK_TIME_NOTE[form.workTime]);
    const modes = form.remoteModes.map((m) => REMOTE_NOTE[m]);
    const days = parseOnsiteDays(form.maxOnsiteDays);
    const cities = parseCities(form.officeCities);
    if (modes.length || (days !== null && Number.isFinite(days)) || cities.length) {
      const parts: string[] = [];
      if (modes.length) parts.push(`Tryb: ${modes.join(" / ")}`);
      if (days !== null && Number.isFinite(days)) parts.push(`maks. ${days} dni w biurze`);
      if (cities.length) parts.push(`dojazd: ${cities.join(", ")}`);
      const more =
        form.acceptsMoreOfficeDays === true
          ? ", przy większej liczbie dni można dzwonić"
          : form.acceptsMoreOfficeDays === false
            ? ", więcej nie"
            : "";
      lines.push(`${parts.join(", ")}${more}.`);
    }
    if (form.availability) lines.push(AVAILABILITY_NOTE[form.availability]);
  }
  const wants = form.wants.trim();
  if (wants) lines.push(wants);
  return lines.join(" ").slice(0, WANTS_MAX);
}

/** Szkic notatki z faktów zapisanych w profilu (pozycja już zamknięta). */
export function handoverNoteFromFacts(facts: TraineeItemFacts): string {
  const lines: string[] = [];
  if (facts.b2b_willingness) lines.push(B2B_NOTE[facts.b2b_willingness]);
  if (facts.b2b_willingness !== "employment_only") {
    if (facts.min_rate_hourly != null) {
      const below =
        facts.accepts_below_min_rate === true
          ? " — przy niższym budżecie można dzwonić"
          : facts.accepts_below_min_rate === false
            ? " — poniżej nie dzwonić"
            : "";
      lines.push(`Minimum ${PLN.format(facts.min_rate_hourly)} zł/h netto B2B${below}.`);
    }
    if (facts.work_time_preference) lines.push(WORK_TIME_NOTE[facts.work_time_preference]);
    const modes = facts.remote_modes.map((m) => REMOTE_NOTE[m]).filter(Boolean);
    const parts: string[] = [];
    if (modes.length) parts.push(`Tryb: ${modes.join(" / ")}`);
    if (facts.max_onsite_days != null) parts.push(`maks. ${facts.max_onsite_days} dni w biurze`);
    if (facts.office_cities.length) parts.push(`dojazd: ${facts.office_cities.join(", ")}`);
    if (parts.length) lines.push(`${parts.join(", ")}.`);
  }
  return lines.join(" ").slice(0, WANTS_MAX);
}
