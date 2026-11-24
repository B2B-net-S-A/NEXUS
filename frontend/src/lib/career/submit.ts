/**
 * Wysyłka zgłoszenia ze strony kariery — wspólna dla formularza oferty
 * (`components/career/site/OfferApply`) i formularza strony rekrutera
 * (`CareerApplyForm`). Jedna ścieżka: `POST /api/public/career/apply`
 * (multipart), gołym `fetch` — NIGDY przez klienta axios NEXUSA, który
 * dokleja token rekrutera.
 *
 * Komunikaty są małą literą (formularz terminala pisze je po `// `); formularz
 * oferty zaczyna je wielką literą.
 */
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
  let res: Response;
  try {
    res = await fetch(`${browserApiBase()}/api/public/career/apply`, {
      method: "POST",
      body: payload,
    });
  } catch {
    return { ok: false, fields: {}, form: "brak połączenia — sprawdź internet i spróbuj ponownie" };
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
  const body: unknown = await res.json().catch(() => ({}));
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
