"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { CareerBoardJob } from "@/lib/career/api";
import { careerHref, type CareerBase } from "@/lib/career/host";
import type { ProcessStep } from "../requirementItems";

import { OfferCard } from "./OfferCard";
import { capitalize } from "@/lib/career/site";

import g from "./glass.module.css";
import { CheckIcon, ChapterMark, siteStyles as s } from "./SiteFrame";

export interface SentResult {
  firstName: string;
  email: string;
  fileName: string | null;
}

/** Kontekst ekranu po wysłaniu — dane z widoku, który pokazał formularz. */
export interface SentContext {
  variant: "job" | "general";
  recruiterFirstName: string;
  jobTitle?: string;
  steps?: ProcessStep[];
  /** Inne otwarte oferty (z tablicy) pod podziękowaniem. */
  others: CareerBoardJob[];
  base: CareerBase;
  /** Liczba otwartych ofert z tablicy do „Wszystkie oferty (101)”; `null` = bez liczby. */
  total?: number | null;
}

const Ctx = createContext<((r: SentResult) => void) | null>(null);

export function useSent(): ((r: SentResult) => void) | null {
  return useContext(Ctx);
}

/**
 * Po wysłaniu formularza cała treść strony zamienia się w ekran „Wysłane”
 * (plansza AplikacjaWyslana). Strona renderuje się na serwerze, więc bramka
 * trzyma stan po stronie klienta, a formularz zgłasza sukces przez kontekst.
 */
export function SentGate({ sent, children }: { sent: SentContext; children: ReactNode }) {
  const [result, setResult] = useState<SentResult | null>(null);
  if (result) return <OfferSent {...sent} result={result} />;
  return (
    <Ctx.Provider
      value={(r) => {
        setResult(r);
        try {
          window.scrollTo({ top: 0 });
        } catch {
          // jsdom nie ma scrollTo — bez znaczenia dla treści.
        }
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

/**
 * Dopełniacz imienia do „CV jest u Marka.” (makieta O-wyslane). Reguły dla
 * typowych polskich imion; imię, którego nie umiemy odmienić, daje `null`
 * i ekran mówi „CV jest u nas.”, zamiast zgadywać formę.
 */
const GENITIVE: [RegExp, (n: string) => string][] = [
  [/[ij]a$/i, (n) => `${n.slice(0, -1)}i`],
  [/la$/i, (n) => `${n.slice(0, -1)}i`],
  [/[kg]a$/i, (n) => `${n.slice(0, -1)}i`],
  [/a$/i, (n) => `${n.slice(0, -1)}y`],
  [/eł$/i, (n) => `${n.slice(0, -2)}ła`],
  [/ek$/i, (n) => `${n.slice(0, -2)}ka`],
  [/[bcdfghjklłmnprstwz]$/i, (n) => `${n}a`],
];
export function atName(name: string): string | null {
  const n = name.trim();
  if (!n || /\s/.test(n)) return null;
  const rule = GENITIVE.find(([re]) => re.test(n));
  return rule ? rule[1](n) : null;
}

export function OfferSent({
  variant,
  recruiterFirstName,
  jobTitle,
  steps = [],
  others,
  base,
  total = null,
  result,
}: SentContext & { result: SentResult }) {
  const name = recruiterFirstName.trim();
  const homeHref = careerHref(base, { to: "home" });
  const allLabel = `Wszystkie oferty${total ? ` (${total})` : ""}`;
  const chapters = 1 + (others.length > 0 ? 1 : 0);
  return (
    <main aria-live="polite">
      <section className={`${s.ch} ${s.chRed} ${g.sentA}`} aria-label="Zgłoszenie wysłane">
        <ChapterMark index={0} count={chapters} name="Wysłane" />
        <div className={`${s.wrap} ${g.sentGrid}`}>
          <div className={g.sentText} role="status">
            <span className={g.badge}>
              <span aria-hidden="true">
                <CheckIcon size={14} />
              </span>
              Wysłane{jobTitle ? ` · ${jobTitle}` : ""}
            </span>
            <h1 className={g.sentTitle}>{atName(name) ? `CV jest u ${atName(name)}.` : "CV jest u nas."}</h1>
            <p className={g.sentLead}>
              {variant === "job"
                ? `${name || "Rekruter"} odezwie się po przejrzeniu CV. Nie musisz robić nic więcej.`
                : `${name ? `${name} odezwie się` : "Odezwiemy się"}, gdy pojawi się projekt w Twojej technologii. Nie musisz robić nic więcej.`}
            </p>
            {steps.length > 0 ? (
              <ol className={g.progress} aria-label="Co dalej">
                <li>
                  <strong>CV wysłane</strong>
                  <span>dziś</span>
                </li>
                {steps.map((st, i) => (
                  <li key={st.title} className={i === 0 ? g.now : undefined}>
                    {i === 0 ? <strong>{capitalize(st.title)}</strong> : <span className={g.stepName}>{capitalize(st.title)}</span>}
                    <span>{i === 0 ? "następny krok" : st.note}</span>
                  </li>
                ))}
              </ol>
            ) : null}
            <div className={g.btnRow}>
              <a className={`${s.btn} ${s.btnWhite}`} href={homeHref}>
                {allLabel} →
              </a>
            </div>
          </div>
          <aside className={g.receipt} aria-label="Twoje zgłoszenie">
            <h2>Twoje zgłoszenie</h2>
            <dl>
              {jobTitle ? (
                <div>
                  <dt>Oferta</dt>
                  <dd>{jobTitle}</dd>
                </div>
              ) : null}
              {name ? (
                <div>
                  <dt>{variant === "job" ? "Prowadzi" : "Trafia do"}</dt>
                  <dd>{name}</dd>
                </div>
              ) : null}
              {result.fileName ? (
                <div>
                  <dt>CV</dt>
                  <dd>{result.fileName}</dd>
                </div>
              ) : null}
              {result.email ? (
                <div>
                  <dt>Odpowiedź</dt>
                  <dd>{result.email}</dd>
                </div>
              ) : null}
            </dl>
          </aside>
        </div>
      </section>

      {others.length > 0 ? (
        <section className={`${s.ch} ${s.chSnow} ${g.alike}`} aria-labelledby="inne-oferty">
          <ChapterMark index={chapters - 1} count={chapters} name="Podobne" />
          <div className={s.wrap}>
            <div className={g.alikeTop}>
              <h2 id="inne-oferty">W międzyczasie: podobne projekty</h2>
              <a href={homeHref}>{allLabel} →</a>
            </div>
            <div className={s.grid}>
              {others.map((j) => (
                <OfferCard key={j.slug} job={j} href={careerHref(base, { to: "job", slug: j.slug })} />
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}
