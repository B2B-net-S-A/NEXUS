"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { CareerBoardResponse, RemotePolicy } from "@/lib/career/api";
import { BOARD_MODES, BOARD_PAGE, filterBoard } from "@/lib/career/board";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { openRecruitmentsIT } from "@/lib/career/ogText";
import { inCities, onMap } from "@/lib/career/polandMap";
import { facetCounts, jobFacetIds, nextBatch, openNowLabel, partialMatch, pluralForm } from "@/lib/career/site";

import g from "./glass.module.css";
import { CityColumnsMap, GhostMap } from "./GlassMap";

import { OfferApply, type OfferApplyProps } from "./OfferApply";
import { OfferCard } from "./OfferCard";
import { SentGate } from "./SentGate";
import { ChapterMark, siteStyles as s } from "./SiteFrame";

export const CV_ID = "zostaw-cv";

/** Ile miast w chipach nad listą (reszta zostaje w szukajce). */
const CHIPS = 12;

/** „101 ofert” (nagłówek listy) i „Pokaż 1 ofertę” (biernik w przycisku szukajki). */
export function offersLabel(n: number, kase: "nom" | "acc"): string {
  const f = pluralForm(n);
  if (f === "one") return kase === "acc" ? "1 ofertę" : "1 oferta";
  return f === "few" ? `${n} oferty` : `${n} ofert`;
}

/** Hasło na pustej kolumnie mapy: krótkie, żeby nie wyszło poza mapę. */
function ghostWord(query: string): string {
  const q = query.trim();
  return q.length > 22 ? `${q.slice(0, 21)}…` : q;
}

/**
 * Lista otwartych rekrutacji (plansze KarieraA, TelKariera, ListaBrakWynikow,
 * ZostawCV): liczba otwartych i talia czterech kart z miastami (zamiast
 * kategorii, decyzja 23.11.2026), które są filtrem, reszta miast w chipach; pod nimi szukajka, tryb
 * pracy, karty ofert i „Pokaż kolejne”, na końcu prośba o CV. Liczby na
 * kartach liczą się po szukaniu i trybie, szukanie bez polskich znaków.
 *
 * `data: null` = API nie odpowiedziało — osobny komunikat, nigdy „brak
 * rekrutacji” (awaria nie może wyglądać jak pusta lista).
 */
export function CareerBoard({
  data,
  base,
  formPreview,
}: {
  data: CareerBoardResponse | null;
  base: CareerBase;
  formPreview?: OfferApplyProps["preview"];
}) {
  if (!data) {
    return (
      <main>
        <section className={`${s.ch} ${s.chRed} ${s.hero}`}>
          <div className={s.wrap} role="alert">
            <p aria-hidden="true" className={`${s.display} ${s.heroNum}`}>
              ?
            </p>
            <h1 className={`${s.lead} ${s.heroLead}`}>Chwilowa przerwa</h1>
            <p className={`${s.body} ${s.heroBody}`}>
              Nie udało się wczytać otwartych rekrutacji. Odśwież stronę za chwilę.
            </p>
            <div className={s.actions}>
              <a className={`${s.btn} ${s.btnWhite}`} href={careerHref(base, { to: "home" })}>
                Odśwież stronę
              </a>
            </div>
          </div>
        </section>
      </main>
    );
  }
  return (
    <SentGate
      sent={{ variant: "general", recruiterFirstName: data.cv?.first_name ?? "", others: [], base }}
    >
      <Board data={data} base={base} formPreview={formPreview} />
    </SentGate>
  );
}

