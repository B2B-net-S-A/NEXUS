/**
 * MAKIETA — wariant `terminal-plus` („Terminal — poprawiony”, 28.10.2026).
 * Klimat terminala zostaje (okno z paskiem, `$`, kursor), ale w grafitowej
 * szacie B2B: duży tytuł, trzy fakty i „Aplikuj” na pierwszym ekranie,
 * wymagania raz — w karcie „Co już masz?”.
 */
import { CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { B2BLogo } from "./B2BLogo";
import type { MockupProps } from "./index";
import { mockJob, type MockAboutBlock, type MockFact } from "./model";
import styles from "./terminalPlus.module.css";
import { TerminalPlusFitCard } from "./TerminalPlusParts";

const FACT_LABEL: Record<MockFact["key"], string> = {
  city: "lokalizacja",
  mode: "tryb pracy",
  contract: "umowa",
  seniority: "poziom",
  start: "start",
};

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/** Tytuł z kursorem przyklejonym do ostatniego słowa (kursor nie ląduje sam w linii). */
function TitleWithCursor({ title }: { title: string }) {
  // Myślnik nie zaczyna linii: „Package - KYC” łamie się za myślnikiem.
  const words = title.replace(/ ([-–—]) /g, "\u00a0$1 ").split(/ +/);
  const last = words.pop() ?? "";
  return (
    <h1 className={styles.title}>
      {words.length ? `${words.join(" ")} ` : null}
      <span className={styles.nowrap}>
        {last}
        <span className={styles.cursor} aria-hidden="true" />
      </span>
    </h1>
  );
}

function AboutBlock({ block }: { block: MockAboutBlock }) {
  return (
    <div className={styles.aboutBlock}>
      {block.heading ? <h3 className={styles.h3}>{block.heading}</h3> : null}
      {block.text ? <p className={styles.para}>{block.text}</p> : null}
      {block.bullets.length ? (
        <ul className={styles.bullets}>
          {block.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Field({
  id,
  label,
  type = "text",
  required = false,
  autoComplete,
}: {
  id: string;
  label: string;
  type?: string;
  required?: boolean;
  autoComplete?: string;
}) {
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {required ? <span className={styles.req}> *</span> : <span className={styles.opt}> (opcjonalnie)</span>}
      </label>
      <input id={id} type={type} className={styles.input} autoComplete={autoComplete} />
    </div>
  );
}

export function TerminalPlus({ data, base }: MockupProps) {
  const job = mockJob(data);
  const hasFit = job.must.length + job.nice.length > 0;
  const recruiter = job.recruiterFirstName.toLocaleLowerCase("pl-PL");
  const pathSlug = job.slug.replace(/-[a-z0-9]{4}$/, "");
  const contract = job.facts.find((f) => f.key === "contract")?.value;
  // „umowa b2b” z `processSteps` → „Umowa B2B” (nazwa umowy jak w faktach).
  const stepNote = (note: string) =>
    cap(contract ? note.replace(contract.toLocaleLowerCase("pl-PL"), contract) : note);

  return (
    <div className={styles.root}>
      <header className={styles.chrome}>
        <span className={styles.dots} aria-hidden="true">
          <span />
          <span />
          <span className={styles.dotOn} />
        </span>
        <a href={careerHref(base, { to: "home" })} className={styles.logoLink} aria-label="B2B Network — kariera">
          <B2BLogo variant="onDark" height={26} />
        </a>
        <span className={styles.path}>~/kariera/{pathSlug}</span>
        <a href={careerHref(base, { to: "home" })} className={styles.allLink}>
          wszystkie rekrutacje <span aria-hidden="true">→</span>
        </a>
      </header>

      <main>
        <section className={`${styles.hero} ${hasFit ? "" : styles.heroSolo}`}>
          <div className={styles.heroMain}>
            <p className={styles.prompt}>
              <span className={styles.dollar}>$</span> rekrutacja --otwarta
              <span className={styles.comment}> # prowadzi {recruiter}@b2bnetwork</span>
            </p>
            <TitleWithCursor title={job.title} />
            {job.subtitle ? <p className={styles.subtitle}>{cap(job.subtitle)}</p> : null}
            {job.facts.length ? (
              <dl className={styles.facts}>
                {job.facts.map((f) => (
                  <div key={f.key} className={styles.fact}>
                    <dt className={styles.factLabel}>{FACT_LABEL[f.key]}</dt>
                    <dd className={styles.factValue}>{f.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <div className={styles.ctas}>
              <a href="#aplikuj" className={styles.btnPrimary}>
                Aplikuj — 2 minuty
              </a>
              {hasFit ? (
                <a href="#wymagania" className={styles.btnGhost}>
                  Zobacz wymagania
                </a>
              ) : null}
            </div>
          </div>
          {hasFit ? (
            <div className={styles.heroSide}>
              <TerminalPlusFitCard must={job.must} nice={job.nice} applyHref="#aplikuj" />
            </div>
          ) : null}
        </section>

        <div className={styles.body}>
          <div className={styles.content}>
            {job.about.length ? (
              <section className={styles.section} aria-labelledby="tp-about">
                <h2 id="tp-about" className={styles.h2}>
                  <span className={styles.h2Num}>01</span> O projekcie
                </h2>
                {job.about.map((block, i) => (
                  <AboutBlock key={i} block={block} />
                ))}
              </section>
            ) : null}

            {job.steps.length ? (
              <section className={styles.section} aria-labelledby="tp-process">
                <h2 id="tp-process" className={styles.h2}>
                  <span className={styles.h2Num}>02</span> Jak wygląda proces
                </h2>
                <ol className={styles.steps}>
                  {job.steps.map((s, i) => (
                    <li key={i} className={styles.step}>
                      <span className={styles.stepNum}>0{i + 1}</span>
                      <span className={styles.stepTitle}>{cap(s.title)}</span>
                      <span className={styles.stepNote}>{stepNote(s.note)}</span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </div>

          <aside id="aplikuj" className={styles.formWrap} aria-labelledby="tp-apply">
            <div className={styles.window}>
              <div className={styles.windowBar}>
                <span className={styles.dots} aria-hidden="true">
                  <span />
                  <span />
                  <span className={styles.dotOn} />
                </span>
                <span className={styles.windowPath}>./aplikuj.sh</span>
              </div>
              <form className={styles.form}>
                <h2 id="tp-apply" className={styles.formTitle}>
                  Aplikuj — 2 minuty
                </h2>
                <p className={styles.formLead}>
                  {cap(job.recruiterFirstName)} odezwie się do Ciebie po przejrzeniu CV.
                </p>
                <div className={styles.row2}>
                  <Field id="tp-first" label="Imię" required autoComplete="given-name" />
                  <Field id="tp-last" label="Nazwisko" required autoComplete="family-name" />
                </div>
                <Field id="tp-email" label="E-mail" type="email" required autoComplete="email" />
                <div className={styles.field}>
                  <span className={styles.label}>
                    CV<span className={styles.req}> *</span>
                  </span>
                  <label htmlFor="tp-cv" className={styles.drop}>
                    <span className={styles.dropMain}>
                      <span className={styles.dollar}>↑</span> Dodaj CV albo upuść plik tutaj
                    </span>
                    <span className={styles.dropHint}>PDF, DOC, DOCX do 10 MB</span>
                    <input id="tp-cv" type="file" accept=".pdf,.doc,.docx" className={styles.srOnly} />
                  </label>
                </div>
                <div className={styles.row2}>
                  <Field id="tp-phone" label="Telefon" type="tel" autoComplete="tel" />
                  <Field id="tp-linkedin" label="LinkedIn" type="url" />
                </div>
                <label className={styles.consent}>
                  <input type="checkbox" className={styles.check} />
                  <span>
                    {CONSENT_CURRENT_TEXT}
                    <span className={styles.req}> *</span>
                  </span>
                </label>
                <label className={styles.consent}>
                  <input type="checkbox" className={styles.check} />
                  <span>
                    {CONSENT_FUTURE_TEXT} <span className={styles.opt}>(opcjonalnie)</span>
                  </span>
                </label>
                <button type="button" className={styles.btnSubmit}>
                  Wyślij zgłoszenie
                </button>
              </form>
            </div>
          </aside>
        </div>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <B2BLogo variant="onDark" height={22} />
          <span className={styles.footerName}>B2B.NET S.A.</span>
          <a href={careerHref(base, { to: "rodo" })} className={styles.footerLink}>
            Klauzula informacyjna RODO
          </a>
        </div>
        <p className={styles.legal}>{COMPANY_LEGAL_LINE}</p>
      </footer>
    </div>
  );
}
