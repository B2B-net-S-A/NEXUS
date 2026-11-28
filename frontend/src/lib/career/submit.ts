/**
 * Wysyłka zgłoszenia ze strony kariery — wspólna dla formularzy oferty, listy
 * i strony rekrutera (`components/career/site/OfferApply`, `QuickApply`).
 * Jedna ścieżka: `POST /api/public/career/apply`
 * (multipart), gołym `fetch` — NIGDY przez klienta axios NEXUSA, który
 * dokleja token rekrutera.
 *
 * Komunikaty są małą literą (formularz terminala pisze je po `// `); formularz
 * oferty zaczyna je wielką literą.
 */
import { takeAltchaPayload, warmAltcha } from "@/lib/altcha";
import { messageFromApiResponse } from "@/lib/api-error";
import { applyFieldErrors } from "@/lib/apply-form-errors";

import { browserApiBase } from "./api";
import { copyConsents } from "./apply";

export type CareerField =
  | "first_name"
  | "last_name"
  | "email"
  | "cv"
  | "consent"
  | "expected_rate_hourly"
  | "availability_date"
  | "city"
  | "work_mode";

export const CAREER_FIELDS: readonly CareerField[] = [
  "cv",
  "first_name",
  "last_name",
  "email",
  "expected_rate_hourly",
  "availability_date",
  "city",
  "work_mode",
  "consent",
];

export type CareerFieldErrors = Partial<Record<CareerField, string>>;

export const LINK_GONE = "link wygasł albo rekrutacja jest już zamknięta";
export const CV_TOO_BIG = "CV jest większe niż 10 MB — zmniejsz plik";
export const CV_BAD_TYPE = "CV musi być plikiem pdf, doc lub docx";
export const NO_CONNECTION = "brak połączenia — sprawdź internet i spróbuj ponownie";
export const SCAN_UNAVAILABLE = "nie możemy teraz sprawdzić pliku — spróbuj ponownie za kilka minut";
export const NOT_CONFIRMED = "nie udało się potwierdzić wysyłki — odśwież stronę i wyślij ponownie";

/**
 * Zagadka ALTCHA (`lib/altcha`) zaczyna się liczyć przy pierwszym dotknięciu
 * formularza, żeby przy „Wyślij” była gotowa. Podgląd (`/preview/*`) nie woła.
 */
export function warmCareerSubmit(): void {
  warmAltcha(browserApiBase());
}

export type ApplyOutcome =
  | { ok: true; firstName: string; email: string }
  | { ok: false; fields: CareerFieldErrors; form: string | null };

/**
 * Treść multipart z pól formularza: zgody (`copyConsents`), pola opcjonalne
 * tylko wypełnione, pułapka na boty tylko wypełniona (backend przyjmuje wtedy
 * zgłoszenie po cichu bez zapisu) i UTM z pierwszego wejścia.
 */
export function careerPayload(
  fd: FormData,
  linkSlug: string,
  utm: Record<string, string>,
): FormData {
  const str = (name: string) => String(fd.get(name) ?? "").trim();
  const payload = new FormData();
  payload.set("link_slug", linkSlug);
  for (const key of ["first_name", "last_name", "email"] as const) {
    if (str(key)) payload.set(key, str(key));
  }
  payload.set("cv", fd.get("cv") as File);
  copyConsents(fd, payload);
  const rate = str("expected_rate_hourly").replace(",", ".");
  if (rate) payload.set("expected_rate_hourly", rate);
  if (str("availability_date")) payload.set("availability_date", str("availability_date"));
  if (str("city")) payload.set("city", str("city"));
  const mode = str("work_mode");
  if (mode && mode !== "any") payload.set("work_mode", mode);
  if (str("website")) payload.set("website", str("website"));
  for (const [key, value] of Object.entries(utm)) payload.set(key, value);
  return payload;
}

/** Wysyła zgłoszenie i tłumaczy odpowiedź API na błędy pól albo całego formularza. */
export async function sendCareerApplication(payload: FormData): Promise<ApplyOutcome> {
  try {
    payload.set("altcha", await takeAltchaPayload(browserApiBase()));
  } catch {
    return { ok: false, fields: {}, form: NO_CONNECTION };
  }
  let res: Response;
  try {
    res = await fetch(`${browserApiBase()}/api/public/career/apply`, {
      method: "POST",
      body: payload,
    });
  } catch {
    return { ok: false, fields: {}, form: NO_CONNECTION };
  }
  if (res.status === 201 || res.status === 200) {
    const done = (await res.json().catch(() => ({}))) as { first_name?: string; email?: string };
    return {
      ok: true,
      firstName: (done.first_name ?? "").trim(),
      email: (done.email ?? String(payload.get("email") ?? "")).trim(),
    };
  }
  if (res.status === 404) return { ok: false, fields: {}, form: LINK_GONE };
  if (res.status === 413) return { ok: false, fields: { cv: CV_TOO_BIG }, form: null };
  if (res.status === 415) return { ok: false, fields: { cv: CV_BAD_TYPE }, form: null };
  if (res.status === 429) {
    return { ok: false, fields: {}, form: "za dużo prób z tego adresu — spróbuj ponownie za kilka minut" };
  }
  // Skaner antywirusowy chwilowo niedostępny (publiczny formularz nie przyjmuje
  // pliku bez skanu) — `docs/claude/podstawy/skan-plikow-i-altcha.md`.
  if (res.status === 503) return { ok: false, fields: {}, form: SCAN_UNAVAILABLE };
  const body: unknown = await res.json().catch(() => ({}));
  // Zagadka ALTCHA nie przeszła (wygasła, powtórka) — zdanie w stylu formularza.
  if (res.status === 400 && isAltchaRejection(body)) {
    return { ok: false, fields: {}, form: NOT_CONFIRMED };
  }
  const fieldErrors = applyFieldErrors(body);
  if (fieldErrors.length > 0) {
    const fields: CareerFieldErrors = {};
    let form: string | null = null;
    for (const fe of fieldErrors) {
      if (fe.field === "link_slug") form = LINK_GONE;
      else if ((CAREER_FIELDS as readonly string[]).includes(fe.field)) {
        fields[fe.field as CareerField] = fe.message;
      }
    }
    if (Object.keys(fields).length > 0 || form) return { ok: false, fields, form };
  }
  return {
    ok: false,
    fields: {},
    form: messageFromApiResponse(res.status, body) ?? "coś poszło nie tak — spróbuj ponownie",
  };
}

function isAltchaRejection(body: unknown): boolean {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" && detail.startsWith("Nie udało się potwierdzić wysyłki");
}
