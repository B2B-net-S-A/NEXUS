"use client";

import gsap from "gsap";
import { Flip } from "gsap/Flip";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

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

import { BoardGlyph, BoardPreviewScene } from "./BoardPreview";
import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { TwoToneTitle } from "./CareerHero";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { TerminalChrome } from "./TerminalChrome";

const CHROME_PATH = "~/b2bnetwork/kariera — zsh";

gsap.registerPlugin(Flip);

function prefersMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const ARROW = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

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
  // Filtr przestawia wiersze płynnie (GSAP Flip, etap 7): stan sprzed zmiany
  // zapisany tutaj, animacja po wyrenderowaniu nowej listy.
  const listRef = useRef<HTMLUListElement | null>(null);
  const flipState = useRef<Flip.FlipState | null>(null);
  const update = (next: Partial<BoardFilters>) => {
    const rows = listRef.current?.querySelectorAll(".kr-brow-item");
    flipState.current = rows && rows.length > 0 && prefersMotion() ? Flip.getState(rows) : null;
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

  useLayoutEffect(() => {
    const state = flipState.current;
    flipState.current = null;
    const rows = listRef.current?.querySelectorAll(".kr-brow-item");
    if (!state || !rows) return;
    Flip.from(state, {
      targets: rows,
      duration: 0.5,
      ease: "power3.inOut",
      onEnter: (els) => gsap.fromTo(els, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.35, delay: 0.1 }),
    });
  }, [visible]);

  // Podgląd: wiersz pod myszą albo z fokusem; bez wskazania — pierwszy na liście.
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const active = visible.find((j) => j.slug === activeSlug) ?? visible[0] ?? null;

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
                <output className="kr-board-out" htmlFor={`${uid}-q`} aria-live="polite">
                  <b>{visible.length}</b> z {jobs.length}
                </output>
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
          </div>

          <div className="kr-board-split">
            <div className="kr-board-listcol">
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
                <ul className="kr-brows" ref={listRef}>
                  {visible.slice(0, shown).map((job) => (
                    <li key={job.slug} className="kr-brow-item">
                      <a
                        className="kr-brow"
                        href={careerHref(base, { to: "job", slug: job.slug })}
                        data-active={active?.slug === job.slug ? "" : undefined}
                        onMouseEnter={() => setActiveSlug(job.slug)}
                        onFocus={() => setActiveSlug(job.slug)}
                      >
                        <BoardGlyph theme={job.theme} />
                        <span className="kr-brow-main">
                          <span className="kr-brow-title">{job.title}</span>
                          {job.subtitle ? <span className="kr-brow-sub">{job.subtitle}</span> : null}
                          <span className="kr-brow-meta">
                            {[boardTagLine(job), categoryLabel(job.category), `rekruter: ${job.recruiter_first_name}`]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </span>
                        <span className="kr-brow-go">Zobacz {ARROW}</span>
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
            </div>

            {active ? (
              // Podgląd jest dodatkiem dla myszy; klawiatura i czytnik idą
              // wierszami listy, więc tu nic nie łapie fokusu.
              <a
                className="kr-board-preview"
                href={careerHref(base, { to: "job", slug: active.slug })}
                tabIndex={-1}
                aria-hidden="true"
              >
                <BoardPreviewScene job={active} />
                <span className="kr-board-preview-title">{active.title}</span>
                <span className="kr-board-preview-go">Zobacz rekrutację {ARROW}</span>
              </a>
            ) : null}
          </div>
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
