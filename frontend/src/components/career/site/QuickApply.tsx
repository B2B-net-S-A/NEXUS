"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { CONSENT_CURRENT_TEXT, CV_ACCEPT, captureUtm } from "@/lib/career/apply";
import { capitalize } from "@/lib/career/site";
import {
  careerPayload,
  sendCareerApplication,
  warmCareerSubmit,
  type CareerFieldErrors,
} from "@/lib/career/submit";

import { QUICK_ID } from "./ApplyDock";
import { validateOfferForm } from "./OfferApply";
import { useSent } from "./SentGate";
import { ErrorIcon, siteStyles as s } from "./SiteFrame";

export interface QuickApplyProps {
  linkSlug: string;
  rodoHref: string;
  preview?: { disableSubmit?: boolean; fileName?: string };
}

/**
 * Szybka aplikacja w nagłówku oferty (prośba Artura 23.11.2026: „wrzucam CV
 * i klikam wyślij”). To ta sama wysyłka co pełny formularz niżej
 * (`POST /api/public/career/apply`): CV i zgoda; imię, nazwisko i e-mail
 * serwer czyta z CV, a gdy w CV nie ma e-maila, pojawia się jedno pole.
 * Zgoda zostaje osobnym polem (decyzja D z 19.10.2026); „klik = zgoda”
 * wymagałby decyzji IOD.
 */
export function QuickApply({ linkSlug, rodoHref, preview }: QuickApplyProps) {
  const uid = useId();
  const sent = useSent();
  const utm = useRef<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<CareerFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [emailShown, setEmailShown] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    utm.current = captureUtm(window.location.search);
  }, []);

  // Zagadka ALTCHA liczy się w tle od pierwszej zmiany pola (sam fokus i klik nie, bo harness `/preview/*` nie może wysyłać zapytań) (`lib/altcha`).
  const warm = () => {
    if (!preview) warmCareerSubmit();
  };

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy || preview?.disableSubmit) return;
    const fd = new FormData(e.currentTarget);
    const next = validateOfferForm(fd, emailShown);
    if (Object.keys(next).length > 0) {
      setErrors(next);
      setFormError(null);
      if (next.cv) fileRef.current?.focus();
      return;
    }
    setBusy(true);
    setFormError(null);
    const outcome = await sendCareerApplication(careerPayload(fd, linkSlug, utm.current));
    setBusy(false);
    if (outcome.ok) {
      sent?.({ firstName: outcome.firstName, email: outcome.email, fileName: file?.name ?? null });
      return;
    }
    const fields: CareerFieldErrors = {};
    for (const [k, v] of Object.entries(outcome.fields)) fields[k as keyof CareerFieldErrors] = capitalize(v ?? "");
    if (fields.email) setEmailShown(true);
    setErrors(fields);
    setFormError(outcome.form ? capitalize(outcome.form) : null);
  }

  const shownName = file?.name ?? preview?.fileName ?? null;
  const problems = [errors.cv, errors.email, errors.consent, formError].filter(Boolean) as string[];

  return (
    <form
      id={QUICK_ID}
      className={s.quick}
      onSubmit={onSubmit}
      onChangeCapture={warm}
      noValidate
      aria-label="Szybka aplikacja: samo CV"
    >
      <p className={s.quickTitle}>
        Szybko: samo CV <span>30 sekund</span>
      </p>
      <div className={s.quickRow}>
        <label className={`${s.quickDrop} ${errors.cv ? s.quickBad : ""}`}>
          <input
            ref={fileRef}
            type="file"
            name="cv"
            accept={CV_ACCEPT}
            className={s.srOnly}
            disabled={busy}
            aria-invalid={errors.cv ? true : undefined}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setErrors((p) => ({ ...p, cv: undefined }));
            }}
          />
          <span aria-hidden="true" className={s.dropIcon}>
            {shownName ? "✓" : "+"}
          </span>
          <span className={s.quickName}>{shownName ?? "Wybierz CV (PDF, DOC, DOCX)"}</span>
        </label>
        <button type="submit" className={`${s.btn} ${s.btnRed} ${s.quickSend}`} disabled={busy}>
          {busy ? "Wysyłanie…" : "Wyślij CV"}
        </button>
      </div>
      {emailShown ? (
        <input
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="E-mail: w CV go nie znaleźliśmy"
          aria-label="E-mail"
          aria-invalid={errors.email ? true : undefined}
          className={`${s.inp} ${s.quickEmail}`}
          disabled={busy}
        />
      ) : null}
      <label className={`${s.cons} ${s.quickCons}`}>
          <input
            id={`${uid}-consent`}
            type="checkbox"
            name="consent"
            value="true"
            required
            className={s.srOnly}
            disabled={busy}
            aria-invalid={errors.consent ? true : undefined}
          />
          <span aria-hidden="true" className={`${s.box} ${errors.consent ? s.boxBad : ""}`}>
            <svg width="15" height="12" viewBox="0 0 16 13" fill="none">
              <path d="M1.5 6.5l4.6 4.6L14.5 2" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
            </svg>
          </span>
          <span>
            * {CONSENT_CURRENT_TEXT} <a href={rodoHref}>Klauzula informacyjna</a>
          </span>
        </label>
      <div className={s.honeypot} aria-hidden="true">
        <label htmlFor={`${uid}-website`}>Strona www (zostaw puste)</label>
        <input id={`${uid}-website`} name="website" type="text" tabIndex={-1} autoComplete="off" defaultValue="" />
      </div>
      {problems.length > 0 ? (
        <p role="alert" className={s.quickErr}>
          <ErrorIcon />
          {problems.join(" ")}
        </p>
      ) : null}
    </form>
  );
}
