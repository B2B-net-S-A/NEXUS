/**
 * MAKIETA — wariant `karta` („najpierw telefon”): czerwony pas marki, na nim
 * biała karta z tytułem i czterema kaflami faktów; wymagania raz, z „Znam to”;
 * reszta w akordeonach; na telefonie przyklejony pasek „Aplikuj”, na desktopie
 * przyklejony panel z prawej. Całość do ogarnięcia w 20 sekund.
 */
import { CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { B2BLogo } from "./B2BLogo";
import type { MockupProps } from "./index";
import { ApplyBar, MustList } from "./KartaParts";
import { mockJob, type MockAboutBlock, type MockFact } from "./model";
import s from "./karta.module.css";

const FORM_ID = "aplikuj";

type TileIcon = MockFact["key"] | "process";

interface Tile {
  key: string;
  icon: TileIcon;
  label: string;
  value: string;
  sub?: string;
  href?: string;
}

function Icon({ name }: { name: TileIcon }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
      {name === "city" ? (
        <>
          <path {...common} d="M12 21s-6.5-6.1-6.5-11.2a6.5 6.5 0 0 1 13 0C18.5 14.9 12 21 12 21z" />
          <circle {...common} cx="12" cy="9.8" r="2.4" />
        </>
      ) : name === "mode" ? (
        <>
          <path {...common} d="M3.5 11 12 4l8.5 7" />
          <path {...common} d="M5.5 9.5V20h13V9.5" />
          <path {...common} d="M10 20v-5.5h4V20" />
        </>
      ) : name === "contract" ? (
        <>
          <path {...common} d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20z" />
          <path {...common} d="M14 3.5V8h4M9.5 12.5h5M9.5 16h5" />
        </>
      ) : name === "seniority" ? (
        <path {...common} d="M5 19v-4M10 19v-8M15 19v-11M20 19V4" />
      ) : name === "start" ? (
        <>
          <rect {...common} x="4" y="5.5" width="16" height="14.5" rx="2" />
          <path {...common} d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
        </>
      ) : (
        <>
          <circle {...common} cx="5.5" cy="6" r="2" />
          <circle {...common} cx="18.5" cy="18" r="2" />
          <path {...common} d="M7.5 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h7.5" />
        </>
      )}
    </svg>
  );
}

/** „rozmowa z Urszulą” → „rozmowy z Urszulą” (po „zaczynasz od”). */
function fromFirstStep(title: string): string {
  return title.replace(/^rozmowa\b/, "rozmowy");
}

function stepsWord(n: number): string {
  if (n === 1) return "krok";
  const d = n % 10;
  const t = n % 100;
  return d >= 2 && d <= 4 && (t < 12 || t > 14) ? "kroki" : "kroków";
}

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

/** Kafle: miasto, tryb, umowa (braki uzupełnia poziom/start) i na końcu proces. */
function tiles(job: ReturnType<typeof mockJob>): Tile[] {
  const primary = job.facts.filter((f) => f.key === "city" || f.key === "mode" || f.key === "contract");
  const extra = job.facts.filter((f) => f.key === "seniority" || f.key === "start");
  const picked = [...primary, ...extra].slice(0, 3);
  const out: Tile[] = picked.map((f) => ({ key: f.key, icon: f.key, label: f.label, value: f.value }));
  if (job.steps.length > 0) {
    out.push({
      key: "process",
      icon: "process",
      label: "Proces",
      value: `${job.steps.length} ${stepsWord(job.steps.length)}`,
      sub: `Zaczynasz od ${fromFirstStep(job.steps[0].title)}`,
      href: "#proces",
    });
  }
  return out;
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className={s.bullets}>
      {items.map((b, i) => (
        <li key={i}>{b}</li>
      ))}
    </ul>
  );
}

function teaserOf(blocks: MockAboutBlock[]): string {
  const first = blocks.find((b) => b.text)?.text ?? blocks[0]?.bullets[0] ?? "";
  return first;
}

interface Section {
  id: string;
  title: string;
  teaser: string;
  body: React.ReactNode;
}

