"use client";

import { useEffect, useId, useRef, useState } from "react";
import { z } from "zod";

import { messageFromApiResponse } from "@/lib/api-error";
import { applyFieldErrors } from "@/lib/apply-form-errors";
import { browserApiBase } from "@/lib/career/api";
import {
  CONSENT_TEXT,
  CV_ACCEPT,
  captureUtm,
  cvProblem,
  type CvProblem,
} from "@/lib/career/apply";

import { useCareerSubmitted } from "./CareerSubmitGate";

/**
 * Formularz strony kariery (`./aplikuj.sh`).
 *
 * Wysyła multipart na `POST /api/public/career/apply` gołym `fetch` — NIGDY
 * przez wewnętrzny klient axios, który dokleja token rekrutera.
 *
 * Pola są niekontrolowane (FormData z formularza), więc po odmowie wpisane dane
 * i wybrany plik zostają w polach — kandydat poprawia jedno pole i wysyła
 * ponownie, zamiast zaczynać od zera.
 */

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

export type CareerFieldErrors = Partial<Record<CareerField, string>>;

/** Kolejność i etykiety pól w podsumowaniu błędów. */
const FIELD_ORDER: { field: CareerField; label: string }[] = [
  { field: "first_name", label: "imię" },
  { field: "last_name", label: "nazwisko" },
  { field: "email", label: "e-mail" },
  { field: "cv", label: "cv" },
  { field: "expected_rate_hourly", label: "stawka" },
  { field: "availability_date", label: "dostępność" },
  { field: "city", label: "miasto" },
  { field: "work_mode", label: "tryb pracy" },
  { field: "consent", label: "zgoda" },
];

const OPTIONAL_FIELDS: CareerField[] = [
  "expected_rate_hourly",
  "availability_date",
  "city",
  "work_mode",
];

const CV_MESSAGES: Record<CvProblem, string> = {
  missing: "dodaj CV — pdf, doc lub docx do 10 MB",
  type: "CV musi być plikiem pdf, doc lub docx",
  size: "CV jest większe niż 10 MB — zmniejsz plik",
};

/** Etykieta domeny po @ nie może zaczynać się ani kończyć myślnikiem. */
function emailDomainProblem(email: string): string | null {
  const at = email.lastIndexOf("@");
  if (at < 0) return null;
  const labels = email.slice(at + 1).split(".");
  if (labels.some((l) => l.startsWith("-") || l.endsWith("-"))) {
    return "sprawdź adres — po @ nie może być myślnika na początku ani na końcu części domeny";
  }
  return null;
}

const schema = z.object({
  first_name: z.string().trim().min(1, "wpisz imię").max(100, "imię jest za długie"),
  last_name: z
    .string()
    .trim()
    .min(1, "wpisz nazwisko")
    .max(100, "nazwisko jest za długie"),
  email: z
    .string()
    .trim()
    .min(1, "wpisz adres e-mail")
    .email("sprawdź adres e-mail — wygląda na niepoprawny"),
  expected_rate_hourly: z
    .string()
    .trim()
    .refine((v) => {
      if (!v) return true;
      const n = Number(v.replace(",", "."));
      return Number.isFinite(n) && n >= 1 && n <= 10000;
    }, "podaj stawkę godzinową netto od 1 do 10 000 zł"),
  availability_date: z
    .string()
    .trim()
    .refine((v) => !v || /^\d{4}-\d{2}-\d{2}$/.test(v), "podaj poprawną datę"),
  city: z.string().trim().max(120, "nazwa miasta może mieć najwyżej 120 znaków"),
  work_mode: z.enum(["any", "remote", "hybrid", "onsite"]),
});

/** „popraw 1 pole / 3 pola / 5 pól". */
export function fieldsWord(n: number): string {
  if (n === 1) return "pole";
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "pola";
  return "pól";
}

export interface CareerApplySuccess {
  firstName: string;
  email: string;
}

export interface CareerApplyFormProps {
  /** Slug linku (`job` albo `recruiter`) — identyfikuje link po stronie API. */
  linkSlug: string;
  variant: "job" | "general";
  rodoHref: string;
  /** Link pod przyciskiem (np. do stałej strony rekrutera). */
  secondaryLink?: { href: string; label: string; note?: string } | null;
  onSuccess?: (result: CareerApplySuccess) => void;
  /** Harness `/preview/kariera`: stan startowy bez wysyłki. */
  preview?: {
    errors?: CareerFieldErrors;
    values?: Partial<Record<Exclude<CareerField, "cv" | "consent">, string>>;
    disableSubmit?: boolean;
  };
}

