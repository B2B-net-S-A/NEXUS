"use client";

import gsap from "gsap";
import { Flip } from "gsap/Flip";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { CareerBoardJob, CareerBoardResponse, RemotePolicy } from "@/lib/career/api";
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

import { BrandArc, BrandPage, BrandTitle, brandStyles as s } from "./brand/BrandShell";
import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { CareerThemeScope } from "./CareerThemeScope";
import { DEFAULT_CAREER_THEME, type CareerThemeId } from "./themes";

gsap.registerPlugin(Flip);

const CV_ID = "zostaw-cv";
/** Ile wymagań na karcie — więcej i karta przestaje być skanowalna. */
const CARD_TAGS = 4;

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
 * 20.10.2026) z filtrami i „Zostaw CV” (stały link Head of Recruitment).
 * Od 29.10.2026 w barwach marki B2B Network jak szablony ogłoszeń (Grafit),
 * zamiast okna terminala: karty z faktami i wymaganiami zamiast podglądu sceny.
 *
 * `data: null` = API nie odpowiedziało — osobny komunikat, nigdy „brak
 * rekrutacji” (awaria nie może wyglądać jak pusta lista).
 */
export function CareerBoardView({
  data,
  base,
  host,
  theme = DEFAULT_CAREER_THEME,
  formPreview,
}: {
  data: CareerBoardResponse | null;
  base: CareerBase;
  /** Adres w stopce, np. „kariera.b2bnetwork.pl”. */
  host: string;
  theme?: CareerThemeId;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const cv = data?.cv ?? null;
  const homeHref = careerHref(base, { to: "home" });
  return (
    <CareerThemeScope theme={theme}>
      <CareerSubmitGate
        thanks={{
          variant: "general",
          recruiterFirstName: cv?.first_name ?? "",
          homeHref,
          rodoHref: careerHref(base, { to: "rodo" }),
          hostLabel: host,
          recruiterPageHref: null,
        }}
      >
        <BrandPage
          homeHref={homeHref}
          homeLabel={null}
          cta={cv ? { href: `#${CV_ID}`, label: "Zostaw CV" } : null}
          rodoHref={careerHref(base, { to: "rodo" })}
          hostLabel={host}
        >
          {data ? (
            <Board data={data} base={base} formPreview={formPreview} />
          ) : (
            <main className={s.main}>
              <div className={`${s.wrap} ${s.message}`} role="alert">
                <BrandTitle text="Chwilowa przerwa." />
                <p className={s.messageText}>
                  Nie udało się wczytać otwartych rekrutacji. Odśwież stronę za chwilę.
                </p>
                <div className={`${s.actions} ${s.messageActions}`}>
                  <a className={s.btn} href={homeHref}>
                    Odśwież stronę
                  </a>
                </div>
              </div>
            </main>
          )}
        </BrandPage>
      </CareerSubmitGate>
    </CareerThemeScope>
  );
}

function JobCard({ job, href }: { job: CareerBoardJob; href: string }) {
  const where = boardTagLine(job);
  const tags = (job.must ?? []).slice(0, CARD_TAGS);
  return (
    <a className={s.card} href={href}>
      {job.category ? <span className={s.cardKicker}>{categoryLabel(job.category)}</span> : null}
      <span className={s.cardTitle}>{job.title}</span>
      {job.subtitle ? <span className={s.cardSub}>{job.subtitle}</span> : null}
      {tags.length > 0 ? (
        <span className={s.chips}>
          {tags.map((t) => (
            <span key={t} className={s.tag}>
              {t}
            </span>
          ))}
        </span>
      ) : null}
      <span className={s.cardFoot}>
        <span className={s.cardMeta}>
          {where ? <span>{where}</span> : null}
          <span>Rekruter: {job.recruiter_first_name}</span>
        </span>
        <span className={s.cardGo}>Zobacz {ARROW}</span>
      </span>
    </a>
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
  // „Zostaw CV” w przyklejonym pasku (także na telefonie, zamiast osobnego
  // dolnego przycisku) to kotwica — po przejściu na nią formularz otwiera się sam.
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === `#${CV_ID}`) setCvOpen(true);
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const jobs = data.jobs;
  const visible = useMemo(() => filterBoard(jobs, filters), [jobs, filters]);
  const counts = useMemo(() => categoryCounts(jobs, filters), [jobs, filters]);
  // Filtr przestawia karty płynnie (GSAP Flip, etap 7): stan sprzed zmiany
  // zapisany tutaj, animacja po wyrenderowaniu nowej listy.
  const listRef = useRef<HTMLUListElement | null>(null);
  const flipState = useRef<Flip.FlipState | null>(null);
  const update = (next: Partial<BoardFilters>) => {
    const rows = listRef.current?.querySelectorAll(`.${s.cardItem}`);
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
    const rows = listRef.current?.querySelectorAll(`.${s.cardItem}`);
    if (!state || !rows) return;
    Flip.from(state, {
      targets: rows,
      duration: 0.5,
      ease: "power3.inOut",
      onEnter: (els) => gsap.fromTo(els, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.35, delay: 0.1 }),
    });
  }, [visible]);

  const rest = visible.length - shown;
  const cv = data.cv;

  return (
    <main className={s.main}>
      <div className={s.hero}>
        <div className={s.glow} aria-hidden="true" />
        <BrandArc />
        <div className={`${s.wrap} ${s.heroInner}`}>
          <p className={s.kicker}>Kariera w B2B Network</p>
          <BrandTitle text="Otwarte rekrutacje IT" />
          <p className={s.lead}>
            {jobs.length > 0 ? `${openCountLabel(jobs.length)} · ` : ""}Projekty B2B — zdalnie,
            hybrydowo i stacjonarnie.
          </p>
        </div>
      </div>

      <div className={s.wrap}>
        {jobs.length === 0 ? (
          <section className={s.empty} aria-label="Brak otwartych rekrutacji">
            <p className={s.emptyTitle}>Brak otwartych rekrutacji.</p>
            <p className={s.note}>Nowe projekty pojawiają się co tydzień — zostaw CV, odezwiemy się.</p>
          </section>
        ) : (
          <>
            <div className={s.filters}>
              <div className={`${s.chips} ${s.scrollRow}`} role="group" aria-label="Kategoria">
                <button
                  type="button"
                  className={s.chip}
                  aria-pressed={filters.category === null}
                  onClick={() => update({ category: null })}
                >
                  Wszystkie · {counts.all}
                </button>
                {BOARD_CATEGORIES.filter((c) => counts[c.id] > 0 || filters.category === c.id).map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={s.chip}
                    aria-pressed={filters.category === c.id}
                    onClick={() => update({ category: filters.category === c.id ? null : c.id })}
                  >
                    {c.label} · {counts[c.id]}
                  </button>
                ))}
              </div>
              <div className={s.searchRow}>
                <label className={s.search} htmlFor={`${uid}-q`}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <circle cx="11" cy="11" r="7" />
                    <path d="m20 20-3.5-3.5" />
                  </svg>
                  <input
                    id={`${uid}-q`}
                    type="search"
                    aria-label="Szukaj w rekrutacjach"
                    className={s.searchInput}
                    placeholder="Java, Kraków, Kafka…"
                    value={filters.query}
                    onChange={(e) => update({ query: e.target.value })}
                    autoComplete="off"
                  />
                  <output className={s.searchCount} htmlFor={`${uid}-q`} aria-live="polite" data-testid="board-count">
                    <b>{visible.length}</b> z {jobs.length}
                  </output>
                </label>
                <div className={`${s.chips} ${s.scrollRow}`} role="group" aria-label="Tryb pracy">
                  {BOARD_MODES.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className={s.chip}
                      aria-pressed={filters.modes.includes(m.id)}
                      onClick={() => toggleMode(m.id)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {visible.length === 0 ? (
              <div className={s.empty}>
                <p className={s.emptyTitle}>Nic nie pasuje do filtrów.</p>
                <button type="button" className={s.btnOutline} onClick={() => update(NO_FILTERS)}>
                  Wyczyść filtry
                </button>
              </div>
            ) : (
              <ul className={`${s.cards} ${visible.length === 1 ? s.cardsOne : ""}`} ref={listRef}>
                {visible.slice(0, shown).map((job) => (
                  <li key={job.slug} className={s.cardItem}>
                    <JobCard job={job} href={careerHref(base, { to: "job", slug: job.slug })} />
                  </li>
                ))}
              </ul>
            )}

            {rest > 0 ? (
              <div className={s.more}>
                <button type="button" className={s.btnOutline} onClick={() => setShown((n) => n + BOARD_PAGE)}>
                  Pokaż kolejne {Math.min(rest, BOARD_PAGE)}
                  {rest > BOARD_PAGE ? ` z ${rest}` : ""}
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>

      {cv ? (
        <div className={`${s.wrap} ${s.section}`} style={{ paddingTop: 48 }}>
          <section
            ref={cvRef}
            id={CV_ID}
            className={s.apply}
            aria-labelledby={`${uid}-cv`}
            tabIndex={-1}
          >
            <div className={s.applyHead}>
              <div>
                <h2 id={`${uid}-cv`} className={s.applyTitle}>
                  Nie widzisz nic dla siebie?
                </h2>
                <p className={s.note}>
                  Zostaw CV — odezwiemy się, gdy pojawi się projekt w Twojej technologii.
                </p>
              </div>
              {cvOpen ? null : (
                <button type="button" className={s.btn} onClick={openCv}>
                  Zostaw CV
                </button>
              )}
            </div>
            {cvOpen ? (
              <div className={`${s.applyForm} ${s.form}`}>
                <CareerApplyForm
                  linkSlug={cv.slug}
                  variant="general"
                  rodoHref={careerHref(base, { to: "rodo" })}
                  preview={formPreview}
                  tone="plain"
                />
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

    </main>
  );
}
