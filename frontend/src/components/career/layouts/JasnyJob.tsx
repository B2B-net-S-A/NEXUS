import "./brandFonts.css";

import { genitiveName } from "@/lib/career/format";
import { careerHref, careerVisibleUrl } from "@/lib/career/host";

import { B2BLogo } from "../B2BLogo";
import { CareerApplyForm } from "../CareerApplyForm";
import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { mockJob, type MockFact } from "./jobModel";
import { JasnyApplyDock } from "./JasnyJobParts";
import s from "./jasnyJob.module.css";
import type { CareerJobLayoutProps } from "./types";

const HERO_ID = "kr-hero";
const FORM_ID = "aplikuj";

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

function FactIcon({ kind }: { kind: MockFact["key"] }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (kind) {
    case "city":
      return (
        <svg {...common}>
          <path d="M12 21s-6.5-6.2-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.8 12 21 12 21Z" />
          <circle cx="12" cy="9.8" r="2.4" />
        </svg>
      );
    case "mode":
      return (
        <svg {...common}>
          <path d="M3.5 11 12 4l8.5 7" />
          <path d="M6 9.5V20h12V9.5" />
          <path d="M10 20v-5.5h4V20" />
        </svg>
      );
    case "contract":
      return (
        <svg {...common}>
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
          <path d="M14 3v5h5M9 13h6M9 17h4" />
        </svg>
      );
    case "seniority":
      return (
        <svg {...common}>
          <path d="M5 20v-5M12 20V10M19 20V4" />
        </svg>
      );
    case "start":
      return (
        <svg {...common}>
          <rect x="3.5" y="5" width="17" height="15" rx="2" />
          <path d="M3.5 10h17M8 3v4M16 3v4" />
        </svg>
      );
  }
}

/**
 * Ozdobnik hero: cała litera „B” ze znaku B2B Network, bardzo jasna. Widać ją
 * w całości (łuki po prawej), bo przycięta do samych poprzeczek czytała się
 * jak poziome pasy (przegląd makiety 28.10.2026).
 */
function MarkB() {
  return (
    <svg className={s.mark} viewBox="566 130 230 240" aria-hidden="true" focusable="false">
      <path d="M760.8,249.8c16.4-10.9,27.3-29.7,27.3-50.9,0-33.7-27.3-61-60.8-61h-143.2c-5.6,0-10.1,4.5-10.1,10.1s4.5,10.1,10.1,10.1h143.2c22.4,0,40.6,18.3,40.6,40.7s-18.2,40.7-40.6,40.7h-67.4c-5.6,0-10.1,4.5-10.1,10.1s4.5,10.1,10.1,10.1h67.4c22.4,0,40.6,18.3,40.6,40.7s-18.2,40.7-40.6,40.7h-102.8c-5.6,0-10.1,4.5-10.1,10.1s4.5,10.1,10.1,10.1h102.8c33.5,0,60.8-27.4,60.8-61s-10.9-40-27.3-50.9" />
      <path d="M584,310.8h133.1c5.6,0,10.1-4.5,10.1-10.1s-4.5-10.1-10.1-10.1h-123v-76.9h123c5.6,0,10.1-4.5,10.1-10.1s-4.5-10.1-10.1-10.1h-133.1c-5.6,0-10.1,4.5-10.1,10.1v97.2c0,5.6,4.5,10.1,10.1,10.1" />
    </svg>
  );
}

function Check() {
  return (
    <svg className={s.check} viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <circle cx="10" cy="10" r="10" />
      <path d="m5.8 10.3 2.7 2.7 5.7-6" />
    </svg>
  );
}

/**
 * Szablon `jasny` (B, role biznesowe — decyzja Artura 28.10.2026): jasna
 * strona w barwach marki, białe karty na Snow, czerwień na akcentach. Kroki
 * procesu stoją raz — w sekcji „Jak wygląda proces”; karta „Prowadzi” ma samo
 * imię, jedno zdanie i „Aplikuj”.
 */
