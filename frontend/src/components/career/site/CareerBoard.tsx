"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { CareerBoardCategory, CareerBoardResponse, RemotePolicy } from "@/lib/career/api";
import { BOARD_MODES, BOARD_PAGE, categoryCounts, filterBoard } from "@/lib/career/board";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { deckCategories, nextBatch, openNowLabel, partialMatch } from "@/lib/career/site";

import { OfferApply, type OfferApplyProps } from "./OfferApply";
import { OfferCard } from "./OfferCard";
import { SentGate } from "./SentGate";
import { ChapterMark, siteStyles as s } from "./SiteFrame";

export const CV_ID = "zostaw-cv";

/**
 * Lista otwartych rekrutacji (plansze KarieraA, TelKariera, ListaBrakWynikow,
 * ZostawCV): liczba otwartych rozkłada się na talię czterech kart kategorii,
 * które są filtrem; pod nimi szukajka, tryb pracy, karty ofert i „Pokaż
 * kolejne”, na końcu prośba o CV. Liczby przy kategoriach liczą się po
 * szukaniu i trybie (`categoryCounts`), szukanie bez polskich znaków.
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
  const [category, setCategory] = useState<CareerBoardCategory | null>(null);
  const [cvOpen, setCvOpen] = useState(false);
  const cvRef = useRef<HTMLElement>(null);
  // „Pokaż kolejne” liczy się dla jednego zestawu filtrów; zmiana filtra wraca do pierwszej paczki.
  const filterKey = `${query}|${modes.join(",")}|${category}`;
  const [more, setMore] = useState({ key: "", extra: 0 });
  const extra = more.key === filterKey ? more.extra : 0;

  const filters = useMemo(() => ({ category, query, modes }), [category, query, modes]);
  const counts = useMemo(() => categoryCounts(data.jobs, filters), [data.jobs, filters]);
  const visible = useMemo(() => filterBoard(data.jobs, filters), [data.jobs, filters]);
  const shown = visible.slice(0, BOARD_PAGE + extra);
  const rest = visible.length - shown.length;
  const batch = nextBatch(rest, BOARD_PAGE);
  const total = data.jobs.length;
  const cv = data.cv;
  const rodoHref = careerHref(base, { to: "rodo" });

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
    setCategory(null);
  };
  // Plansza ListaBrakWynikow: hasło bez trafień zamienia liczbę w „0”.
  const noHits = query.trim() !== "" && visible.length === 0;

  // Pusty wynik (plansza ListaBrakWynikow): pierwsze słowo hasła, które samo coś znajduje.
  const partial = useMemo(() => (noHits ? partialMatch(data.jobs, filters) : null), [noHits, data.jobs, filters]);

  const openCv = () => {
    if (cvOpen) cvRef.current?.focus();
    else setCvOpen(true);
  };

  return (
    <main>
      <section className={`${s.ch} ${s.chRed} ${s.hero}`} aria-labelledby={`${uid}-t`}>
        <ChapterMark index={0} count={3} name="Kariera" />
        <div className={s.wrap}>
          <div className={s.heroHeading}>
            <h1 id={`${uid}-t`}>
              <span className={`${s.display} ${s.heroNum}`}>{noHits ? 0 : total}</span>
              <span className={`${s.lead} ${s.heroLead}`}>
                {noHits ? "Nic dla tego hasła" : "Otwarte rekrutacje IT"}
              </span>
            </h1>
            <p className={`${s.body} ${s.heroBody}`}>
              {noHits
                ? `W ${total} otwartych rekrutacjach nie ma „${query.trim()}”.`
                : "Projekty B2B: zdalnie, hybrydowo i stacjonarnie."}
            </p>
          </div>
          <div role="group" aria-label="Kategorie" className={s.deck}>
            {deckCategories().map((c) => (
              <button
                key={c.id}
                type="button"
                aria-pressed={category === c.id}
                onClick={() => setCategory(category === c.id ? null : c.id)}
                className={`${s.card} ${s[`c_${c.id}`]} ${category && category !== c.id ? s.dim : ""}`}
              >
                <b>{counts[c.id]}</b>
                <span>{c.label}</span>
                <i aria-hidden="true">{category === c.id ? "×" : "→"}</i>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className={`${s.ch} ${s.chSnow} ${s.list}`} aria-label="Rekrutacje">
        <ChapterMark index={1} count={3} name="Rekrutacje" />
        <div className={s.wrap}>
          <div className={s.bar} role="search">
            <label className={s.search}>
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <circle cx="7.5" cy="7.5" r="5.5" stroke="currentColor" strokeWidth="1.8" />
                <path d="M12 12l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              <span className={s.srOnly}>Szukaj oferty</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Java, Kraków, Kafka…"
              />
              <span className={`${s.mono} ${s.count}`} aria-live="polite">
                <b>{visible.length}</b> z {total}
              </span>
              {query ? (
                <button type="button" className={s.clear} aria-label="Wyczyść szukanie" onClick={() => setQuery("")}>
                  ×
                </button>
              ) : null}
            </label>
            <div role="group" aria-label="Tryb pracy" className={s.pills}>
              {BOARD_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  aria-pressed={modes.includes(m.id)}
                  onClick={() => toggleMode(m.id)}
                  className={s.pill}
                >
                  {m.label}
                </button>
              ))}
            </div>
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