type Status = "idle" | "submitting";

export function CareerApplyForm({
  linkSlug,
  variant,
  rodoHref,
  secondaryLink,
  onSuccess,
  preview,
}: CareerApplyFormProps) {
  const gateSubmit = useCareerSubmitted();
  const uid = useId();
  const id = (name: string) => `${uid}-${name}`;
  const [errors, setErrors] = useState<CareerFieldErrors>(preview?.errors ?? {});
  const [formError, setFormError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(Boolean(preview?.errors));
  const [status, setStatus] = useState<Status>("idle");
  const [cvName, setCvName] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [optionalOpen, setOptionalOpen] = useState(true);
  const [focusTick, setFocusTick] = useState(0);
  const summaryRef = useRef<HTMLDivElement | null>(null);
  const utmRef = useRef<Record<string, string>>({});

  useEffect(() => {
    utmRef.current = captureUtm(window.location.search);
  }, []);

  useEffect(() => {
    if (focusTick > 0) summaryRef.current?.focus();
  }, [focusTick]);

  const fail = (next: CareerFieldErrors, message: string | null) => {
    setErrors(next);
    setFormError(message);
    setAttempted(true);
    if (OPTIONAL_FIELDS.some((f) => next[f])) setOptionalOpen(true);
    setFocusTick((t) => t + 1);
    setStatus("idle");
  };

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (status === "submitting" || preview?.disableSubmit) return;
    const fd = new FormData(e.currentTarget);
    const str = (name: string) => String(fd.get(name) ?? "");

    const next: CareerFieldErrors = {};
    const parsed = schema.safeParse({
      first_name: str("first_name"),
      last_name: str("last_name"),
      email: str("email"),
      expected_rate_hourly: str("expected_rate_hourly"),
      availability_date: str("availability_date"),
      city: str("city"),
      work_mode: str("work_mode") || "any",
    });
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as CareerField;
        if (!next[key]) next[key] = issue.message;
      }
    }
    if (!next.email) {
      const domain = emailDomainProblem(str("email").trim());
      if (domain) next.email = domain;
    }
    const cv = cvProblem(fd.get("cv") as File | null);
    if (cv) next.cv = CV_MESSAGES[cv];
    if (fd.get("consent") !== "true") {
      next.consent = "bez zgody nie możemy przyjąć zgłoszenia";
    }
    if (Object.keys(next).length > 0) {
      fail(next, null);
      return;
    }

    const payload = new FormData();
    payload.set("link_slug", linkSlug);
    payload.set("first_name", str("first_name").trim());
    payload.set("last_name", str("last_name").trim());
    payload.set("email", str("email").trim());
    payload.set("cv", fd.get("cv") as File);
    payload.set("consent", "true");
    const rate = str("expected_rate_hourly").trim().replace(",", ".");
    if (rate) payload.set("expected_rate_hourly", rate);
    const availability = str("availability_date").trim();
    if (availability) payload.set("availability_date", availability);
    const city = str("city").trim();
    if (city) payload.set("city", city);
    const mode = str("work_mode");
    if (mode && mode !== "any") payload.set("work_mode", mode);
    // Pułapka na boty: człowiek pola nie widzi, więc zostaje puste. Wysyłamy je
    // tylko wypełnione — backend przyjmuje wtedy zgłoszenie po cichu bez zapisu.
    const honeypot = str("website");
    if (honeypot) payload.set("website", honeypot);
    for (const [key, value] of Object.entries(utmRef.current)) payload.set(key, value);

    setStatus("submitting");
    setFormError(null);
    try {
      const res = await fetch(`${browserApiBase()}/api/public/career/apply`, {
        method: "POST",
        body: payload,
      });
      if (res.status === 201 || res.status === 200) {
        setStatus("idle");
        setErrors({});
        (onSuccess ?? gateSubmit)?.({
          firstName: str("first_name").trim(),
          email: str("email").trim(),
        });
        return;
      }
      if (res.status === 404) {
        fail({}, "link wygasł albo rekrutacja jest już zamknięta");
        return;
      }
      if (res.status === 413) {
        fail({ cv: CV_MESSAGES.size }, null);
        return;
      }
      if (res.status === 415) {
        fail({ cv: CV_MESSAGES.type }, null);
        return;
      }
      if (res.status === 429) {
        fail({}, "za dużo prób z tego adresu — spróbuj ponownie za kilka minut");
        return;
      }
      const body: unknown = await res.json().catch(() => ({}));
      const fieldErrors = applyFieldErrors(body);
      if (fieldErrors.length > 0) {
        const mapped: CareerFieldErrors = {};
        let linkProblem: string | null = null;
        for (const fe of fieldErrors) {
          if (fe.field === "link_slug") {
            linkProblem = "link wygasł albo rekrutacja jest już zamknięta";
          } else if (FIELD_ORDER.some((f) => f.field === fe.field)) {
            mapped[fe.field as CareerField] = fe.message;
          }
        }
        if (Object.keys(mapped).length > 0 || linkProblem) {
          fail(mapped, linkProblem);
          return;
        }
      }
      fail(
        {},
        messageFromApiResponse(res.status, body) ?? "coś poszło nie tak — spróbuj ponownie",
      );
    } catch {
      fail({}, "brak połączenia — sprawdź internet i spróbuj ponownie");
    }
  }

  const busy = status === "submitting";
  const invalid = FIELD_ORDER.filter((f) => errors[f.field]);
  const hasProblem = invalid.length > 0 || formError !== null;
  const errId = (field: CareerField) => (errors[field] ? id(`${field}-err`) : undefined);
  const v = preview?.values ?? {};

  const fieldError = (field: CareerField) =>
    errors[field] ? (
      <span className="kr-err" id={id(`${field}-err`)}>
        {"// "}
        {errors[field]}
      </span>
    ) : null;

  const textInput = (
    field: "first_name" | "last_name" | "email" | "city",
    label: string,
    extra: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <div>
      <label className="kr-label" htmlFor={id(field)}>
        {label}
      </label>
      <input
        id={id(field)}
        name={field}
        className="kr-input"
        disabled={busy}
        defaultValue={v[field]}
        aria-invalid={errors[field] ? true : undefined}
        aria-describedby={errId(field)}
        {...extra}
      />
      {fieldError(field)}
    </div>
  );

  return (
    <form onSubmit={onSubmit} noValidate className="kr-form" aria-label="Formularz aplikacji">
      {hasProblem ? (
        <div
          ref={summaryRef}
          role="alert"
          tabIndex={-1}
          className="kr-alert"
          data-testid="career-form-summary"
        >
          <span>
            <span className="kr-r">[err]</span>{" "}
            {invalid.length > 0
              ? `nie udało się wysłać — popraw ${invalid.length} ${fieldsWord(invalid.length)}:`
              : `nie udało się wysłać — ${formError}`}
          </span>
          {invalid.length > 0 ? (
            <span className="kr-g">
              {"  → "}
              {invalid.map((f) => f.label).join(" · ")}
            </span>
          ) : null}
          {invalid.length > 0 && formError ? <span className="kr-g">{formError}</span> : null}
        </div>
      ) : (
        <span className="kr-c" style={{ fontSize: 13 }}>
          {"// pola z * są wymagane"}
        </span>
      )}

      <div className="kr-grid2">
        {textInput("first_name", "imię *", { autoComplete: "given-name", required: true })}
        {textInput("last_name", "nazwisko *", { autoComplete: "family-name", required: true })}
      </div>
      {textInput("email", "e-mail *", {
        type: "email",
        autoComplete: "email",
        inputMode: "email",
        required: true,
      })}

      <div>
        <span className="kr-label" id={id("cv-label")}>
          cv *
        </span>
        <label
          className={dragging ? "kr-file kr-file-drag" : "kr-file"}
          data-invalid={errors.cv ? "true" : undefined}
          onDragEnter={() => setDragging(true)}
          onDragLeave={() => setDragging(false)}
          onDrop={() => setDragging(false)}
        >
          <span className="kr-r" aria-hidden="true">
            +
          </span>
          {cvName ? (
            <span>
              {cvName} <span className="kr-g">· zmień plik</span>
            </span>
          ) : (
            <>
              <span className="kr-file-hint-desktop">
                wybierz plik lub przeciągnij{" "}
                <span className="kr-g">· pdf/doc/docx · 10{"\u00a0"}MB</span>
              </span>
              <span className="kr-file-hint-mobile">dodaj plik z telefonu</span>
            </>
          )}
          <input
            name="cv"
            type="file"
            accept={CV_ACCEPT}
            disabled={busy}
            required
            aria-labelledby={id("cv-label")}
            aria-invalid={errors.cv ? true : undefined}
            aria-describedby={errId("cv")}
            onChange={(e) => {
              const file = e.target.files?.[0];
              setCvName(file?.name ?? null);
              if (attempted) {
                const problem = cvProblem(file);
                setErrors((prev) => ({ ...prev, cv: problem ? CV_MESSAGES[problem] : undefined }));
              }
            }}
          />
        </label>
        {fieldError("cv")}
      </div>

      <button
        type="button"
        className="kr-opt-toggle"
        aria-expanded={optionalOpen}
        aria-controls={id("optional")}
        onClick={() => setOptionalOpen((o) => !o)}
      >
        {optionalOpen ? "▾ " : "▸ "}
        {"// opcjonalnie"}
      </button>
      <span className="kr-c kr-opt-label">
        {variant === "job" ? "// opcjonalnie — przyspieszy rozmowę" : "// opcjonalnie"}
      </span>
      <div
        id={id("optional")}
        className="kr-grid2 kr-opt-fields"
        data-collapsed={optionalOpen ? undefined : "true"}
      >
        <div>
          <label className="kr-label" htmlFor={id("expected_rate_hourly")}>
            stawka zł/h netto
          </label>
          <input
            id={id("expected_rate_hourly")}
            name="expected_rate_hourly"
            type="number"
            inputMode="decimal"
            min={1}
            max={10000}
            step="any"
            placeholder="170"
            className="kr-input"
            disabled={busy}
            defaultValue={v.expected_rate_hourly}
            aria-invalid={errors.expected_rate_hourly ? true : undefined}
            aria-describedby={errId("expected_rate_hourly")}
          />
          {fieldError("expected_rate_hourly")}
        </div>
        <div>
          <label className="kr-label" htmlFor={id("availability_date")}>
            dostępny od
          </label>
          <input
            id={id("availability_date")}
            name="availability_date"
            type="date"
            className="kr-input"
            disabled={busy}
            defaultValue={v.availability_date}
            aria-invalid={errors.availability_date ? true : undefined}
            aria-describedby={errId("availability_date")}
          />
          {fieldError("availability_date")}
        </div>
        {textInput("city", "miasto", { autoComplete: "address-level2", maxLength: 120 })}
        <div>
          <label className="kr-label" htmlFor={id("work_mode")}>
            tryb pracy
          </label>
          <select
            id={id("work_mode")}
            name="work_mode"
            className="kr-input"
            disabled={busy}
            defaultValue={v.work_mode ?? "any"}
            aria-invalid={errors.work_mode ? true : undefined}
            aria-describedby={errId("work_mode")}
          >
            <option value="any">dowolny</option>
            <option value="remote">zdalnie</option>
            <option value="hybrid">hybrydowo</option>
            <option value="onsite">stacjonarnie</option>
          </select>
          {fieldError("work_mode")}
        </div>
      </div>

      {/* Pułapka na boty — niewidoczna i pomijana przez czytniki oraz Tab. */}
      <div className="kr-honeypot" aria-hidden="true">
        <label htmlFor={id("website")}>Strona www (zostaw puste)</label>
        <input
          id={id("website")}
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          defaultValue=""
        />
      </div>

      <div>
        <label className="kr-consent" data-invalid={errors.consent ? "true" : undefined}>
          <input
            type="checkbox"
            name="consent"
            value="true"
            disabled={busy}
            required
            aria-invalid={errors.consent ? true : undefined}
            aria-describedby={errId("consent")}
          />
          <span className="kr-consent-text">
            * {CONSENT_TEXT} <a href={rodoHref}>Klauzula informacyjna</a>
          </span>
        </label>
        {fieldError("consent")}
      </div>

      <button type="submit" className="kr-submit" disabled={busy}>
        {/* Plakietka klawisza nie ma sensu na telefonie — chowamy poniżej `sm`. */}
        <span className="kr-kbd hidden sm:inline-block" aria-hidden="true">
          ENTER
        </span>
        {busy
          ? "wysyłanie…"
          : attempted && hasProblem
            ? "wyślij ponownie"
            : variant === "job"
              ? "wyślij aplikację"
              : "dołącz do bazy"}
      </button>
      {attempted && hasProblem ? (
        <span className="kr-c" style={{ fontSize: 12, textAlign: "center" }}>
          {"// wpisane dane i plik zostają — nie musisz zaczynać od nowa"}
        </span>
      ) : null}
      {secondaryLink ? (
        <a className="kr-sub-link" href={secondaryLink.href}>
          <span>
            {secondaryLink.label}
            {secondaryLink.note ? <span className="kr-c"> {secondaryLink.note}</span> : null}
          </span>
        </a>
      ) : null}
    </form>
  );
}
