"use client";

/**
 * „Twoje warunki” pod linkiem z maila z raportem kompetencji (decyzje Artura
 * 25.11.2026). Bez logowania i bez nawigacji NEXUSA, wygląd jak `/warunki`.
 * Pola jak formularz raportu na stronie b2bnetwork.ai; zapis idzie do profilu
 * tymi samymi writerami co zgłoszenie (`api/public_competence_report.py`).
 * `?wypis=1` = wypis z raportów (działa także po terminie linku).
 */

import { useEffect, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import axios from "axios";
import Link from "next/link";

import { B2BLogo } from "@/components/career/B2BLogo";
import { careerDisplayFont } from "@/components/career/fonts";
import {
  CITIES_MAX,
  CITY_OPTIONS,
  CONTRACTS,
  EMPTY_STATE,
  OFFICE_DAYS_MAX,
  STARTS,
  TEXT,
  WORK_MODES,
  addCity,
  buildPayload,
  formatSentDay,
  hasCity,
  needsOffice,
  stateFromConditions,
  toggleCity,
  toggleMode,
  type ConditionsErrors,
  type ConditionsField,
  type ConditionsState,
  type ReportView,
} from "@/lib/competence-report";

import "@/components/candidate-terms/warunki.css";
import "./raport.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

type Screen = "loading" | "form" | "saved" | "invalid" | "load_error" | "optout" | "optout_done";

interface ReportConditionsPageProps {
  token: string;
  optOut: boolean;
}

function Title({ text }: { text: string }) {
  return (
    <h1>
      {text}
      {!text.endsWith("?") && <span className="wr-dot">.</span>}
    </h1>
  );
}

function statusOf(err: unknown): number | undefined {
  return axios.isAxiosError(err) ? err.response?.status : undefined;
}

interface QuestionProps {
  legend: ReactNode;
  /** Pole tekstowe: podpis jako `<label>`, bez grupy. */
  htmlFor?: string;
  error?: string;
  children: ReactNode;
}

function Question({ legend, htmlFor, error, children }: QuestionProps) {
  const body = (
    <div>
      {htmlFor ? (
        <label htmlFor={htmlFor} className="wr-label rk-label">
          {legend}
        </label>
      ) : (
        <legend>{legend}</legend>
      )}
      {children}
      {error && <p className="wr-error">{error}</p>}
    </div>
  );
  return htmlFor ? <div className="wr-q">{body}</div> : <fieldset className="wr-q">{body}</fieldset>;
}

export function ReportConditionsPage({ token, optOut }: ReportConditionsPageProps) {
  const [screen, setScreen] = useState<Screen>(optOut ? "optout" : "loading");
  const [sentAt, setSentAt] = useState<string | null>(null);
  const [state, setState] = useState<ConditionsState>(EMPTY_STATE);
  const [errors, setErrors] = useState<ConditionsErrors>({});
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const t = TEXT;
  const url = `${API_BASE}/api/public/competence-report/${encodeURIComponent(token)}`;

  useEffect(() => {
    // Wypis nie czeka na odczyt: działa też po terminie linku, gdy odczyt daje 404.
    if (optOut) return;
    let alive = true;
    axios
      .get<ReportView>(url)
      .then(({ data }) => {
        if (!alive) return;
        setSentAt(data.sent_at);
        setState(stateFromConditions(data.conditions));
        setScreen("form");
      })
      .catch((err: unknown) => {
        if (alive) setScreen(statusOf(err) === 404 ? "invalid" : "load_error");
      });
    return () => {
      alive = false;
    };
  }, [url, optOut]);

  const patch = (field: ConditionsField, next: Partial<ConditionsState>) => {
    setState((prev) => ({ ...prev, ...next }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
    setFailed(false);
  };

  const addDraft = () => {
    patch("cities", { cities: addCity(state.cities, draft) });
    setDraft("");
    setAdding(false);
  };

  const onDraftKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    addDraft();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const { payload, errors: found } = buildPayload(state);
    setErrors(found);
    setFailed(false);
    if (!payload) return;
    setSaving(true);
    try {
      const { data } = await axios.post<ReportView>(`${url}/conditions`, payload);
      setState(stateFromConditions(data.conditions));
      setScreen("saved");
    } catch (err: unknown) {
      if (statusOf(err) === 404) setScreen("invalid");
      else setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const confirmOptOut = async () => {
    setSaving(true);
    setFailed(false);
    try {
      await axios.post(`${url}/opt-out`);
      setScreen("optout_done");
    } catch (err: unknown) {
      if (statusOf(err) === 404) setScreen("invalid");
      else setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const office = needsOffice(state.modes);
  const own = state.cities.filter((c) => !hasCity(CITY_OPTIONS, c));
  const full = state.cities.length >= CITIES_MAX;
  const days = state.officeDays === "" ? -1 : Number(state.officeDays);

  return (
    <div className={`wr-root rk-root ${careerDisplayFont.variable}`} lang="pl">
      <header className="wr-head">
        <span className="wr-logo">
          <B2BLogo height={36} className="wr-logo-lt" />
          <B2BLogo variant="onDark" height={36} className="wr-logo-dk" />
        </span>
      </header>

      <main className="wr-main">
        <section className="wr-intro" aria-live="polite">
          {screen === "loading" && <p>{t.loading}</p>}
          {screen === "form" && (
            <>
              {sentAt && (
                <p className="wr-kicker">
                  {t.sentOn} {formatSentDay(sentAt)}
                </p>
              )}
              <Title text={t.title} />
              <p>{t.lead}</p>
            </>
          )}
          {screen === "saved" && (
            <>
              <Title text={t.savedTitle} />
              <p>{t.savedLead}</p>
              <button type="button" className="wr-btn wr-btn-quiet" onClick={() => setScreen("form")}>
                {t.edit}
              </button>
            </>
          )}
          {screen === "invalid" && (
            <>
              <Title text={t.invalidTitle} />
              <p>{t.invalidLead}</p>
            </>
          )}
          {screen === "load_error" && (
            <>
              <Title text={t.loadErrorTitle} />
              <p>{t.loadErrorLead}</p>
            </>
          )}
          {(screen === "optout" || screen === "optout_done") && (
            <>
              <Title text={screen === "optout_done" ? t.optoutDoneTitle : t.optoutTitle} />
              <p>{screen === "optout_done" ? t.optoutDone : t.optoutLead}</p>
              {screen === "optout" && (
                <button type="button" className="wr-btn" onClick={confirmOptOut} disabled={saving}>
                  {t.optoutButton}
                </button>
              )}
              {failed && <p className="wr-alert">{t.errors.optout}</p>}
            </>
          )}
        </section>

        {screen === "form" && (
          <form className="wr-form" onSubmit={submit} noValidate>
            <Question legend={t.rate} htmlFor="rk-rate" error={errors.rate}>
              <div className="rk-field">
                <input
                  id="rk-rate"
                  className="wr-input"
                  inputMode="numeric"
                  autoComplete="off"
                  aria-invalid={errors.rate ? true : undefined}
                  value={state.rate}
                  onChange={(e) => patch("rate", { rate: e.target.value })}
                />
                <span className="rk-unit">{t.rateUnit}</span>
              </div>
            </Question>

            <Question
              legend={
                <>
                  {t.currentRate} <span className="rk-optional">{t.optional}</span>
                </>
              }
              htmlFor="rk-current"
              error={errors.currentRate}
            >
              <div className="rk-field">
                <input
                  id="rk-current"
                  className="wr-input"
                  inputMode="numeric"
                  autoComplete="off"
                  aria-invalid={errors.currentRate ? true : undefined}
                  value={state.currentRate}
                  onChange={(e) => patch("currentRate", { currentRate: e.target.value })}
                />
                <span className="rk-unit">{t.currentUnit}</span>
              </div>
            </Question>

            <Question legend={t.contract} error={errors.contract}>
              <div className="wr-seg" role="radiogroup" aria-label={t.contract}>
                {CONTRACTS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    role="radio"
                    aria-checked={state.contract === c}
                    onClick={() => patch("contract", { contract: c })}
                  >
                    {t.contractOptions[c]}
                  </button>
                ))}
              </div>
            </Question>

            <Question legend={t.modes} error={errors.modes}>
              <div className="wr-seg">
                {WORK_MODES.map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={state.modes.includes(m)}
                    onClick={() => patch("modes", { modes: toggleMode(state.modes, m) })}
                  >
                    {t.modeOptions[m]}
                  </button>
                ))}
              </div>
            </Question>

            {office && (
              <Question legend={t.officeDays} error={errors.officeDays}>
                <div className="wr-seg rk-days" role="radiogroup" aria-label={t.officeDays}>
                  {Array.from({ length: OFFICE_DAYS_MAX + 1 }, (_, n) => (
                    <button
                      key={n}
                      type="button"
                      role="radio"
                      aria-checked={n === days}
                      onClick={() => patch("officeDays", { officeDays: String(n) })}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </Question>
            )}

            {office && (
              <Question legend={t.cities} error={errors.cities}>
                <div className="wr-chips">
                  {[...CITY_OPTIONS, ...own].map((city) => {
                    const on = hasCity(state.cities, city);
                    return (
                      <button
                        key={city}
                        type="button"
                        className="wr-chip"
                        aria-pressed={on}
                        disabled={full && !on}
                        onClick={() => patch("cities", { cities: toggleCity(state.cities, city) })}
                      >
                        {city}
                      </button>
                    );
                  })}
                  {!adding && (
                    <button
                      type="button"
                      className="wr-chip wr-chip-other"
                      disabled={full}
                      onClick={() => setAdding(true)}
                    >
                      {t.otherCity}
                    </button>
                  )}
                </div>
                {adding && (
                  <div className="rk-other">
                    <label htmlFor="rk-city" className="sr-only">
                      {t.otherCityLabel}
                    </label>
                    <input
                      id="rk-city"
                      className="wr-input"
                      autoComplete="address-level2"
                      maxLength={60}
                      autoFocus
                      placeholder={t.otherCityPlaceholder}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={onDraftKey}
                    />
                    <button type="button" className="wr-chip" onClick={addDraft}>
                      {t.addCity}
                    </button>
                  </div>
                )}
              </Question>
            )}

            <Question legend={t.start} error={errors.start}>
              <div className="wr-seg" role="radiogroup" aria-label={t.start}>
                {STARTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={state.start === s}
                    onClick={() => patch("start", { start: s })}
                  >
                    {t.startOptions[s]}
                  </button>
                ))}
              </div>
            </Question>

            {failed && <p className="wr-alert">{t.errors.network}</p>}

            <button type="submit" className="wr-btn" disabled={saving}>
              {saving ? t.saving : t.submit}
              <span aria-hidden="true">→</span>
            </button>
          </form>
        )}
      </main>

      <footer className="wr-foot">
        <div className="wr-foot-inner">
          <Link href="/kariera/rodo">{t.privacy}</Link>
          <span>B2B.NET S.A. · Al. Jerozolimskie 180, 02-486 Warszawa · KRS 0000387063 · NIP 5711707392</span>
        </div>
      </footer>
    </div>
  );
}
