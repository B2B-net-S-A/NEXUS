"use client";

/**
 * „Twoje warunki” — formularz dla kandydata z linku w mailu „Dziękujemy za
 * zgłoszenie” (decyzje Artura 16–17.11.2026). Bez logowania i bez nawigacji
 * NEXUSA. Zapis nadpisuje profil (backend: `candidate_terms_apply.py`).
 */

import { useCallback, useEffect, useState } from "react";
import axios from "axios";

import { B2BLogo } from "@/components/career/B2BLogo";
import { careerDisplayFont } from "@/components/career/fonts";
import {
  CITY_SUGGESTIONS,
  EMPTY_STATE,
  TEXT,
  addCity,
  answeredCount,
  buildPayload,
  officeNeeded,
  parseAmount,
  pluralForm,
  rateSummary,
  stateFromAnswers,
  unitHint,
  type FieldError,
  type Lang,
  type Mode,
  type TermsState,
} from "@/lib/candidate-terms";

import "./warunki.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.b2bnetwork.pl";

interface TermsView {
  job_title: string | null;
  expires_at: string;
  answered_at: string | null;
  answers: Record<string, unknown> | null;
  opted_out: boolean;
}

type Screen = "loading" | "form" | "saved" | "expired" | "invalid" | "optout" | "optout_done";

interface TermsPageProps {
  token: string;
  optOut: boolean;
}

type StepState = "done" | "open" | "expired";

