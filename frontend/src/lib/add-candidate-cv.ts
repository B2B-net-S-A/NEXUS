/**
 * „Dodaj kandydata” zaczynane od CV (29.09.2026).
 *
 * Okno wysyła plik do `POST /api/candidates/cv/preview` (odczyt bez zapisu),
 * uzupełnia PUSTE pola formularza, a zapis idzie przez `POST /from-cv`
 * z polami formularza — serwer bierze ten sam odczyt z pamięci procesu,
 * więc model płaci raz. Reszta formularza (tagi, preferencje…) jedzie w tym
 * samym żądaniu (pole `candidate`) — jedna transakcja, bez PATCH-a.
 */

export interface CandidateCvPreview {
  cv_sha256: string;
  name: string | null;
  lastname: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  linkedin: string | null;
  current_position: string | null;
  confidence: Record<string, number>;
  source: string | null;
}

/** Pola formularza, które odczyt CV umie wypełnić i które `/from-cv` przyjmuje. */
export const CV_FORM_FIELDS = ["name", "lastname", "email", "phone", "city", "linkedin"] as const;
export type CvFormField = (typeof CV_FORM_FIELDS)[number];

export const CV_FIELD_LABELS: Record<CvFormField, string> = {
  name: "imię",
  lastname: "nazwisko",
  email: "e-mail",
  phone: "telefon",
  city: "miasto",
  linkedin: "LinkedIn",
};

export const CV_ACCEPT = ".pdf,.doc,.docx,.odt,.rtf,.txt";

/**
 * Uzupełnia WYŁĄCZNIE puste pola — to, co rekruter zdążył wpisać, zostaje.
 * Zwraca listę wypełnionych pól (do zdania „Uzupełniono z CV: …”).
 */
export function fillEmptyFromCv<T extends Record<CvFormField, string>>(
  form: T,
  preview: CandidateCvPreview,
): { form: T; filled: CvFormField[] } {
  const next = { ...form };
  const filled: CvFormField[] = [];
  for (const field of CV_FORM_FIELDS) {
    const value = preview[field]?.trim();
    if (value && !form[field].trim()) {
      next[field] = value as T[CvFormField];
      filled.push(field);
    }
  }
  return { form: next, filled };
}

/** Pola, dla których odczyt CV dał wartość — tylko je da się „wyczyścić”. */
export function cvKnownFields(preview: CandidateCvPreview | null | undefined): CvFormField[] {
  if (!preview) return [];
  return CV_FORM_FIELDS.filter((field) => Boolean(preview[field]?.trim()));
}

/**
 * Pola formularza dla `/from-cv` — wpisane przez rekrutera wygrywają z odczytem.
 * Pole, które odczyt CV znał (`known`), a rekruter je wyczyścił, idzie jako
 * jawne `""`: serwer NIE wstawia wtedy wartości z CV (ani do profilu, ani do
 * skanu duplikatów). Puste pole bez wartości w CV nie jest wysyłane.
 */
export function fromCvOverrides(
  form: Record<CvFormField, string>,
  known: readonly CvFormField[] = [],
): Partial<Record<CvFormField, string>> {
  const out: Partial<Record<CvFormField, string>> = {};
  for (const field of CV_FORM_FIELDS) {
    const value = form[field].trim();
    if (value) out[field] = value;
    else if (known.includes(field)) out[field] = "";
  }
  return out;
}

/** Klucze formularza zmienione względem pustego formularza (poza pominiętymi). */
export function changedFormKeys<T extends Record<string, unknown>>(
  form: T,
  empty: T,
  skip: ReadonlySet<string>,
): string[] {
  return Object.keys(empty).filter(
    (key) => !skip.has(key) && JSON.stringify(form[key]) !== JSON.stringify(empty[key]),
  );
}

const PAYLOAD_KEYS: Record<string, string[]> = {
  notice_period: ["notice_period", "notice_period_unit"],
  notice_period_unit: ["notice_period", "notice_period_unit"],
};

/**
 * Reszta formularza dla `/from-cv` (pole `candidate`, JSON) — tylko to, co
 * rekruter faktycznie ustawił. Serwer waliduje ją jak `POST /api/candidates`
 * i zapisuje w TEJ SAMEJ transakcji co kandydata. Preferencje bez pustych
 * kluczy — nie ma czego czyścić.
 */
export function extraFieldsForCv(
  payload: Record<string, unknown>,
  changed: readonly string[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  let preferencesChanged = false;
  for (const key of changed) {
    if (key.startsWith("pref_")) {
      preferencesChanged = true;
      continue;
    }
    for (const payloadKey of PAYLOAD_KEYS[key] ?? [key]) {
      if (payload[payloadKey] !== undefined) out[payloadKey] = payload[payloadKey];
    }
  }
  if (preferencesChanged && payload.preferences && typeof payload.preferences === "object") {
    const prefs = Object.fromEntries(
      Object.entries(payload.preferences as Record<string, unknown>).filter(
        ([, value]) => value !== null && value !== undefined,
      ),
    );
    if (Object.keys(prefs).length) out.preferences = prefs;
  }
  return out;
}

export interface CvDuplicateMatch {
  candidate_id: number;
  name: string;
  lastname: string;
  email: string | null;
  match_score: number;
  match_reasons: string[];
}

/**
 * 409 z `/cv/preview` i `/from-cv` (`{detail: {matches: [...]}}`) → lista
 * trafień; każda inna odpowiedź → `null`.
 */
export function duplicateMatchesFromConflict(error: unknown): CvDuplicateMatch[] | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | null)?.detail;
  const matches = (detail as { matches?: unknown } | null)?.matches;
  if (!Array.isArray(matches)) return null;
  return matches
    .filter(
      (m): m is CvDuplicateMatch =>
        !!m && typeof m === "object" && typeof (m as CvDuplicateMatch).candidate_id === "number",
    )
    .map((m) => ({
      candidate_id: m.candidate_id,
      name: typeof m.name === "string" ? m.name : "",
      lastname: typeof m.lastname === "string" ? m.lastname : "",
      email: typeof m.email === "string" ? m.email : null,
      match_score: typeof m.match_score === "number" ? m.match_score : 0,
      match_reasons: Array.isArray(m.match_reasons)
        ? m.match_reasons.filter((r): r is string => typeof r === "string")
        : [],
    }));
}
