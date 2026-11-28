"use client";

import { useEffect, useId, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";

import {
  CONSENT_CURRENT_TEXT,
  CONSENT_FUTURE_TEXT,
  CV_ACCEPT,
  captureUtm,
  cvProblem,
} from "@/lib/career/apply";
import { capitalize, pluralForm } from "@/lib/career/site";
import {
  careerPayload,
  sendCareerApplication,
  warmCareerSubmit,
  type CareerField,
  type CareerFieldErrors,
} from "@/lib/career/submit";

import { useSent } from "./SentGate";
import { ErrorIcon, Who, siteStyles as s } from "./SiteFrame";

/** Kolejność pól w liście „rzeczy do poprawy” i przy fokusie. */
const ORDER: CareerField[] = [
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

const OPTIONAL: CareerField[] = ["expected_rate_hourly", "availability_date", "city", "work_mode"];

const LABEL: Record<CareerField, string> = {
  cv: "CV",
  first_name: "Imię",
  last_name: "Nazwisko",
  email: "E-mail",
  expected_rate_hourly: "Stawka",
  availability_date: "Dostępny od",
  city: "Miasto",
  work_mode: "Tryb pracy",
  consent: "Zgoda na rekrutację",
};

const CV_RULE = "CV musi być plikiem PDF, DOC albo DOCX do 10 MB.";

/** Rozszerzenie do komunikatu „Ten plik to ZIP.” */
export function cvExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toUpperCase() : "plik bez rozszerzenia";
}

function cvMessage(file: File | null): string | null {
  const problem = cvProblem(file);
  if (problem === "missing") return "Dodaj CV: PDF, DOC albo DOCX do 10 MB.";
  if (problem === "type") return `Ten plik to ${cvExtension(file?.name ?? "")}. ${CV_RULE}`;
  if (problem === "size") return `Plik jest za duży. ${CV_RULE}`;
  return null;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Walidacja w przeglądarce — te same reguły co API, zdania jak na planszy AplikacjaBledy. */
export function validateOfferForm(fd: FormData, emailShown: boolean): CareerFieldErrors {
  const str = (k: string) => String(fd.get(k) ?? "").trim();
  const errors: CareerFieldErrors = {};
  const cv = cvMessage(fd.get("cv") as File | null);
  if (cv) errors.cv = cv;
  const email = str("email");
  if (emailShown && !email) errors.email = "Podaj adres e-mail.";
  else if (email && (!EMAIL.test(email) || email.length > 255)) {
    errors.email = "Wpisz adres w formacie twoj@email.pl.";
  }
  const rate = str("expected_rate_hourly");
  if (rate) {
    const n = Number(rate.replace(",", "."));
    if (!Number.isFinite(n) || n < 1 || n > 10000) {
      errors.expected_rate_hourly = "Wpisz stawkę liczbą od 1 do 10 000 zł albo zostaw pole puste.";
    }
  }
  const date = str("availability_date");
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) errors.availability_date = "Wybierz datę z kalendarza.";
  if (str("city").length > 120) errors.city = "Nazwa miasta może mieć najwyżej 120 znaków.";
  if (fd.get("consent") !== "true") errors.consent = "Zaznacz zgodę, żeby wysłać zgłoszenie.";
  return errors;
}

export interface OfferApplyProps {
  linkSlug: string;
  /** `general` = „Zostaw CV” bez rekrutacji: jedna, obowiązkowa zgoda na przyszłe procesy. */
  variant: "job" | "general";
  rodoHref: string;
  recruiterFirstName: string;
  jobTitle?: string;
  /** „Warszawa · Hybryda · B2B” na karcie pod listą błędów. */
  factsLine?: string;
  /** Lewa kolumna przed pierwszą próbą wysyłki. */
  intro: ReactNode;
  /** Harness `/preview/kariera`: stan bez wysyłki. */
  preview?: { errors?: CareerFieldErrors; disableSubmit?: boolean };
}

/**
 * Formularz zgłoszenia (plansze OfertaA i AplikacjaBledy). Wysyłka przez
 * `POST /api/public/career/apply` (`lib/career/submit`). Pola są
 * niekontrolowane, więc po odmowie wpisane dane i plik zostają.
 *
 * Samo CV (decyzja Artura 07.11.2026): imię, nazwisko i e-mail czyta serwer
 * z CV; pole e-mail pojawia się dopiero, gdy w CV adresu nie było (422 na
 * `email`). Pola opcjonalne są zwinięte.
 */
export function OfferApply({
  linkSlug,
  variant,
  rodoHref,
  recruiterFirstName,
  jobTitle,
  factsLine,
  intro,
  preview,
}: OfferApplyProps) {
  const uid = useId();
  const id = (f: string) => `${uid}-${f}`;
  const errId = (f: CareerField) => `${uid}-${f}-err`;
  const sent = useSent();
  const formRef = useRef<HTMLFormElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const bannerRef = useRef<HTMLDivElement>(null);
  const utm = useRef<Record<string, string>>({});
  const [errors, setErrors] = useState<CareerFieldErrors>(preview?.errors ?? {});
  const [formError, setFormError] = useState<string | null>(null);
  const [tried, setTried] = useState(Boolean(preview?.errors));
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [emailShown, setEmailShown] = useState(Boolean(preview?.errors?.email));
  const [optOpen, setOptOpen] = useState(OPTIONAL.some((f) => preview?.errors?.[f]));
  const [focusTick, setFocusTick] = useState(0);

  useEffect(() => {
    utm.current = captureUtm(window.location.search);
  }, []);

  const failed = ORDER.filter((f) => errors[f]);

  // Fokus na pierwsze złe pole po odmowie (po renderze, bo pole e-mail może dopiero się pojawić).
  useEffect(() => {
    if (focusTick === 0) return;
    const first = ORDER.find((f) => errors[f]);
    const el = first ? document.getElementById(id(first)) : bannerRef.current;
    el?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTick]);

  const fail = (next: CareerFieldErrors, message: string | null) => {
    setErrors(next);
    setFormError(message);
    setTried(true);
    if (next.email) setEmailShown(true);
    if (OPTIONAL.some((f) => next[f])) setOptOpen(true);
    setFocusTick((t) => t + 1);
  };

  // Po pierwszej próbie błędy znikają na bieżąco, gdy kandydat poprawia pola.
  const revalidate = (nextFile: File | null = file) => {
    if (!tried || !formRef.current) return;
    const fd = new FormData(formRef.current);
    if (nextFile !== file) fd.set("cv", nextFile ?? new File([], ""));
    setErrors((prev) => {
      const fresh = validateOfferForm(fd, emailShown);
      // Błąd z serwera (np. brak e-maila w CV) zostaje, dopóki pole jest puste.
      if (prev.email && !fresh.email && !String(fd.get("email") ?? "").trim()) fresh.email = prev.email;
      return fresh;
    });
  };

  // Zagadka ALTCHA liczy się w tle od pierwszej zmiany pola (sam fokus i klik nie, bo harness `/preview/*` nie może wysyłać zapytań) (`lib/altcha`).
  const warm = () => {
    if (!preview) warmCareerSubmit();
  };

  const pickFile = (next: File | null) => {
    warm();
    setFile(next);
    revalidate(next);
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files;
    if (!dropped.length || !fileRef.current) return;
    fileRef.current.files = dropped;
    pickFile(dropped[0]);
  };

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy || preview?.disableSubmit) return;
    const fd = new FormData(e.currentTarget);
    const next = validateOfferForm(fd, emailShown);
    if (Object.keys(next).length > 0) {
      fail(next, null);
      return;
    }
    setBusy(true);
    setFormError(null);
    const outcome = await sendCareerApplication(careerPayload(fd, linkSlug, utm.current));
    setBusy(false);
    if (outcome.ok) {
      setErrors({});
      sent?.({ firstName: outcome.firstName, email: outcome.email, fileName: file?.name ?? null });
      return;
    }
    const fields: CareerFieldErrors = {};
    for (const [k, v] of Object.entries(outcome.fields)) fields[k as CareerField] = capitalize(v ?? "");
    fail(fields, outcome.form ? capitalize(outcome.form) : null);
  }

  const aria = (f: CareerField) => ({
    "aria-invalid": errors[f] ? true : undefined,
    "aria-describedby": errors[f] ? errId(f) : undefined,
  });

  const msg = (f: CareerField, className?: string) =>
    errors[f] ? (
      <span id={errId(f)} className={`${s.msg} ${className ?? ""}`}>
        <ErrorIcon />
        {errors[f]}
      </span>
    ) : null;

  const goTo = (f: CareerField) => {
    const el = document.getElementById(id(f));
    el?.scrollIntoView({ block: "center" });
    el?.focus({ preventScroll: true });
  };

  const name = recruiterFirstName.trim();
  const callback = name ? `${name} odezwie się do Ciebie po przejrzeniu CV.` : "Odezwiemy się po przejrzeniu CV.";
  const n = failed.length;
  const cvBad = Boolean(errors.cv);
  const req = <span className={s.req}>*</span>;

  return (
    <div className={s.row4}>
      <div aria-live="polite">
        {n === 0 ? (
          intro
        ) : (
          <>
            <p aria-hidden="true" className={`${s.display} ${s.s4Big}`}>
              {n}
            </p>
            <h2 className={s.lead}>
              <span className={s.srOnly}>{n}</span>{" "}
              {pluralForm(n) === "one" ? "rzecz do poprawy" : "rzeczy do poprawy"}, reszta została
            </h2>
            <p className={s.body}>
              {jobTitle ? `${jobTitle}. ` : ""}Nie wpisujesz niczego od nowa, popraw tylko{" "}
              {pluralForm(n) === "one" ? "to pole" : "te pola"}.
            </p>
            <ol className={s.errl}>
              {failed.map((f) => (
                <li key={f}>
                  <b>{f === "consent" && variant === "general" ? "Zgoda" : LABEL[f]}</b>
                  <a
                    href={`#${id(f)}`}
                    onClick={(e) => {
                      e.preventDefault();
                      goTo(f);
                    }}
                  >
                    Przejdź do pola
                  </a>
                </li>
              ))}
            </ol>
            {jobTitle ? (
              <aside className={s.mini} aria-label="Oferta">
                <h3>{jobTitle}</h3>
                {factsLine ? <p>{factsLine}</p> : null}
                {name ? <Who name={`Prowadzi ${name}`} initialOf={name} note={callback} /> : null}
              </aside>
            ) : null}
          </>
        )}
      </div>

      <div className={s.formCard}>
        <form
          ref={formRef}
          noValidate
          onSubmit={onSubmit}
          onChange={() => revalidate()}
          onChangeCapture={warm}
          aria-label="Formularz zgłoszenia"
        >
          {n > 0 || formError ? (
            <div ref={bannerRef} role="alert" tabIndex={-1} className={s.banner} data-testid="career-form-summary">
              <ErrorIcon />
              <span>
                {n > 0
                  ? `Zgłoszenie nie wyszło. Sprawdź ${n} ${
                      { one: "pole oznaczone", few: "pola oznaczone", many: "pól oznaczonych" }[pluralForm(n)]
                    } na czerwono.`
                  : `Zgłoszenie nie wyszło. ${formError}`}
                {n > 0 && formError ? ` ${formError}` : ""}
              </span>
            </div>
          ) : null}

          <div className={s.form}>
            <div className={`${s.fld} ${s.full}`}>
              <span id={id("cv-label")}>CV {req}</span>
              <label
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={`${s.drop} ${cvBad ? s.dropBad : dragging ? s.dropDrag : ""}`}
              >
                <input
                  ref={fileRef}
                  id={id("cv")}
                  type="file"
                  name="cv"
                  accept={CV_ACCEPT}
                  className={s.srOnly}
                  disabled={busy}
                  aria-labelledby={`${id("cv-label")} ${id("cv-hint")}`}
                  {...aria("cv")}
                  onChange={(e) => {
                    e.stopPropagation();
                    pickFile(e.target.files?.[0] ?? null);
                  }}
                />
                <span aria-hidden="true" className={s.dropIcon}>
                  {cvBad && file ? "×" : "+"}
                </span>
                <span id={id("cv-hint")}>
                  <b>
                    {file ? (
                      file.name
                    ) : (
                      <>
                        <span className={s.dropDesk}>Wybierz plik lub przeciągnij</span>
                        <span className={s.dropMob}>Dodaj plik z telefonu</span>
                      </>
                    )}
                  </b>
                  <small>{cvBad && file ? "Wybierz inny plik: PDF, DOC, DOCX do 10 MB" : "PDF, DOC, DOCX do 10 MB"}</small>
                </span>
              </label>
              {msg("cv")}
            </div>

            {emailShown ? (
              <div className={`${s.fld} ${s.full}`}>
                <label htmlFor={id("email")}>E-mail {req}</label>
                <input
                  id={id("email")}
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  placeholder="twoj@email.pl"
                  className={s.inp}
                  disabled={busy}
                  {...aria("email")}
                />
                {msg("email")}
              </div>
            ) : null}

            <button
              type="button"
              className={`${s.subg} ${s.full}`}
              aria-expanded={optOpen}
              aria-controls={id("optional")}
              onClick={() => setOptOpen((o) => !o)}
            >
              {variant === "job" ? "Opcjonalnie, przyspieszy rozmowę" : "Opcjonalnie"}
              <span>{optOpen ? "Zwiń" : "Rozwiń"}</span>
            </button>
            <div id={id("optional")} className={s.optFields} hidden={!optOpen}>
              <div className={s.fld}>
                <label htmlFor={id("expected_rate_hourly")}>Stawka zł/h netto</label>
                <div className={s.inpWrap}>
                  <input
                    id={id("expected_rate_hourly")}
                    name="expected_rate_hourly"
                    inputMode="decimal"
                    className={s.inp}
                    style={{ paddingRight: 56 }}
                    disabled={busy}
                    {...aria("expected_rate_hourly")}
                  />
                  <span aria-hidden="true" className={s.sfx}>
                    zł/h
                  </span>
                </div>
                {msg("expected_rate_hourly")}
              </div>
              <div className={s.fld}>
                <label htmlFor={id("availability_date")}>Dostępny od</label>
                <input
                  id={id("availability_date")}
                  name="availability_date"
                  type="date"
                  className={s.inp}
                  disabled={busy}
                  {...aria("availability_date")}
                />
                {msg("availability_date")}
              </div>
              <div className={s.fld}>
                <label htmlFor={id("city")}>Miasto</label>
                <input
                  id={id("city")}
                  name="city"
                  autoComplete="address-level2"
                  maxLength={120}
                  className={s.inp}
                  disabled={busy}
                  {...aria("city")}
                />
                {msg("city")}
              </div>
              <div className={s.fld}>
                <label htmlFor={id("work_mode")}>Tryb pracy</label>
                <div className={s.inpWrap}>
                  <select
                    id={id("work_mode")}
                    name="work_mode"
                    defaultValue="any"
                    className={s.inp}
                    disabled={busy}
                    {...aria("work_mode")}
                  >
                    <option value="any">dowolny</option>
                    <option value="remote">Zdalnie</option>
                    <option value="hybrid">Hybryda</option>
                    <option value="onsite">Stacjonarnie</option>
                  </select>
                  <span aria-hidden="true" className={s.caret}>
                    ▾
                  </span>
                </div>
                {msg("work_mode")}
              </div>
            </div>

            {/* Pułapka na boty: niewidoczna i pomijana przez czytniki oraz Tab. */}
            <div className={s.honeypot} aria-hidden="true">
              <label htmlFor={id("website")}>Strona www (zostaw puste)</label>
              <input id={id("website")} name="website" type="text" tabIndex={-1} autoComplete="off" defaultValue="" />
            </div>

            <div className={s.full}>
              <label className={s.cons}>
                <input
                  id={id("consent")}
                  type="checkbox"
                  name="consent"
                  value="true"
                  required
                  className={s.srOnly}
                  disabled={busy}
                  {...aria("consent")}
                />
                <span aria-hidden="true" className={`${s.box} ${errors.consent ? s.boxBad : ""}`}>
                  <CheckMark />
                </span>
                <span>
                  {req} {variant === "general" ? CONSENT_FUTURE_TEXT : CONSENT_CURRENT_TEXT}{" "}
                  <a href={rodoHref}>Klauzula informacyjna</a>
                </span>
              </label>
            </div>
            {errors.consent ? msg("consent", `${s.full} ${s.consMsg}`) : null}

            {variant === "general" ? null : (
              <label className={`${s.cons} ${s.full}`}>
                <input type="checkbox" name="consent_future" value="true" className={s.srOnly} disabled={busy} />
                <span aria-hidden="true" className={s.box}>
                  <CheckMark />
                </span>
                <span>
                  <span className={s.opt}>(nieobowiązkowe)</span> {CONSENT_FUTURE_TEXT}
                </span>
              </label>
            )}

            <button type="submit" className={`${s.submit} ${s.full}`} disabled={busy}>
              {busy ? "Wysyłanie…" : variant === "job" ? "Wyślij zgłoszenie" : "Zostaw CV"}
            </button>
          </div>
          <p className={s.note}>
            Pola oznaczone {req} są wymagane.
            {tried && (n > 0 || formError) ? " Wpisane dane i plik zostają, nie musisz zaczynać od nowa." : ""}
          </p>
        </form>
      </div>
    </div>
  );
}

function CheckMark() {
  return (
    <svg width="15" height="12" viewBox="0 0 16 13" fill="none">
      <path d="M1.5 6.5l4.6 4.6L14.5 2" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
    </svg>
  );
}
