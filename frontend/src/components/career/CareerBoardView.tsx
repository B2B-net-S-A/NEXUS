"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import type { CareerBoardResponse, RemotePolicy } from "@/lib/career/api";
import {
  BOARD_CATEGORIES,
  BOARD_MODES,
  BOARD_PAGE,
  NO_FILTERS,
  boardTagLine,
  categoryCounts,
  categoryLabel,
  filterBoard,
  openCountLabel,
  type BoardFilters,
} from "@/lib/career/board";
import { careerHref, type CareerBase } from "@/lib/career/host";

import { BoardBand } from "./BoardBand";
import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { TwoToneTitle } from "./CareerHero";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { TerminalChrome } from "./TerminalChrome";

const CHROME_PATH = "~/b2bnetwork/kariera — zsh";

/**
 * Strona główna kariery: tablica wszystkich otwartych rekrutacji (D1 = A,
 * 20.10.2026) z filtrami, kartami w scenach i „Zostaw CV” (stały link Head of
 * Recruitment). Makiety 6b/6c: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h.
 *
 * `data: null` = API nie odpowiedziało — osobny komunikat, nigdy „brak
 * rekrutacji” (awaria nie może wyglądać jak pusta lista).
 */
export function CareerBoardView({
  data,
  base,
  footer,
  formPreview,
}: {
  data: CareerBoardResponse | null;
  base: CareerBase;
  footer: ReactNode;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const cv = data?.cv ?? null;
  return (
    <CareerSubmitGate
      thanks={{
        variant: "general",
        recruiterFirstName: cv?.first_name ?? "",
        chromePath: CHROME_PATH,
        recruiterPageHref: null,
      }}
    >
      <TerminalChrome path={CHROME_PATH} />
      {data ? (
        <Board data={data} base={base} formPreview={formPreview} />
      ) : (
        <main className="kr-log" role="alert">
          <span>
            <span className="kr-r">[err]</span> <span className="kr-g">ls ~/rekrutacje</span>{" "}
            <span className="kr-c">{"// nie udało się wczytać listy"}</span>
          </span>
          <TwoToneTitle className="kr-log-title" first="Chwilowa" second="przerwa." />
          <span className="kr-log-text">
            Nie udało się wczytać otwartych rekrutacji. Odśwież stronę za chwilę.
          </span>
          <a className="kr-btn" href={careerHref(base, { to: "home" })}>
            $ ./odswiez
          </a>
        </main>
      )}
      {footer}
    </CareerSubmitGate>
  );
}

function Board({
  data,
  base,
  formPreview,
}: {
  data: CareerBoardResponse;
  base: CareerBase;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const uid = useId();
  const [filters, setFilters] = useState<BoardFilters>(NO_FILTERS);
  const [shown, setShown] = useState(BOARD_PAGE);
  const [cvOpen, setCvOpen] = useState(false);
  const cvRef = useRef<HTMLElement | null>(null);
  // Przyklejony przycisk znika, gdy sekcja „Zostaw CV” jest na ekranie —
  // dwa takie same przyciski naraz to szum.
  const [cvInView, setCvInView] = useState(false);
  useEffect(() => {
    const node = cvRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setCvInView(entry.isIntersecting));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const jobs = data.jobs;
  const visible = useMemo(() => filterBoard(jobs, filters), [jobs, filters]);
  const counts = useMemo(() => categoryCounts(jobs, filters), [jobs, filters]);
  const filtered =
    filters.category !== null || filters.query.trim() !== "" || filters.modes.length > 0;

  const update = (next: Partial<BoardFilters>) => {
    setFilters((f) => ({ ...f, ...next }));
    setShown(BOARD_PAGE);
  };
  const toggleMode = (mode: RemotePolicy) =>
    update({
      modes: filters.modes.includes(mode)
        ? filters.modes.filter((m) => m !== mode)
        : [...filters.modes, mode],
    });
  const openCv = () => {
    setCvOpen(true);
    // Po wyrenderowaniu formularza — przewinięcie i fokus na sekcję.
    requestAnimationFrame(() => {
      cvRef.current?.scrollIntoView?.({ block: "start" });
      cvRef.current?.focus();
    });
  };

  const rest = visible.length - shown;
  const cv = data.cv;

  return (
    <main className="kr-board">
      <div className="kr-board-hero">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          ls ~/rekrutacje --open
        </span>
        <TwoToneTitle className="kr-title kr-board-h1" first="Otwarte rekrutacje IT" second="B2B Network." />
        <span className="kr-g">
          [{jobs.length > 0 ? `${openCountLabel(jobs.length)} · ` : ""}projekty B2B · zdalnie,
          hybrydowo, stacjonarnie]
        </span>
      </div>

      {jobs.length === 0 ? (
        <section className="kr-board-empty" aria-label="Brak otwartych rekrutacji">
          <p className="kr-cmd">
            <b aria-hidden="true">$ </b>ls ~/rekrutacje --open
          </p>
          <p className="kr-board-empty-title">Brak otwartych rekrutacji.</p>
          <p className="kr-g">
            {"// nowe projekty pojawiają się co tydzień — zostaw CV, odezwiemy się"}
          </p>
        </section>
      ) : (
        <>
          <div className="kr-board-filters">
            <div className="kr-board-chips kr-board-cats" role="group" aria-label="Kategoria">
              <button
                type="button"
                className="kr-chip"
                aria-pressed={filters.category === null}
                onClick={() => update({ category: null })}
              >
                wszystkie · {counts.all}
              </button>
              {BOARD_CATEGORIES.filter(
                (c) => counts[c.id] > 0 || filters.category === c.id,
              ).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="kr-chip"
                  aria-pressed={filters.category === c.id}
                  onClick={() => update({ category: filters.category === c.id ? null : c.id })}
                >
                  {c.label} · {counts[c.id]}
                </button>
              ))}
            </div>
            <div className="kr-board-search-row">
              <label className="kr-board-search" htmlFor={`${uid}-q`}>
                <span className="kr-r" aria-hidden="true">
                  grep
                </span>
                <input
                  id={`${uid}-q`}
                  type="search"
                  aria-label="Szukaj w rekrutacjach"
                  className="kr-board-input"
                  placeholder="java, kraków, kafka…"
                  value={filters.query}
                  onChange={(e) => update({ query: e.target.value })}
                  autoComplete="off"
                />
              </label>
              <div className="kr-board-chips" role="group" aria-label="Tryb pracy">
                {BOARD_MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className="kr-chip"
                    aria-pressed={filters.modes.includes(m.id)}
                    onClick={() => toggleMode(m.id)}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            <p className="kr-board-count kr-g" aria-live="polite">
              {filtered ? `[${visible.length} z ${jobs.length} pasuje do filtrów]` : null}
            </p>
          </div>

          {visible.length === 0 ? (
            <div className="kr-board-empty">
              <p className="kr-board-empty-title">Nic nie pasuje do filtrów.</p>
              <button
                type="button"
                className="kr-btn-outline kr-board-reset"
                onClick={() => update(NO_FILTERS)}
              >
                $ wyczyść filtry
              </button>
            </div>
          ) : (
            <ul className="kr-board-grid">
              {visible.slice(0, shown).map((job) => (
                <li key={job.slug}>
                  <a className="kr-board-card" href={careerHref(base, { to: "job", slug: job.slug })}>
                    <BoardBand theme={job.theme} category={categoryLabel(job.category)} />
                    <span className="kr-board-body">
                      <span className="kr-board-title">{job.title}</span>
                      {job.subtitle ? <span className="kr-board-sub">{job.subtitle}</span> : null}
                      {boardTagLine(job) ? (
                        <span className="kr-board-tag">[{boardTagLine(job)}]</span>
                      ) : null}
                    </span>
                    <span className="kr-board-foot">
                      <span>rekruter: {job.recruiter_first_name}</span>
                      <span className="kr-r">./aplikuj →</span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}

          {rest > 0 ? (
            <button
              type="button"
              className="kr-board-more"
              onClick={() => setShown((n) => n + BOARD_PAGE)}
            >
              $ more — pokaż kolejne {Math.min(rest, BOARD_PAGE)}
              {rest > BOARD_PAGE ? ` z ${rest}` : ""}
            </button>
          ) : null}
        </>
      )}

      {cv ? (
        <section
          ref={cvRef}
          id="zostaw-cv"
          className="kr-board-cv"
          aria-labelledby={`${uid}-cv`}
          tabIndex={-1}
        >
          <div className="kr-board-cv-head">
            <div className="kr-board-cv-text">
              <span className="kr-g">
                <span className="kr-r" aria-hidden="true">
                  ${" "}
                </span>
                ./zostaw-cv
              </span>
              <h2 id={`${uid}-cv`} className="kr-board-cv-title">
                Nie widzisz nic dla siebie?
              </h2>
              <span className="kr-board-cv-note">
                Zostaw CV — odezwiemy się, gdy pojawi się projekt w Twojej technologii.
              </span>
            </div>
            {cvOpen ? null : (
              <button type="button" className="kr-btn kr-board-cv-btn" onClick={openCv}>
                Zostaw CV
              </button>
            )}
          </div>
          {cvOpen ? (
            <div className="kr-form-box kr-board-form">
              <div className="kr-form-bar">
                <span>
                  <span className="kr-r" aria-hidden="true">
                    ${" "}
                  </span>
                  ./dolacz-do-bazy.sh
                </span>
                <span className="kr-g">~2 min</span>
              </div>
              <CareerApplyForm
                linkSlug={cv.slug}
                variant="general"
                rodoHref={careerHref(base, { to: "rodo" })}
                preview={formPreview}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      {cv && !cvOpen && !cvInView ? (
        <div className="kr-board-sticky">
          <button type="button" className="kr-btn kr-board-sticky-btn" onClick={openCv}>
            Zostaw CV — odezwiemy się
          </button>
        </div>
      ) : null}
    </main>
  );
}
