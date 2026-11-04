/**
 * Szablon `terminal` (A — role deweloperskie, decyzja Artura 28.10.2026).
 * Klimat terminala (pasek okna, `$`, kursor) w grafitowej szacie B2B Network:
 * duży tytuł, fakty i „Aplikuj” na pierwszym ekranie, wymagania raz — w karcie
 * „Co już masz?”. Makieta „Terminal — poprawiony”:
 * https://claude.ai/artifact/RGquQpMFyKgRYHPognJ2kU
 */
import "./brandFonts.css";

import { genitiveName } from "@/lib/career/format";
import { careerHref, careerVisibleUrl } from "@/lib/career/host";

import { B2BLogo } from "../B2BLogo";
import { CareerApplyForm } from "../CareerApplyForm";
import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { mockJob, type MockAboutBlock } from "./jobModel";
import { TerminalFitCard } from "./TerminalJobParts";
import styles from "./terminalJob.module.css";
import type { CareerJobLayoutProps } from "./types";

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/**
 * Tytuł z kursorem przyklejonym do ostatniego słowa (kursor nie ląduje sam
 * w linii). Reszta łamie się naturalnie — twarda spacja przed „ - ” dawała
 * trzy linie zamiast dwóch.
 */
function TitleWithCursor({ title }: { title: string }) {
  const words = title.split(/ +/);
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

function Dots() {
  return (
    <span className={styles.dots} aria-hidden="true">
      <span />
      <span />
      <span className={styles.dotOn} />
    </span>
  );
}

export function TerminalJob({ data, base, host, formPreview }: CareerJobLayoutProps) {
  const job = mockJob(data);
  const { recruiter } = data;
  const hasFit = job.must.length + job.nice.length > 0;
  const homeHref = careerHref(base, { to: "home" });
  const rodoHref = careerHref(base, { to: "rodo" });
  const handle = job.recruiterFirstName.toLocaleLowerCase("pl-PL");
  const pathSlug = job.slug.replace(/-[a-z0-9]{4}$/, "");
  const contract = job.facts.find((f) => f.key === "contract")?.value;
  // „umowa b2b” z `processSteps` → „Umowa B2B” (nazwa umowy jak w faktach).
  const stepNote = (note: string) =>
    cap(contract ? note.replace(contract.toLocaleLowerCase("pl-PL"), contract) : note);
  let section = 0;
  const nextNum = () => String(++section).padStart(2, "0");

  return (
    <div className={styles.root}>
      <header className={styles.chrome}>
        <Dots />
        <a href={homeHref} className={styles.logoLink} aria-label="B2B Network — kariera">
          <B2BLogo variant="onDark" height={26} />
        </a>
        <span className={styles.path}>~/kariera/{pathSlug}</span>
        <a href={homeHref} className={styles.allLink}>
          Wszystkie rekrutacje <span aria-hidden="true">→</span>
        </a>
      </header>

      <main>
        <section className={`${styles.hero} ${hasFit ? "" : styles.heroSolo}`}>
          <div className={styles.heroMain}>
            <p className={styles.prompt}>
              <span className={styles.dollar}>$</span> rekrutacja --otwarta
              {handle ? <span className={styles.comment}> # prowadzi {handle}@b2bnetwork</span> : null}
            </p>
            <TitleWithCursor title={job.title} />
            {job.subtitle ? <p className={styles.subtitle}>{cap(job.subtitle)}</p> : null}
            {job.facts.length ? (
              <dl className={styles.facts}>
                {job.facts.map((f) => (
                  <div key={f.key} className={styles.fact}>
                    <dt className={styles.factLabel}>{f.label}</dt>
                    <dd className={styles.factValue}>{f.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <div className={styles.ctas}>
              <a href="#aplikuj" className={styles.btnPrimary}>
                Aplikuj — 2 minuty
              </a>
              {/* Na telefonie karta stoi pod opisem — skrót do niej jako zwykły link. */}
              {hasFit ? (
                <a href="#wymagania" className={styles.reqLink}>
                  Zobacz wymagania <span aria-hidden="true">↓</span>
                </a>
              ) : null}
            </div>
          </div>
          {hasFit ? (
            <div className={styles.heroSide}>
              <TerminalFitCard must={job.must} nice={job.nice} applyHref="#aplikuj" />
            </div>
          ) : null}
        </section>

        <div className={styles.body}>
          <div className={styles.content}>
            {job.about.length ? (
              <section className={styles.section} aria-label="O projekcie">
                <h2 className={styles.h2}>
                  <span className={styles.h2Num}>{nextNum()}</span> O projekcie
                </h2>
                {job.about.map((block, i) => (
                  <AboutBlock key={i} block={block} />
                ))}
              </section>
            ) : null}

            {job.steps.length ? (
              <section className={styles.section} aria-label="Proces rekrutacji">
                <h2 className={styles.h2}>
                  <span className={styles.h2Num}>{nextNum()}</span> Jak wygląda proces
                </h2>
                <ol className={styles.steps}>
                  {job.steps.map((s, i) => (
                    <li key={i} className={styles.step}>
                      <span className={styles.stepNum}>{String(i + 1).padStart(2, "0")}</span>
                      <span className={styles.stepTitle}>{cap(s.title)}</span>
                      <span className={styles.stepNote}>{stepNote(s.note)}</span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </div>

          <section id="aplikuj" tabIndex={-1} className={styles.formWrap} aria-label="Aplikuj">
            <div className={styles.window}>
              <div className={styles.windowBar}>
                <Dots />
                <span className={styles.windowPath}>./aplikuj.sh</span>
              </div>
              <div className={styles.form}>
                <h2 className={styles.formTitle}>
                  Aplikuj — 2 minuty
                </h2>
                <p className={styles.formLead}>
                  {cap(job.recruiterFirstName)} odezwie się do Ciebie po przejrzeniu CV.
                </p>
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
              </div>
            </div>
          </section>
        </div>
      </main>

      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <B2BLogo variant="onDark" height={22} />
          <span className={styles.footerName}>B2B.NET S.A.</span>
          <a href={rodoHref} className={styles.footerLink}>
            Klauzula informacyjna RODO
          </a>
          <span className={styles.footerHost}>
            {careerVisibleUrl(host, base, { to: "job", slug: job.slug })}
          </span>
        </div>
        <p className={styles.legal}>{COMPANY_LEGAL_LINE}</p>
      </footer>
    </div>
  );
}
