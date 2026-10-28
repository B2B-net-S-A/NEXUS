/**
 * MAKIETA — wariant `b2b-ciemny` („B2B Network — grafit”, 28.10.2026).
 * Ciemny grafit marki, duży tytuł z łukiem znaku B2B w tle, trzy kafle faktów
 * i czerwone „Aplikuj” na pierwszym ekranie; niżej kafle treści (bento).
 * Formularz statyczny — nic nie wysyła.
 */
import { CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { B2BLogo } from "./B2BLogo";
import type { MockupProps } from "./index";
import { mockJob, type MockAboutBlock, type MockFact } from "./model";
import styles from "./b2bCiemny.module.css";

const HERO_KEYS: MockFact["key"][] = ["city", "mode", "contract"];

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/** Ostatnie słowo tytułu dostaje czerwień marki. */
function splitTitle(title: string): [string, string] {
  const i = title.lastIndexOf(" ");
  return i > 0 ? [title.slice(0, i + 1), title.slice(i + 1)] : ["", title];
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
  return [main, rest.length ? rest.join(", ") : null];
}

function AboutBody({ blocks }: { blocks: MockAboutBlock[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.bullets.length ? (
          <ul key={i} className={styles.bullets}>
            {b.bullets.map((item) => (
              <li key={item}>{item}</li>
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

export function B2BCiemny({ data, base, host }: MockupProps) {
  const job = mockJob(data);
  // „Package - KYC” → myślnik zostaje przy poprzednim słowie, nie otwiera wiersza.
  const [titleHead, titleTail] = splitTitle(job.title.replace(/ - /g, "\u00A0– "));
  const heroFacts = job.facts.filter((f) => HERO_KEYS.includes(f.key));
  const contract = job.facts.find((f) => f.key === "contract")?.value ?? null;
  const extraFacts = job.facts.filter((f) => !HERO_KEYS.includes(f.key));
  const intro = job.about.filter((b) => !b.heading);
  const sections = job.about.filter((b) => b.heading);
  const hasMain = intro.length > 0 || sections.length > 0;
  const hasSide = job.must.length > 0 || job.nice.length > 0 || job.steps.length > 0;
  const rodoHref = careerHref(base, { to: "rodo" });
  const homeHref = careerHref(base, { to: "home" });
  const hostLabel = host.replace(/^https?:\/\//, "");

  return (
    <div className={styles.root}>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <a href={homeHref} className={styles.logoLink} aria-label="B2B Network — wszystkie rekrutacje">
            <B2BLogo variant="onDark" height={30} />
          </a>
          <nav className={styles.barNav}>
            <a href={homeHref} className={styles.barLink}>
              Wszystkie rekrutacje
            </a>
            <a href="#aplikuj" className={styles.barCta}>
              Aplikuj
            </a>
          </nav>
        </div>
      </header>

      <main>
        <section className={styles.hero}>
          <div className={styles.glow} aria-hidden="true" />
          <BrandArc />
          <div className={styles.heroInner}>
            <p className={styles.kicker}>Rekrutacja IT w B2B Network</p>
            <h1 className={styles.title}>
              {titleHead}
              <span className={styles.titleTail}>{titleTail}</span>
            </h1>
            {job.subtitle && <p className={styles.subtitle}>{cap(job.subtitle)}</p>}
            {extraFacts.length > 0 && (
              <ul className={styles.extra}>
                {extraFacts.map((f) => (
                  <li key={f.key}>
                    <span className={styles.extraLabel}>{f.label}:</span> {f.value}
                  </li>
                ))}
              </ul>
            )}

            <div className={styles.heroBottom}>
              {heroFacts.length > 0 && (
                <dl className={styles.facts}>
                  {heroFacts.map((f) => {
                    const [main, note] = splitValue(f.value);
                    return (
                      <div key={f.key} className={styles.fact}>
                        <dt className={styles.factLabel}>{f.label}</dt>
                        <dd className={styles.factValue}>
                          {main}
                          {note && <span className={styles.factNote}>{note}</span>}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              )}
              <div className={styles.ctaBox}>
                <a href="#aplikuj" className={styles.cta}>
                  Aplikuj — 2 minuty
                </a>
                <p className={styles.ctaNote}>Rekrutację prowadzi {job.recruiterFirstName}</p>
              </div>
            </div>
          </div>
        </section>

        <section className={`${styles.bento} ${hasMain && hasSide ? "" : styles.bentoSingle}`}>
          {hasMain && (
            <div className={styles.col}>
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
            </div>
          )}

          {hasSide && (
            <div className={styles.col}>
              {job.must.length > 0 && (
                <article className={`${styles.tile} ${styles.tileMust}`}>
                  <h2 className={styles.tileTitle}>Wymagane</h2>
                  <ul className={styles.checks}>
                    {job.must.map((m) => (
                      <li key={m.name}>
                        <span className={styles.checkMark} aria-hidden="true">
                          <svg viewBox="0 0 16 16">
                            <path d="M3.5 8.5l3 3 6-7" />
                          </svg>
                        </span>
                        <span>
                          {m.name}
                          {m.note && <span className={styles.checkNote}>{m.note}</span>}
                        </span>
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
                    {job.nice.map((n) => (
                      <li key={n}>
                        <span className={styles.plusMark} aria-hidden="true">
                          +
                        </span>
                        <span>{n}</span>
                      </li>
                    ))}
                  </ul>
                </article>
              )}
              {job.steps.length > 0 && (
                <article className={styles.tile}>
                  <h2 className={styles.tileTitle}>Jak przebiega rekrutacja</h2>
                  <ol className={styles.steps}>
                    {job.steps.map((s, i) => (
                      <li key={s.title} className={styles.step}>
                        <span className={styles.stepNo}>{i + 1}</span>
                        <span>
                          <span className={styles.stepTitle}>{cap(s.title)}</span>
                          <span className={styles.stepNote}>{stepNote(s.note, contract)}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                </article>
              )}
            </div>
          )}
        </section>

        <section id="aplikuj" className={styles.applyWrap}>
          <div className={styles.apply}>
            <div className={styles.applyIntro}>
              <h2 className={styles.applyTitle}>Aplikuj — 2 minuty</h2>
              <p className={styles.para}>
                Podaj imię, nazwisko i e-mail, dołącz CV. Nie musisz spełniać wszystkich wymagań — jeśli
                projekt Cię ciekawi, wyślij zgłoszenie.
              </p>
              <p className={styles.applyWho}>
                Zgłoszenie czyta {job.recruiterFirstName} z B2B Network.
              </p>
            </div>

            <form className={styles.form} noValidate>
              <div className={styles.field}>
                <label htmlFor="bc-first">Imię *</label>
                <input id="bc-first" name="first_name" autoComplete="given-name" required />
              </div>
              <div className={styles.field}>
                <label htmlFor="bc-last">Nazwisko *</label>
                <input id="bc-last" name="last_name" autoComplete="family-name" required />
              </div>
              <div className={styles.field}>
                <label htmlFor="bc-email">E-mail *</label>
                <input id="bc-email" name="email" type="email" autoComplete="email" required />
              </div>
              <div className={styles.field}>
                <label htmlFor="bc-phone">
                  Telefon <span className={styles.opt}>(opcjonalnie)</span>
                </label>
                <input id="bc-phone" name="phone" type="tel" autoComplete="tel" />
              </div>
              <div className={`${styles.field} ${styles.full}`}>
                <label htmlFor="bc-linkedin">
                  LinkedIn <span className={styles.opt}>(opcjonalnie)</span>
                </label>
                <input id="bc-linkedin" name="linkedin" type="url" placeholder="linkedin.com/in/…" />
              </div>
              <label className={`${styles.drop} ${styles.full}`}>
                <input type="file" name="cv" accept=".pdf,.doc,.docx" className={styles.fileInput} />
                <span className={styles.dropIcon} aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
                  </svg>
                </span>
                <span>
                  <span className={styles.dropTitle}>CV * — wybierz plik albo upuść go tutaj</span>
                  <span className={styles.dropHint}>PDF, DOC, DOCX do 10 MB</span>
                </span>
              </label>
              <label className={`${styles.consent} ${styles.full}`}>
                <input type="checkbox" name="consent" required />
                <span>
                  <strong>Zgoda wymagana. </strong>
                  {CONSENT_CURRENT_TEXT}
                </span>
              </label>
              <label className={`${styles.consent} ${styles.full}`}>
                <input type="checkbox" name="consent_future" />
                <span>
                  <strong>Zgoda dobrowolna. </strong>
                  {CONSENT_FUTURE_TEXT}
                </span>
              </label>
              <div className={styles.full}>
                <button type="button" className={styles.cta}>
                  Wyślij zgłoszenie
                </button>
              </div>
            </form>
          </div>
        </section>
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
    </div>
  );
}