export function JasnyJob({ data, base, host, formPreview }: CareerJobLayoutProps) {
  const job = mockJob(data);
  const { recruiter } = data;
  const first = job.recruiterFirstName;
  const rodoHref = careerHref(base, { to: "rodo" });
  const homeHref = careerHref(base, { to: "home" });
  const hasRequirements = job.must.length > 0 || job.nice.length > 0;
  // Kroki podają „umowa b2b” małymi literami — w treści jak w faktach („Umowa B2B”).
  const contract = job.facts.find((f) => f.key === "contract")?.value;
  const stepNote = (note: string) =>
    contract && note.toLocaleLowerCase("pl-PL") === `umowa ${contract.toLocaleLowerCase("pl-PL")}`
      ? `Umowa ${contract}`
      : cap(note);

  return (
    <div className={s.root}>
      <header className={s.bar}>
        <div className={s.barInner}>
          <a href={homeHref} className={s.brand} aria-label="B2B Network — Kariera, wszystkie rekrutacje">
            <B2BLogo variant="color" height={30} />
            <span className={s.brandDivider} aria-hidden="true" />
            <span className={s.brandLabel}>Kariera</span>
          </a>
          <nav className={s.barNav} aria-label="Strona kariery">
            <a href={homeHref} className={s.barLink}>
              Wszystkie rekrutacje
            </a>
            <a href={`#${FORM_ID}`} className={`${s.btn} ${s.btnPrimary} ${s.btnSmall}`}>
              Aplikuj
            </a>
          </nav>
        </div>
      </header>

      <main>
        <section id={HERO_ID} className={s.hero} aria-labelledby="kr-job-title">
          <MarkB />
          <div className={s.heroInner}>
            <div className={s.heroMain}>
              <p className={s.eyebrow}>Rekrutacja IT</p>
              <h1 id="kr-job-title" className={s.title}>
                {job.title}
              </h1>
              {job.subtitle && <p className={s.subtitle}>{cap(job.subtitle)}</p>}
              {job.facts.length > 0 && (
                <dl className={s.facts} aria-label="Najważniejsze informacje">
                  {job.facts.map((f) => (
                    <div key={f.key} className={s.fact}>
                      <span className={s.factIcon} aria-hidden="true">
                        <FactIcon kind={f.key} />
                      </span>
                      <div className={s.factText}>
                        <dt className={s.factLabel}>{f.label}</dt>
                        <dd className={s.factValue}>{f.value}</dd>
                      </div>
                    </div>
                  ))}
                </dl>
              )}
              <div className={s.heroActions}>
                <a href={`#${FORM_ID}`} className={`${s.btn} ${s.btnPrimary}`}>
                  Aplikuj — 2 minuty
                </a>
                {hasRequirements && (
                  <a href="#wymagania" className={`${s.btn} ${s.btnGhost}`}>
                    Zobacz wymagania
                  </a>
                )}
              </div>
            </div>

            <aside className={s.lead} aria-label="Kto prowadzi rekrutację">
              <div className={s.leadHead}>
                <span className={s.avatar} aria-hidden="true">
                  {first.charAt(0).toLocaleUpperCase("pl-PL")}
                </span>
                <span className={s.leadName}>Prowadzi: {first}</span>
              </div>
              <p className={s.leadNote}>
                Zgłoszenia czyta i odpowiada na nie osobiście — wystarczy CV.
              </p>
              <a
                href={`#${FORM_ID}`}
                className={`${s.btn} ${s.btnPrimary} ${s.btnBlock} ${s.leadApply}`}
              >
                Aplikuj
              </a>
            </aside>
          </div>
        </section>

        <div className={s.body}>
          <div className={s.content}>
            {job.about.length > 0 && (
              <section aria-label="O projekcie" className={s.section}>
                {job.about.map((block, i) => {
                  const heading = block.heading ?? (i === 0 ? "O projekcie" : null);
                  return (
                    <div key={i} className={s.block}>
                      {heading && <h2 className={s.h2}>{cap(heading)}</h2>}
                      {block.text && <p className={s.para}>{block.text}</p>}
                      {block.bullets.length > 0 && (
                        <ul className={s.bullets}>
                          {block.bullets.map((b) => (
                            <li key={b}>{b}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </section>
            )}

            {hasRequirements && (
              <section id="wymagania" aria-label="Wymagania" className={`${s.section} ${s.anchor}`}>
                {job.must.length > 0 && (
                  <>
                    <h2 className={s.h2}>Wymagane</h2>
                    <ul className={s.must} aria-label="Wymagane">
                      {job.must.map((m) => (
                        <li key={m.name}>
                          <Check />
                          <span>
                            <span className={s.mustName}>{cap(m.name)}</span>
                            {m.note && <span className={s.mustNote}>{m.note}</span>}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {job.nice.length > 0 && (
                  <div className={job.must.length > 0 ? s.nice : undefined}>
                    {job.must.length > 0 ? (
                      <h3 className={s.h3}>Mile widziane</h3>
                    ) : (
                      <h2 className={s.h2}>Mile widziane</h2>
                    )}
                    <p className={s.niceNote}>Nie musisz mieć wszystkiego — to dodatkowe atuty.</p>
                    <ul className={s.chips} aria-label="Mile widziane">
                      {job.nice.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )}

            {job.steps.length > 0 && (
              <section aria-label="Proces rekrutacji" className={s.section}>
                <h2 className={s.h2}>Jak wygląda proces</h2>
                <ol className={s.steps}>
                  {job.steps.map((step, i) => (
                    <li key={step.title}>
                      <span className={s.stepNum} aria-hidden="true">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className={s.stepTitle}>{cap(step.title)}</span>
                      <span className={s.stepNote}>{stepNote(step.note)}</span>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>

          <section
            id={FORM_ID}
            tabIndex={-1}
            className={s.formCol}
            aria-label="Aplikuj"
          >
            <div className={s.formCard}>
              <h2 className={s.formTitle}>
                Aplikuj
              </h2>
              <p className={s.formLead}>
                Zgłoszenia czyta osobiście {first}. Wystarczy CV — resztę omówicie na rozmowie.
              </p>
              <div className={s.form}>
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
              <p className={s.formFoot}>
                Administratorem danych jest B2B.NET S.A. Szczegóły:{" "}
                <a href={rodoHref} className={s.inlineLink}>
                  klauzula informacyjna RODO
                </a>
                .
              </p>
            </div>
          </section>
        </div>
      </main>

      <footer className={s.footer}>
        <div className={s.footerInner}>
          <div className={s.footerTop}>
            <B2BLogo variant="color" height={24} />
            <span className={s.footerBrand}>B2B.NET S.A.</span>
            <a href={rodoHref} className={s.footerLink}>
              Klauzula informacyjna RODO
            </a>
            <span className={s.footerHost}>
              {careerVisibleUrl(host, base, { to: "job", slug: job.slug })}
            </span>
          </div>
          <p className={s.legal}>{COMPANY_LEGAL_LINE}</p>
        </div>
      </footer>

      <JasnyApplyDock heroId={HERO_ID} formId={FORM_ID} />
    </div>
  );
}
