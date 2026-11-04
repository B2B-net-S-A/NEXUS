/**
 * Szablon `grafit` („Grafit B2B”, domyślny dla większości rekrutacji;
 * decyzja Artura 28.10.2026, makieta C w
 * https://claude.ai/artifact/RGquQpMFyKgRYHPognJ2kU). Ciemny grafit marki,
 * duży tytuł z łukiem znaku B2B w tle, trzy fakty i „Aplikuj” na pierwszym
 * ekranie; niżej kafle treści, a przy formularzu „Jak przebiega rekrutacja”.
 *
 * Uwagi z przeglądu makiety: „Wymagane” bez wypełnionych ptaszków (wyglądały
 * jak już zaznaczone pola), kroki procesu obok formularza i kolumny kafli
 * wyrównane do jednej linii, bo na laptopie zostawało puste miejsce.
 */
import { genitiveName } from "@/lib/career/format";
import { careerHref, careerVisibleUrl } from "@/lib/career/host";

import { B2BLogo } from "../B2BLogo";
import { CareerApplyForm } from "../CareerApplyForm";
import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { GrafitApplyBar } from "./GrafitJobParts";
import { mockJob, type MockAboutBlock, type MockFact } from "./jobModel";
import type { CareerJobLayoutProps } from "./types";
import "./brandFonts.css";
import styles from "./grafitJob.module.css";

const HERO_KEYS: MockFact["key"][] = ["city", "mode", "contract"];
const APPLY_ID = "aplikuj";
const HERO_CTA_ID = "grafit-hero-cta";
/** Dłuższa lista wymagań (np. 20 technologii) idzie w dwie kolumny, żeby nie zajęła trzech ekranów. */
const MUST_COMPACT_FROM = 8;

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/**
 * Ostatnie słowo tytułu dostaje czerwień marki — tylko gdy to słowo z liter.
 * Numer albo kod na końcu („TP#41745”) zostaje biały: inaczej to on byłby
 * najmocniejszym napisem na stronie.
 */
function splitTitle(title: string): [string, string] {
  const i = title.lastIndexOf(" ");
  const last = i > 0 ? title.slice(i + 1) : title;
  if (!/^[\p{L}-]+$/u.test(last)) return [title, ""];
  return i > 0 ? [title.slice(0, i + 1), last] : ["", title];
}

/** „umowa b2b” z modelu procesu → „Umowa B2B” (nazwa umowy w oryginalnej pisowni). */
function stepNote(note: string, contract: string | null): string {
  if (contract && note.toLocaleLowerCase("pl-PL") === `umowa ${contract.toLocaleLowerCase("pl-PL")}`) {
    return `Umowa ${contract}`;
  }
  return cap(note);
}

/** „Hybryda · 3 dni w biurze w tygodniu” → duża wartość + dopisek. */
function splitValue(value: string): [string, string | null] {
  const [main, ...rest] = value.split(" · ");
  return [main, rest.length ? rest.join(" · ") : null];
}