/** Pasek jak w mailu „Pasek postępu”: Zgłoszenie ✓ · CV ✓ · Twoje warunki. */
function Progress({
  labels,
  last,
  fill,
  note,
}: {
  labels: readonly string[];
  last: StepState;
  fill: number;
  note?: string;
}) {
  const states: StepState[] = ["done", "done", last];
  return (
    <ol className="wr-bar" aria-label={labels.join(", ")}>
      {labels.map((label, i) => (
        <li key={label} className={`wr-seg-${states[i]}`}>
          <span className="wr-track" aria-hidden="true">
            {states[i] === "open" && <span style={{ width: `${Math.round(fill * 100)}%` }} />}
          </span>
          <span className="wr-step">
            {states[i] === "done" && <span aria-hidden="true">✓ </span>}
            {label}
            {states[i] === "expired" && note ? <small> · {note}</small> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Title({ text }: { text: string }) {
  return (
    <h1>
      {text}
      <span className="wr-dot">.</span>
    </h1>
  );
}

function formatDate(iso: string, lang: Lang): string {
  return new Date(iso).toLocaleDateString(lang === "pl" ? "pl-PL" : "en-GB", {
    day: "numeric",
    month: "long",
    timeZone: "Europe/Warsaw",
  });
}

export function TermsPage({ token, optOut }: TermsPageProps) {
  const [lang, setLang] = useState<Lang>("pl");
  const [screen, setScreen] = useState<Screen>("loading");
  const [view, setView] = useState<TermsView | null>(null);
  const [state, setState] = useState<TermsState>(EMPTY_STATE);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [networkError, setNetworkError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [cityDraft, setCityDraft] = useState("");
  const t = TEXT[lang];
  const url = `${API_BASE}/api/public/candidate-terms/${encodeURIComponent(token)}`;

  useEffect(() => {
    let alive = true;
    axios
      .get<TermsView>(url)
      .then(({ data }) => {
        if (!alive) return;
        setView(data);
        setState(stateFromAnswers(data.answers));
        setScreen(optOut ? "optout" : data.answered_at ? "saved" : "form");
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const status = axios.isAxiosError(err) ? err.response?.status : undefined;
        if (status === 410) setScreen(optOut ? "optout" : "expired");
        else setScreen("invalid");
      });
    return () => {
      alive = false;
    };
  }, [url, optOut]);

  const patch = useCallback((next: Partial<TermsState>) => {
    setState((prev) => ({ ...prev, ...next }));
    setErrors([]);
  }, []);

  const toggleMode = (mode: Mode) => {
    const modes = state.modes.includes(mode)
      ? state.modes.filter((m) => m !== mode)
      : [...state.modes, mode];
    patch({ modes });
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const { payload, errors: found } = buildPayload(state);
    setErrors(found);
    setNetworkError(false);
    if (found.length) return;
    setSaving(true);
    try {
      await axios.post(url, payload);
      setView((prev) => (prev ? { ...prev, answered_at: new Date().toISOString() } : prev));
      setScreen("saved");
    } catch (err: unknown) {
      const status = axios.isAxiosError(err) ? err.response?.status : undefined;
      if (status === 410) setScreen("expired");
      else setNetworkError(true);
    } finally {
      setSaving(false);
    }
  };

  const confirmOptOut = async () => {
    setSaving(true);
    try {
      await axios.post(`${url}/opt-out`);
      setScreen("optout_done");
    } catch {
      setNetworkError(true);
    } finally {
      setSaving(false);
    }
  };

  const amount = parseAmount(state.rateAmount);
  const hint = unitHint(amount, state.rateUnit);
  const showOffice = officeNeeded(state.modes);

  return (
    <div className={`wr-root ${careerDisplayFont.variable}`} lang={lang}>
      <header className="wr-head">
        <span className="wr-logo">
          <B2BLogo height={36} className="wr-logo-lt" />
          <B2BLogo variant="onDark" height={36} className="wr-logo-dk" />
        </span>
        <button type="button" className="wr-lang" onClick={() => setLang(lang === "pl" ? "en" : "pl")}>
          {t.lang}
        </button>
      </header>

      <main className="wr-main">
        <section className="wr-intro" aria-live="polite">
          {screen === "loading" && <p>{t.loading}</p>}
          {(screen === "form" || screen === "saved" || screen === "expired") && (
            <>
              <p className="wr-kicker">
                {t.kicker}
                {view?.job_title && (
                  <>
                    <br />
                    <b>{view.job_title}</b>
                  </>
                )}
              </p>
              <Progress
                labels={t.steps}
                last={screen === "saved" ? "done" : screen === "expired" ? "expired" : "open"}
                fill={(answeredCount(state) / 3) * 0.9}
                note={t.expiredStep}
              />
            </>
          )}
          {(screen === "form" || screen === "saved") && (
            <>
              <Title text={screen === "saved" ? t.savedTitle : t.title} />
              <p>
                {screen === "saved" && view
                  ? `${t.savedLead} ${formatDate(view.expires_at, lang)}.`
                  : t.lead}
              </p>
            </>
          )}
          {screen === "expired" && (
            <>
              <Title text={t.expiredTitle} />
              <p>{t.expiredLead}</p>
            </>
          )}
          {screen === "invalid" && (
            <>
              <Title text={t.invalidTitle} />
              <p>{t.invalidLead}</p>
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
              {networkError && <p className="wr-alert">{t.errors.network}</p>}
            </>
          )}
        </section>

        {screen === "saved" && (
          <section className="wr-form">
            <dl className="wr-sum">
              <dt>{t.summaryRate}</dt>
              <dd>{rateSummary(state, lang) ?? "—"}</dd>
              <dt>{t.summaryModes}</dt>
              <dd>
                {state.modes.length
                  ? state.modes.map((m) => t.mode[m]).join(", ") +
                    (state.modes.includes("hybrid") && state.onsiteDays
                      ? ` · ${state.onsiteDays} / 5`
                      : "")
                  : "—"}
              </dd>
              <dt>{t.summaryCities}</dt>
              <dd>{state.cities.length ? state.cities.join(", ") : "—"}</dd>
              <dt>{t.summaryStart}</dt>
              <dd>
                {state.startKind === "now"
                  ? t.startNow
                  : state.startKind === "date" && state.startDate
                    ? formatDate(state.startDate, lang)
                    : state.startKind === "notice"
                      ? `${state.noticeValue} ${pluralForm(
                          Number(state.noticeValue),
                          state.noticeUnit === "weeks" ? t.weekForms : t.monthForms,
                        )} ${t.notice}`
                      : "—"}
              </dd>
            </dl>
            <button type="button" className="wr-btn wr-btn-quiet" onClick={() => setScreen("form")}>
              {t.edit}
            </button>
          </section>
        )}

        {screen === "form" && (
          <form className="wr-form" onSubmit={submit} noValidate>
            <fieldset className="wr-q">
              <span className="wr-num">01</span>
              <div>
                <legend>{t.rate}</legend>
                <p className="wr-help">{t.rateHelp}</p>
                <div className="wr-row">
                  <input
                    id="wr-rate"
                    className="wr-input wr-amount"
                    inputMode="decimal"
                    aria-label={t.rate}
                    value={state.rateAmount}
                    onChange={(e) => patch({ rateAmount: e.target.value })}
                  />
                  <div className="wr-seg" role="radiogroup" aria-label={t.rate}>
                    {(["hour", "month"] as const).map((unit) => (
                      <button
                        key={unit}
                        type="button"
                        role="radio"
                        aria-checked={state.rateUnit === unit}
                        onClick={() => patch({ rateUnit: unit })}
                      >
                        {unit === "hour" ? t.perHour : t.perMonth}
                      </button>
                    ))}
                  </div>
                  <div className="wr-seg" role="radiogroup" aria-label="PLN / EUR">
                    {(["PLN", "EUR"] as const).map((cur) => (
                      <button
                        key={cur}
                        type="button"
                        role="radio"
                        aria-checked={state.currency === cur}
                        onClick={() => patch({ currency: cur })}
                      >
                        {cur}
                      </button>
                    ))}
                  </div>
                </div>
                {hint && (
                  <p className="wr-hint">
                    {hint === "looks_monthly" ? t.looksMonthly : t.looksHourly}
                    <button
                      type="button"
                      className="wr-link"
                      onClick={() => patch({ rateUnit: hint === "looks_monthly" ? "month" : "hour" })}
                    >
                      {t.switchUnit}
                    </button>
                  </p>
                )}
                {errors.includes("rate") && <p className="wr-error">{t.errors.rate}</p>}
                {errors.includes("rate_range") && <p className="wr-error">{t.errors.rate_range}</p>}
              </div>
            </fieldset>

            <fieldset className="wr-q">
              <span className="wr-num">02</span>
              <div>
                <legend>{t.modes}</legend>
                <p className="wr-help">{t.modesHelp}</p>
                <div className="wr-seg">
                  {(["remote", "hybrid", "onsite"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      aria-pressed={state.modes.includes(mode)}
                      onClick={() => toggleMode(mode)}
                    >
                      {t.mode[mode]}
                    </button>
                  ))}
                </div>
                {state.modes.includes("hybrid") && (
                  <div className="wr-sub">
                    <p className="wr-label">{t.days}</p>
                    <div className="wr-seg wr-days" role="radiogroup" aria-label={t.days}>
                      {[1, 2, 3, 4, 5].map((d) => (
                        <button
                          key={d}
                          type="button"
                          role="radio"
                          aria-checked={state.onsiteDays === d}
                          onClick={() => patch({ onsiteDays: state.onsiteDays === d ? null : d })}
                        >
                          {d}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {showOffice && (
                  <div className="wr-sub">
                    <label className="wr-label" htmlFor="wr-city">
                      {t.cities}
                    </label>
                    <div className="wr-row">
                      <input
                        id="wr-city"
                        className="wr-input"
                        placeholder={t.cityPlaceholder}
                        value={cityDraft}
                        onChange={(e) => setCityDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            patch({ cities: addCity(state.cities, cityDraft) });
                            setCityDraft("");
                          }
                        }}
                      />
                      <button
                        type="button"
                        className="wr-chip"
                        onClick={() => {
                          patch({ cities: addCity(state.cities, cityDraft) });
                          setCityDraft("");
                        }}
                      >
                        {t.addCity}
                      </button>
                    </div>
                    <div className="wr-chips">
                      {[...state.cities, ...CITY_SUGGESTIONS.filter((c) => !state.cities.includes(c))].map(
                        (city) => {
                          const on = state.cities.includes(city);
                          return (
                            <button
                              key={city}
                              type="button"
                              className="wr-chip"
                              aria-pressed={on}
                              aria-label={on ? `${t.removeCity}: ${city}` : city}
                              onClick={() =>
                                patch({
                                  cities: on
                                    ? state.cities.filter((c) => c !== city)
                                    : addCity(state.cities, city),
                                })
                              }
                            >
                              {city}
                              {on ? " ×" : ""}
                            </button>
                          );
                        },
                      )}
                    </div>
                  </div>
                )}
              </div>
            </fieldset>

            <fieldset className="wr-q">
              <span className="wr-num">03</span>
              <div>
                <legend>{t.start}</legend>
                <div className="wr-seg" role="radiogroup" aria-label={t.start}>
                  {(["now", "date", "notice"] as const).map((kind) => (
                    <button
                      key={kind}
                      type="button"
                      role="radio"
                      aria-checked={state.startKind === kind}
                      onClick={() => patch({ startKind: state.startKind === kind ? null : kind })}
                    >
                      {kind === "now" ? t.startNow : kind === "date" ? t.startDate : t.startNotice}
                    </button>
                  ))}
                </div>
                {state.startKind === "date" && (
                  <div className="wr-sub">
                    <input
                      id="wr-start-date"
                      type="date"
                      className="wr-input"
                      aria-label={t.startDate}
                      value={state.startDate}
                      onChange={(e) => patch({ startDate: e.target.value })}
                    />
                  </div>
                )}
                {state.startKind === "notice" && (
                  <div className="wr-sub wr-row">
                    <input
                      id="wr-notice"
                      className="wr-input wr-amount"
                      inputMode="numeric"
                      aria-label={t.startNotice}
                      value={state.noticeValue}
                      onChange={(e) => patch({ noticeValue: e.target.value.replace(/\D/g, "") })}
                    />
                    <div className="wr-seg" role="radiogroup" aria-label={t.startNotice}>
                      {(["weeks", "months"] as const).map((unit) => (
                        <button
                          key={unit}
                          type="button"
                          role="radio"
                          aria-checked={state.noticeUnit === unit}
                          onClick={() => patch({ noticeUnit: unit })}
                        >
                          {unit === "weeks" ? t.weeks : t.months}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {errors.includes("start") && <p className="wr-error">{t.errors.start}</p>}
              </div>
            </fieldset>

            {errors.includes("empty") && <p className="wr-alert">{t.errors.empty}</p>}
            {networkError && <p className="wr-alert">{t.errors.network}</p>}

            <button type="submit" className="wr-btn" disabled={saving}>
              {saving ? t.saving : t.submit}
              <span aria-hidden="true">→</span>
            </button>
          </form>
        )}
      </main>

      <footer className="wr-foot">
        <div className="wr-foot-inner">
          {/* Zwykły <a>, nie next/link: prefetch RSC trafiał w 307 middleware na
              domenę kariery i CSP connect-src go blokowała (NEXUS-FE-A4).
              Nowa karta, jak w ApplyForm — formularz nie traci wpisanych danych. */}
          <a href="/kariera/rodo" target="_blank" rel="noopener noreferrer">
            {t.privacy}
          </a>
          <span>B2B.NET S.A. · Al. Jerozolimskie 180, 02-486 Warszawa · KRS 0000387063 · NIP 5711707392</span>
        </div>
      </footer>
    </div>
  );
}