function Board({
  data,
  base,
  formPreview,
}: {
  data: CareerBoardResponse;
  base: CareerBase;
  formPreview?: OfferApplyProps["preview"];
}) {
  const uid = useId();
  const [query, setQuery] = useState("");
  const [modes, setModes] = useState<RemotePolicy[]>([]);
  const [facet, setFacet] = useState<string | null>(null);
  const [cvOpen, setCvOpen] = useState(false);
  const cvRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLElement>(null);
  // „Pokaż kolejne” liczy się dla jednego zestawu filtrów; zmiana filtra wraca do pierwszej paczki.
  const filterKey = `${query}|${modes.join(",")}|${facet}`;
  const [more, setMore] = useState({ key: "", extra: 0 });
  const extra = more.key === filterKey ? more.extra : 0;

  const filters = useMemo(() => ({ category: null, query, modes }), [query, modes]);
  // Liczby przy miastach / technologiach liczą się po szukaniu i trybie, bez samego wyboru.
  const searched = useMemo(() => filterBoard(data.jobs, filters), [data.jobs, filters]);
  const facets = useMemo(() => facetCounts(searched), [searched]);
  // Talia i wiersz pod szukajką stoją na liczbach z całej listy, żeby karty nie skakały przy pisaniu.
  const allFacets = useMemo(() => facetCounts(data.jobs), [data.jobs]);
  const countOf = (id: string) => facets.find((f) => f.id === id)?.count ?? 0;
  const visible = useMemo(
    () => (facet ? searched.filter((j) => jobFacetIds(j).includes(facet)) : searched),
    [searched, facet],
  );
  const shown = visible.slice(0, BOARD_PAGE + extra);
  const rest = visible.length - shown.length;
  const batch = nextBatch(rest, BOARD_PAGE);
  const total = data.jobs.length;
  const cv = data.cv;
  const rodoHref = careerHref(base, { to: "rodo" });
  const cities = inCities(allFacets.filter((f) => onMap(f.label)).length);

  // Wejście z `#zostaw-cv` (np. z zamkniętej oferty) od razu otwiera formularz.
  useEffect(() => {
    if (cv && window.location.hash === `#${CV_ID}`) setCvOpen(true);
  }, [cv]);
  useEffect(() => {
    if (cvOpen) cvRef.current?.focus();
  }, [cvOpen]);

  const toggleMode = (m: RemotePolicy) =>
    setModes((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));
  const clearAll = () => {
    setQuery("");
    setModes([]);
    setFacet(null);
  };
  // Plansza ListaBrakWynikow: hasło bez trafień zamienia liczbę w „0”.
  const noHits = query.trim() !== "" && visible.length === 0;

  // Pusty wynik (plansza ListaBrakWynikow): pierwsze słowo hasła, które samo coś znajduje.
  const partial = useMemo(() => (noHits ? partialMatch(data.jobs, filters) : null), [noHits, data.jobs, filters]);

  const openCv = () => {
    if (cvOpen) cvRef.current?.focus();
    else setCvOpen(true);
  };

  const lead = total > 0 ? (
    <>
      <strong>{openRecruitmentsIT(total)}</strong> w bankowości, AI, danych i testach. Zdalnie, hybrydowo albo w biurze
      {cities ? `, ${cities}` : ""}.
    </>
  ) : (
    "Teraz nie prowadzimy otwartych rekrutacji. Zostaw CV, odezwiemy się, gdy pojawi się projekt."
  );

  return (
    <main>
      <section className={`${s.ch} ${s.chRed} ${g.heroA}`} aria-labelledby={`${uid}-t`}>
        <ChapterMark index={0} count={3} name="Kariera" />
        <div className={`${s.wrap} ${g.heroGrid}`}>
          <div className={g.heroText}>
            <h1 id={`${uid}-t`} className={g.heroTitle}>
              Dołącz do projektów, które muszą działać.
            </h1>
            <p className={g.heroLead}>{lead}</p>
            <form
              role="search"
              className={g.heroSearch}
              onSubmit={(e) => {
                e.preventDefault();
                listRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
              }}
            >
              <div className={g.heroField}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <circle cx="8.5" cy="8.5" r="6.5" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M13.5 13.5 L18 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
                <label htmlFor={`${uid}-q`} className={s.srOnly}>
                  Technologia, rola albo miasto
                </label>
                <input
                  id={`${uid}-q`}
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Java, Kafka, Gdańsk…"
                />
                {query ? (
                  <>
                    <span className={g.heroCount} aria-live="polite">
                      {visible.length} z {total}
                    </span>
                    <button type="button" className={g.heroClear} aria-label="Wyczyść szukanie" onClick={() => setQuery("")}>
                      ×
                    </button>
                  </>
                ) : null}
              </div>
              <button type="submit" className={g.heroGo}>
                Pokaż {offersLabel(visible.length, "acc")}
              </button>
            </form>
            <div role="group" aria-label="Tryb pracy" className={g.heroModes}>
              {BOARD_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  aria-pressed={modes.includes(m.id)}
                  onClick={() => toggleMode(m.id)}
                  className={g.mode}
                >
                  {m.label}
                </button>
              ))}
              {cv ? (
                <a
                  href={`#${CV_ID}`}
                  className={g.heroCv}
                  onClick={(e) => {
                    e.preventDefault();
                    openCv();
                  }}
                >
                  Nic dla Ciebie? Zostaw CV
                </a>
              ) : null}
            </div>
          </div>
          {allFacets.length > 0 ? (
            <div className={g.heroMap}>
              <CityColumnsMap uid={`${uid}-md`} facets={allFacets} className={g.mapDesk} />
              <CityColumnsMap uid={`${uid}-mp`} facets={allFacets} phone className={g.mapPhone} />
            </div>
          ) : null}
        </div>
        <svg viewBox="0 0 1440 80" preserveAspectRatio="none" aria-hidden="true" className={g.wave}>
          <path d="M0,44 C220,6 470,74 720,40 C960,8 1200,66 1440,30 L1440,80 L0,80 Z" fill="#FAF6F4" />
        </svg>
      </section>

      <section ref={listRef} className={`${s.ch} ${s.chSnow} ${s.list}`} aria-label="Rekrutacje">
        <ChapterMark index={1} count={3} name="Rekrutacje" />
        <div className={s.wrap}>
          <div className={g.listHead}>
            <h2 className={g.listTitle}>{offersLabel(visible.length, "nom")}</h2>
            {allFacets.length > 0 ? (
              <div role="group" aria-label="Miasta" className={g.cityChips}>
                <button type="button" aria-pressed={facet === null} onClick={() => setFacet(null)} className={g.cityChip}>
                  Wszystkie
                </button>
                {allFacets.slice(0, CHIPS).map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={facet === f.id}
                    onClick={() => setFacet(facet === f.id ? null : f.id)}
                    className={g.cityChip}
                  >
                    {f.label} {countOf(f.id)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          {shown.length > 0 ? (
            <div className={s.grid}>
              {shown.map((j) => (
                <OfferCard key={j.slug} job={j} href={careerHref(base, { to: "job", slug: j.slug })} />
              ))}
            </div>
          ) : total === 0 ? (
            <div className={s.none}>
              <div className={s.empty} role="status">
                <h2>Brak otwartych rekrutacji</h2>
                <p>Teraz nie prowadzimy otwartych rekrutacji. Zostaw CV, odezwiemy się, gdy pojawi się projekt.</p>
                {cv ? (
                  <div className={s.actions}>
                    <button type="button" className={`${s.btn} ${s.btnRed}`} onClick={openCv}>
                      Zostaw CV
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className={s.none}>
              {query.trim() ? (
                <div className={g.emptyA}>
                  <GhostMap uid={`${uid}-gh`} word={ghostWord(query)} />
                  <div className={s.empty} role="status">
                    <h2>
                      {`Nie mamy teraz projektu dla „${query.trim()}”.`}
                    </h2>
                    <p>
                      Wyczyść filtry{cv ? " albo zostaw CV. Odezwiemy się, gdy pojawi się projekt w Twojej technologii." : "."}
                    </p>
                    <div className={s.actions}>
                      <button type="button" className={`${s.btn} ${s.btnInk}`} onClick={clearAll}>
                        Wyczyść filtry
                      </button>
                      {cv ? (
                        <button type="button" className={`${s.btn} ${s.btnRed}`} onClick={openCv}>
                          Zostaw CV
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : (
              <div className={s.empty} role="status">
                <h2>
                  {query.trim()
                    ? `Nie mamy teraz projektu dla „${query.trim()}”.`
                    : "Nie mamy teraz projektu z tymi filtrami."}
                </h2>
                <p>
                  Wyczyść filtry{cv ? " albo zostaw CV. Odezwiemy się, gdy pojawi się projekt w Twojej technologii." : "."}
                </p>
                <div className={s.actions}>
                  <button type="button" className={`${s.btn} ${s.btnInk}`} onClick={clearAll}>
                    Wyczyść filtry
                  </button>
                  {cv ? (
                    <button type="button" className={`${s.btn} ${s.btnRed}`} onClick={openCv}>
                      Zostaw CV
                    </button>
                  ) : null}
                </div>
              </div>
              )}
              {partial ? (
                <div>
                  <h3 className={s.altTitle}>
                    Dla „{partial.word}” {openNowLabel(partial.jobs.length)}:
                  </h3>
                  <OfferCard job={partial.jobs[0]} href={careerHref(base, { to: "job", slug: partial.jobs[0].slug })} />
                </div>
              ) : null}
            </div>
          )}
          {batch > 0 ? (
            <button type="button" onClick={() => setMore({ key: filterKey, extra: extra + batch })} className={s.more}>
              Pokaż kolejne {batch} z {rest}
            </button>
          ) : null}
        </div>
      </section>

      {cv ? (
        <>
          <section className={`${s.ch} ${s.chInk} ${s.end}`} aria-labelledby={`${uid}-cv`}>
            <ChapterMark index={2} count={3} name="CV" />
            <div className={`${s.wrap} ${s.endInner}`}>
              <div>
                <h2 id={`${uid}-cv`}>Nie widzisz nic dla siebie?</h2>
                <p>Zostaw CV, odezwiemy się, gdy pojawi się projekt w Twojej technologii.</p>
              </div>
              <a
                href={`#${CV_ID}`}
                className={`${s.btn} ${s.btnRed} ${s.endCta}`}
                aria-expanded={cvOpen}
                aria-controls={CV_ID}
                onClick={(e) => {
                  e.preventDefault();
                  openCv();
                }}
              >
                Zostaw CV
              </a>
            </div>
          </section>
          <section
            id={CV_ID}
            ref={cvRef}
            tabIndex={-1}
            hidden={!cvOpen}
            className={`${s.ch} ${s.chInk} ${s.cvSection}`}
            aria-label="Zostaw CV"
          >
            <div className={s.wrap}>
              <OfferApply
                linkSlug={cv.slug}
                variant="general"
                rodoHref={rodoHref}
                recruiterFirstName={cv.first_name}
                preview={formPreview}
                intro={
                  <>
                    <p aria-hidden="true" className={`${s.display} ${s.cvBig}`}>
                      CV
                    </p>
                    <h2 className={s.lead}>Zostaw CV, odezwiemy się, gdy pojawi się projekt w Twojej technologii.</h2>
                    <p className={s.body}>
                      To zgłoszenie nie dotyczy konkretnej oferty, więc prosimy tylko o zgodę na przyszłe
                      rekrutacje. Dane przechowujemy do czasu wycofania zgody, nie dłużej niż 3 lata.
                    </p>
                    <ol className={s.next}>
                      <li>
                        <span className={s.mono}>01</span>Zostawiasz CV
                      </li>
                      <li>
                        <span className={s.mono}>02</span>Pojawia się projekt w Twojej technologii
                      </li>
                      <li>
                        <span className={s.mono}>03</span>Odzywamy się do Ciebie
                      </li>
                    </ol>
                  </>
                }
              />
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