export function Karta({ data, base, host }: MockupProps) {
  const job = mockJob(data);
  const factTiles = tiles(job);
  const intro = job.about.filter((b) => !b.heading);
  const headed = job.about.filter((b) => b.heading);

  const sections: Section[] = [];
  if (intro.length) {
    sections.push({
      id: "o-projekcie",
      title: "O projekcie",
      teaser: teaserOf(intro),
      body: intro.map((b, i) =>
        b.bullets.length ? <Bullets key={i} items={b.bullets} /> : <p key={i}>{b.text}</p>,
      ),
    });
  }
  headed.forEach((b, i) => {
    sections.push({
      id: `sekcja-${i}`,
      title: b.heading as string,
      teaser: b.bullets.length ? `${b.bullets.length} punktów · ${b.bullets[0]}` : (b.text ?? ""),
      body: b.bullets.length ? <Bullets items={b.bullets} /> : <p>{b.text}</p>,
    });
  });
  if (job.steps.length) {
    sections.push({
      id: "proces",
      title: "Jak wygląda proces",
      teaser: job.steps.map((st) => cap(st.title)).join(" → "),
      body: (
        <ol className={s.steps}>
          {job.steps.map((st, i) => (
            <li key={i} className={s.step}>
              <span className={s.stepNo} aria-hidden>
                {i + 1}
              </span>
              <span>
                <span className={s.stepTitle}>{cap(st.title)}</span>
                <span className={s.stepNote}>{cap(st.note)}</span>
              </span>
            </li>
          ))}
        </ol>
      ),
    });
  }

  const homeHref = careerHref(base, { to: "home" });
  const rodoHref = careerHref(base, { to: "rodo" });
  const firstStep = job.steps[0]?.title ?? null;

  return (
    <div className={s.root} lang="pl">
      <header className={s.band}>
        <div className={s.bandInner}>
          <a href={homeHref} className={s.logoLink} aria-label="B2B Network — wszystkie rekrutacje">
            <B2BLogo variant="white" height={40} />
          </a>
          <a href={homeHref} className={s.bandLink}>
            Wszystkie rekrutacje
          </a>
        </div>
        <div className={s.bandMark} aria-hidden>
          <B2BLogo variant="white" height={420} />
        </div>
      </header>

      <div className={s.layout}>
        <main className={s.main}>
          <article className={`${s.card} ${s.hero}`}>
            <p className={s.eyebrow}>Rekrutacja IT · B2B Network</p>
            <h1 className={s.title}>{job.title}</h1>
            {job.subtitle ? <p className={s.subtitle}>{job.subtitle}</p> : null}
            {factTiles.length ? (
              <ul className={s.tiles} data-odd={factTiles.length % 2 ? "" : undefined}>
                {factTiles.map((t) => {
                  const inner = (
                    <>
                      <span className={s.tileHead}>
                        <span className={s.tileIcon}>
                          <Icon name={t.icon} />
                        </span>
                        <span className={s.tileLabel}>{t.label}</span>
                      </span>
                      <span className={s.tileValue}>{t.value}</span>
                      {t.sub ? <span className={s.tileSub}>{t.sub}</span> : null}
                    </>
                  );
                  return (
                    <li key={t.key} className={s.tile}>
                      {t.href ? (
                        <a href={t.href} className={s.tileLink}>
                          {inner}
                        </a>
                      ) : (
                        <div className={s.tileBody}>{inner}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </article>

          {job.must.length || job.nice.length ? (
            <section className={s.card} aria-label="Wymagania">
              {job.must.length ? <MustList items={job.must} /> : null}
              <p className={s.encourage}>Nie musisz mieć wszystkiego — aplikuj.</p>
              {job.nice.length ? (
                <div className={s.nice}>
                  <h3 className={s.niceTitle}>Mile widziane</h3>
                  <ul className={s.niceList}>
                    {job.nice.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}

          {sections.length ? (
            <section className={`${s.card} ${s.accordions}`} aria-label="Szczegóły">
              {sections.map((sec) => (
                <details key={sec.id} id={sec.id} className={s.acc}>
                  <summary className={s.accSummary}>
                    <span className={s.accText}>
                      <span className={s.accTitle}>{sec.title}</span>
                      {sec.teaser ? <span className={s.accTeaser}>{sec.teaser}</span> : null}
                    </span>
                    <span className={s.accChevron} aria-hidden>
                      <svg viewBox="0 0 24 24" width="22" height="22">
                        <path d="M6 9.5l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                  </summary>
                  <div className={s.accBody}>{sec.body}</div>
                </details>
              ))}
            </section>
          ) : null}

          <section id={FORM_ID} className={`${s.card} ${s.formCard}`} aria-labelledby="karta-form-title">
            <h2 id="karta-form-title" className={s.h2}>
              Aplikuj — 2 minuty
            </h2>
            <p className={s.formLead}>
              Na stanowisko <strong>{job.title}</strong>. Imię, e-mail i CV wystarczą.
            </p>
            <form className={s.form}>
              <div className={s.row2}>
                <label className={s.field}>
                  <span className={s.fieldLabel}>
                    Imię <span className={s.req}>*</span>
                  </span>
                  <input className={s.input} name="first_name" autoComplete="given-name" required />
                </label>
                <label className={s.field}>
                  <span className={s.fieldLabel}>
                    Nazwisko <span className={s.req}>*</span>
                  </span>
                  <input className={s.input} name="last_name" autoComplete="family-name" required />
                </label>
              </div>
              <label className={s.field}>
                <span className={s.fieldLabel}>
                  E-mail <span className={s.req}>*</span>
                </span>
                <input className={s.input} type="email" name="email" autoComplete="email" required />
              </label>
              <label className={s.drop}>
                <input className={s.fileInput} type="file" name="cv" accept=".pdf,.doc,.docx" required />
                <span className={s.dropIcon} aria-hidden>
                  <svg viewBox="0 0 24 24" width="26" height="26">
                    <path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className={s.dropText}>
                  <span className={s.dropTitle}>
                    Dodaj CV <span className={s.req}>*</span>
                  </span>
                  <span className={s.dropHint}>Upuść plik albo wybierz · PDF, DOC, DOCX do 10 MB</span>
                </span>
              </label>
              <div className={s.row2}>
                <label className={s.field}>
                  <span className={s.fieldLabel}>
                    Telefon <span className={s.opt}>(opcjonalnie)</span>
                  </span>
                  <input className={s.input} type="tel" name="phone" autoComplete="tel" />
                </label>
                <label className={s.field}>
                  <span className={s.fieldLabel}>
                    LinkedIn <span className={s.opt}>(opcjonalnie)</span>
                  </span>
                  <input className={s.input} type="url" name="linkedin" placeholder="linkedin.com/in/…" />
                </label>
              </div>
              <label className={s.consent}>
                <input type="checkbox" name="consent" required className={s.check} />
                <span>
                  {CONSENT_CURRENT_TEXT} <span className={s.req}>*</span>
                </span>
              </label>
              <label className={s.consent}>
                <input type="checkbox" name="consent_future" className={s.check} />
                <span>
                  {CONSENT_FUTURE_TEXT} <span className={s.opt}>(dobrowolna)</span>
                </span>
              </label>
              <button type="button" className={s.submit}>
                Wyślij zgłoszenie
              </button>
            </form>
          </section>
        </main>

        <aside className={s.aside} aria-label="Aplikuj">
          <div className={s.asideCard}>
            <p className={s.asideTitle}>Aplikuj w 2 minuty</p>
            <ul className={s.asideList}>
              <li>Imię, nazwisko, e-mail i CV</li>
              <li>Bez listu motywacyjnego</li>
              {firstStep ? <li>Pierwszy krok: {firstStep}</li> : null}
            </ul>
            <a href={`#${FORM_ID}`} className={s.applyBtn}>
              Aplikuj — 2 minuty
            </a>
          </div>
        </aside>
      </div>

      <footer className={s.footer}>
        <div className={s.footerTop}>
          <span className={s.footerBrand}>B2B.NET S.A.</span>
          <a href={rodoHref} className={s.footerLink}>
            Klauzula informacyjna RODO
          </a>
          <span>{host}</span>
        </div>
        <p className={s.legal}>{COMPANY_LEGAL_LINE}</p>
      </footer>

      <ApplyBar targetId={FORM_ID} />
    </div>
  );
}
