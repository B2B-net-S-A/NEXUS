"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { CareerBoardJob } from "@/lib/career/api";
import { careerHref, type CareerBase } from "@/lib/career/host";
import type { ProcessStep } from "../requirementItems";

import { OfferCard } from "./OfferCard";
import { CheckIcon, ChapterMark, siteStyles as s } from "./SiteFrame";
import { StepsList } from "./Steps";

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

export function OfferSent({
  variant,
  recruiterFirstName,
  jobTitle,
  steps = [],
  others,
  base,
  result,
}: SentContext & { result: SentResult }) {
  const name = recruiterFirstName.trim();
  const homeHref = careerHref(base, { to: "home" });
  const chapters = 1 + (steps.length > 0 ? 1 : 0) + (others.length > 0 ? 1 : 0);
  return (
    <main aria-live="polite">
      <section className={`${s.ch} ${s.chRed} ${s.sent1}`}>
        <ChapterMark index={0} count={chapters} name="Wysłane" />
        <div className={s.wrap}>
          <h1>
            <span className={`${s.display} ${s.sentWord}`}>Wysłane</span>
          </h1>
          <div className={s.sentRow}>
            <div>
              <p className={s.lead}>
                {variant === "job"
                  ? `${name || "Rekruter"} odezwie się po przejrzeniu CV.`
                  : `${name ? `${name} odezwie się` : "Odezwiemy się"}, gdy pojawi się projekt w Twojej technologii.`}
              </p>
              <p className={s.body}>Twoje zgłoszenie jest u nas. Nie musisz robić nic więcej.</p>
              <a className={`${s.btn} ${s.btnWhite}`} href={homeHref}>
                Wszystkie rekrutacje →
              </a>
            </div>
            <aside className={s.rc} aria-label="Twoje zgłoszenie">
              <span className={s.tick}>
                <CheckIcon size={24} />
              </span>
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
        </div>
      </section>

      {steps.length > 0 ? (
        <section className={`${s.ch} ${s.chInk} ${s.s3}`} aria-label="Co dalej">
          <ChapterMark index={1} count={chapters} name="Co dalej" />
          <div className={s.wrap}>
            <div className={s.s3Top}>
              <span aria-hidden="true" className={`${s.display} ${s.s3Big}`}>
                {steps.length}
              </span>
              <h2 className={s.lead}>
                <span className={s.srOnly}>{steps.length}</span>{" "}
                kroki.
                <br />
                Co dalej
              </h2>
            </div>
            <StepsList steps={steps} recruiterFirstName={name} />
          </div>
        </section>
      ) : null}

      {others.length > 0 ? (
        <section className={`${s.ch} ${s.chSnow} ${s.others}`} aria-labelledby="inne-oferty">
          <ChapterMark index={chapters - 1} count={chapters} name="Inne oferty" />
          <div className={s.wrap}>
            <div className={s.othersTop}>
              <h2 id="inne-oferty" className={s.h2}>
                Inne oferty
              </h2>
              <a className={s.ulink} href={homeHref}>
                Wszystkie rekrutacje →
              </a>
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