function AboutBody({ blocks }: { blocks: MockAboutBlock[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.bullets.length ? (
          <ul key={i} className={styles.bullets}>
            {b.bullets.map((item, j) => (
              <li key={`${item}-${j}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={i} className={styles.para}>
            {b.text}
          </p>
        ),
      )}
    </>
  );
}

/** Łuki znaku B2B (dwie „brzuszki” litery B) — dekoracja za tytułem. */
function BrandArc() {
  return (
    <svg className={styles.arc} viewBox="0 0 520 600" aria-hidden="true" focusable="false">
      <path
        className={styles.arcPath}
        d="M30 40 H300 A125 125 0 0 1 300 290 H170 M170 290 H330 A140 140 0 0 1 330 570 H30"
        pathLength={1}
      />
    </svg>
  );
}

export function GrafitJob({ data, base, host, formPreview }: CareerJobLayoutProps) {
  const { recruiter } = data;
  const job = mockJob(data);
  // „Package - KYC” → myślnik zostaje przy poprzednim słowie, nie otwiera wiersza.
  const [titleHead, titleTail] = splitTitle(job.title.replace(/ - /g, " – "));
  const heroFacts = job.facts.filter((f) => HERO_KEYS.includes(f.key));
  const extraFacts = job.facts.filter((f) => !HERO_KEYS.includes(f.key));
  const contract = job.facts.find((f) => f.key === "contract")?.value ?? null;
  const intro = job.about.filter((b) => !b.heading);
  const sections = job.about.filter((b) => b.heading);
  const hasMain = intro.length > 0 || sections.length > 0;
  const hasSide = job.must.length > 0 || job.nice.length > 0;
  const rodoHref = careerHref(base, { to: "rodo" });
  const homeHref = careerHref(base, { to: "home" });
  const hostLabel = careerVisibleUrl(host, base, { to: "job", slug: job.slug });

  return (
    <div className={styles.root}>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <a href={homeHref} className={styles.logoLink} aria-label="B2B Network — wszystkie rekrutacje">
            <B2BLogo variant="onDark" height={30} />
          </a>
          <nav className={styles.barNav} aria-label="Nawigacja">
            <a href={homeHref} className={styles.barLink}>
              Wszystkie rekrutacje
            </a>
            <a href={`#${APPLY_ID}`} className={styles.barCta}>
              Aplikuj
            </a>
          </nav>
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.hero}>
          <div className={styles.glow} aria-hidden="true" />
          <BrandArc />
          <div className={styles.heroInner}>
            <p className={styles.kicker}>Rekrutacja IT w B2B Network</p>
            <h1 className={styles.title}>
              {titleHead}
              <span className={styles.titleTail}>{titleTail}</span>
            </h1>
            {job.subtitle && <p className={styles.subtitle}>{cap(job.subtitle)}</p>}

            <div className={`${styles.heroBottom} ${job.facts.length ? "" : styles.heroBottomSolo}`}>
              {job.facts.length > 0 && (
                // Jedna lista faktów: trzy główne jako kafle, „Poziom” i „Start”
                // pod nimi w jednym wierszu. Tekst `dd` = wartość z `mockJob`
                // (separator „ · ” zostaje w treści, kafel chowa go wizualnie).
                <dl
                  className={styles.facts}
                  style={{ "--fact-cols": Math.max(heroFacts.length, 1) } as React.CSSProperties}
                >
                  {heroFacts.map((f) => {
                    const [main, note] = splitValue(f.value);
                    return (
                      <div key={f.key} className={styles.fact}>
                        <dt className={styles.factLabel}>{f.label}</dt>
                        <dd className={styles.factValue}>
                          {main}
                          {note && (
                            <span className={styles.factNote}>
                              <span className={styles.factSep}> · </span>
                              {note}
                            </span>
                          )}
                        </dd>
                      </div>
                    );
                  })}
                  {extraFacts.map((f) => (
                    <div key={f.key} className={styles.factExtra}>
                      <dt className={styles.extraLabel}>{f.label}</dt>
                      <dd className={styles.extraValue}>{f.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <div className={styles.ctaBox} id={HERO_CTA_ID}>
                <a href={`#${APPLY_ID}`} className={styles.cta}>
                  Aplikuj — 2 minuty
                </a>
                <p className={styles.ctaNote}>Rekrutację prowadzi {job.recruiterFirstName}</p>
              </div>
            </div>
          </div>
        </div>

        {(hasMain || hasSide) && (
          <div className={`${styles.bento} ${hasMain && hasSide ? "" : styles.bentoSingle}`}>
            {hasMain && (
              <section className={styles.col} aria-label="O projekcie">
                {intro.length > 0 && (
                  <article className={styles.tile}>
                    <h2 className={styles.tileTitle}>O projekcie</h2>
                    <AboutBody blocks={intro} />
                  </article>
                )}
                {sections.map((b, i) => (
                  <article key={i} className={styles.tile}>
                    <h2 className={styles.tileTitle}>{b.heading}</h2>
                    <AboutBody blocks={[b]} />
                  </article>
                ))}
              </section>
            )}

            {hasSide && (
              <section className={styles.col} aria-label="Wymagania">
                {job.must.length > 0 && (
                  <article className={`${styles.tile} ${styles.tileMust}`}>
                    <h2 className={styles.tileTitle}>Wymagane</h2>
                    <ul className={`${styles.must} ${job.must.length > MUST_COMPACT_FROM ? styles.mustCompact : ""}`}>
                      {job.must.map((m, i) => (
                        <li key={`${m.name}-${i}`}>
                          <span className={styles.mustName}>{m.name}</span>
                          {m.note && <span className={styles.mustNote}>{m.note}</span>}
                        </li>
                      ))}
                    </ul>
                  </article>
                )}
                {job.nice.length > 0 && (
                  <article className={`${styles.tile} ${styles.tileNice}`}>
                    <h2 className={styles.tileTitle}>Mile widziane</h2>
                    <p className={styles.tileLead}>Atut, nie warunek — aplikuj bez tego.</p>
                    <ul className={styles.plus}>
                      {job.nice.map((n, i) => (
                        <li key={`${n}-${i}`}>
                          <span className={styles.plusMark} aria-hidden="true">
                            +
                          </span>
                          <span>{n}</span>
                        </li>
                      ))}
                    </ul>
                  </article>
                )}
              </section>
            )}
          </div>
        )}

        <div className={styles.applyWrap}>
          <div className={styles.apply}>
            <div className={styles.applyIntro}>
              <h2 className={styles.applyTitle}>
                Aplikuj — 2 minuty
              </h2>
              <p className={styles.para}>
                Podaj imię, nazwisko i e-mail, dołącz CV. Nie musisz spełniać wszystkich wymagań — jeśli
                projekt Cię ciekawi, wyślij zgłoszenie.
              </p>
              <p className={styles.applyWho}>Zgłoszenie czyta {job.recruiterFirstName} z B2B Network.</p>

              {job.steps.length > 0 && (
                <section className={styles.process} aria-label="Proces rekrutacji">
                  <h3 className={styles.processTitle}>Jak przebiega rekrutacja</h3>
                  <ol className={styles.steps}>
                    {job.steps.map((s, i) => (
                      <li key={s.title} className={styles.step}>
                        <span className={styles.stepNo} aria-hidden="true">
                          {i + 1}
                        </span>
                        <span>
                          <span className={styles.stepTitle}>{cap(s.title)}</span>
                          <span className={styles.stepNote}>{stepNote(s.note, contract)}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                </section>
              )}
            </div>

            <section id={APPLY_ID} tabIndex={-1} aria-label="Aplikuj" className={styles.form}>
              <CareerApplyForm
                linkSlug={job.slug}
                variant="job"
                rodoHref={rodoHref}
                preview={formPreview}
                tone="plain"
                secondaryLink={
                  recruiter.slug
                    ? {
                        href: careerHref(base, { to: "recruiter", slug: recruiter.slug }),
                        label: "Nie ten projekt?",
                        note: `Zostaw CV u ${genitiveName(recruiter.first_name)}`,
                      }
                    : null
                }
              />
            </section>
          </div>
        </div>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <B2BLogo variant="onDark" height={24} />
          <span className={styles.footerBrand}>B2B.NET S.A.</span>
          <a href={rodoHref} className={styles.footerLink}>
            Klauzula informacyjna RODO
          </a>
          <a href={homeHref} className={styles.footerLink}>
            {hostLabel}
          </a>
        </div>
        <p className={styles.legal}>{COMPANY_LEGAL_LINE}</p>
      </footer>

      <GrafitApplyBar targetId={APPLY_ID} heroId={HERO_CTA_ID} />
    </div>
  );
}
