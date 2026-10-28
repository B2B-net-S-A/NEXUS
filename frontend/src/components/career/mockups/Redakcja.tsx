import type { ReactNode } from "react";

import { CONSENT_CURRENT_TEXT, CONSENT_FUTURE_TEXT } from "@/lib/career/apply";
import { careerHref } from "@/lib/career/host";

import { COMPANY_LEGAL_LINE } from "../CareerFooter";
import { B2BLogo } from "./B2BLogo";
import type { MockupProps } from "./index";
import { mockJob, type MockAboutBlock } from "./model";
import s from "./redakcja.module.css";

/**
 * MAKIETA — wariant `redakcja` („plakat / strona magazynu”): biel, czerń,
 * jeden akcent czerwieni B2B; typografia niesie całą stronę. Sekcje numerowane
 * dynamicznie — brak treści = brak sekcji, numeracja bez dziur.
 */

interface Section {
  id: string;
  name: string;
  body: ReactNode;
}

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

function issueDate(iso: string | null | undefined): string | null {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
  return m ? `${m[3]}.${m[2]}.${m[1]}` : null;
}

function TextBlocks({ blocks }: { blocks: MockAboutBlock[] }) {
  return (
    <div className={s.prose}>
      {blocks.map((b, i) => (
        <div key={i}>
          {b.heading ? <h3 className={s.subhead}>{b.heading}</h3> : null}
          {b.text ? <p className={i === 0 && !b.heading ? s.lead : undefined}>{b.text}</p> : null}
        </div>
      ))}
    </div>
  );
}

function BulletBlocks({ blocks }: { blocks: MockAboutBlock[] }) {
  return (
    <div className={s.prose}>
      {blocks.map((b, i) => (
        <div key={i}>
          {blocks.length > 1 && b.heading ? <h3 className={s.subhead}>{b.heading}</h3> : null}
          <ul className={s.bullets}>
            {b.bullets.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function Redakcja({ data, base }: MockupProps) {
  const job = mockJob(data);
  const closed = data.status === "closed";
  const date = issueDate(data.published_at);
  const textBlocks = job.about.filter((b) => b.bullets.length === 0);
  const bulletBlocks = job.about.filter((b) => b.bullets.length > 0);
  const tasksName =
    bulletBlocks.length === 1 && bulletBlocks[0].heading ? bulletBlocks[0].heading : "Czym się zajmiesz";

  const sections: Section[] = [];
  if (textBlocks.length) {
    sections.push({ id: "projekt", name: "Projekt", body: <TextBlocks blocks={textBlocks} /> });
  }
  if (bulletBlocks.length) {
    sections.push({ id: "zadania", name: tasksName, body: <BulletBlocks blocks={bulletBlocks} /> });
  }
  if (job.must.length || job.nice.length) {
    // Długa lista (np. 20 technologii) w jednej wąskiej kolumnie to ściana — wtedy
    // „Wymagane” i „Mile widziane” jedna pod drugą, każda w dwóch kolumnach.
    const long = job.must.length > 8;
    const listClass = long ? `${s.reqList} ${s.reqListCols}` : s.reqList;
    sections.push({
      id: "wymagania",
      name: "Czego szukamy",
      body: (
        <div className={long ? s.reqStack : job.must.length && job.nice.length ? s.reqGrid : undefined}>
          {job.must.length ? (
            <div>
              <h3 className={s.reqHead}>Wymagane</h3>
              <ul className={listClass}>
                {job.must.map((m) => (
                  <li key={m.name}>
                    <span className={s.reqName}>{m.name}</span>
                    {m.note ? <span className={s.reqNote}>{m.note}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {job.nice.length ? (
            <div className={s.nice}>
              <h3 className={s.reqHead}>
                Mile widziane <span className={s.reqHint}>— atut, nie warunek</span>
              </h3>
              <ul className={listClass}>
                {job.nice.map((n) => (
                  <li key={n}>
                    <span className={s.reqName}>{n}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ),
    });
  }
  if (job.steps.length) {
    sections.push({
      id: "proces",
      name: "Jak wygląda proces",
      body: (
        <ol className={s.steps}>
          {job.steps.map((st, i) => (
            <li key={st.title}>
              <span className={s.stepNo}>{i + 1}</span>
              <span className={s.stepTitle}>{cap(st.title)}</span>
              <span className={s.stepNote}>{cap(st.note).replace(/\bb2b\b/gi, "B2B")}</span>
            </li>
          ))}
        </ol>
      ),
    });
  }
  if (!closed) {
    sections.push({
      id: "aplikuj",
      name: "Aplikuj",
      body: (
        <form className={s.form} noValidate>
          <p className={s.formIntro}>
            Wystarczy CV i dane kontaktowe. Zgłoszenie trafi bezpośrednio do osoby, która prowadzi
            rekrutację — {job.recruiterFirstName}.
          </p>
          <div className={s.fieldGrid}>
            <label className={s.field}>
              <span className={s.label}>
                Imię <span className={s.req}>*</span>
              </span>
              <input type="text" name="first_name" autoComplete="given-name" required />
            </label>
            <label className={s.field}>
              <span className={s.label}>
                Nazwisko <span className={s.req}>*</span>
              </span>
              <input type="text" name="last_name" autoComplete="family-name" required />
            </label>
            <label className={s.field}>
              <span className={s.label}>
                E-mail <span className={s.req}>*</span>
              </span>
              <input type="email" name="email" autoComplete="email" required />
            </label>
            <label className={s.field}>
              <span className={s.label}>
                Telefon <span className={s.opt}>opcjonalnie</span>
              </span>
              <input type="tel" name="phone" autoComplete="tel" />
            </label>
            <label className={`${s.field} ${s.wide}`}>
              <span className={s.label}>
                LinkedIn <span className={s.opt}>opcjonalnie</span>
              </span>
              <input type="url" name="linkedin" placeholder="https://linkedin.com/in/…" />
            </label>
          </div>
          <label className={s.drop}>
            <span className={s.label}>
              CV <span className={s.req}>*</span>
            </span>
            <span className={s.dropBody}>
              <span className={s.dropMain}>
                Przeciągnij plik tutaj albo <span className={s.dropLink}>wybierz z dysku</span>
              </span>
              <span className={s.dropHint}>PDF, DOC, DOCX do 10 MB</span>
            </span>
            <input type="file" name="cv" accept=".pdf,.doc,.docx" className={s.fileInput} />
          </label>
          <div className={s.consents}>
            <label className={s.consent}>
              <input type="checkbox" name="consent" required />
              <span>
                {CONSENT_CURRENT_TEXT} <span className={s.req}>*</span>
              </span>
            </label>
            <label className={s.consent}>
              <input type="checkbox" name="consent_future" />
              <span>
                {CONSENT_FUTURE_TEXT} <span className={s.opt}>(dobrowolna)</span>
              </span>
            </label>
          </div>
          <div className={s.submitRow}>
            <button type="button" className={s.button}>
              Wyślij zgłoszenie
            </button>
            <a href={careerHref(base, { to: "rodo" })} className={s.quietLink}>
              Jak przetwarzamy Twoje dane
            </a>
          </div>
        </form>
      ),
    });
  }

  const meta = [
    ...job.facts.map((f) => ({ label: f.label, value: f.value })),
    { label: "Prowadzi", value: job.recruiterFirstName },
  ];

  return (
    <div className={s.root}>
      <header className={s.bar}>
        <div className={s.barInner}>
          <a href={careerHref(base, { to: "home" })} className={s.brand} aria-label="B2B Network — Kariera">
            <B2BLogo variant="color" height={30} />
            <span className={s.brandSep} aria-hidden />
            <span className={s.brandWord}>Kariera</span>
          </a>
          {closed ? null : (
            <a href="#aplikuj" className={s.barCta}>
              Aplikuj
            </a>
          )}
        </div>
      </header>

      <main>
        <section className={s.hero}>
          <p className={s.kicker}>
            <span className={s.kickerRule} aria-hidden />
            Rekrutacja IT{date ? <span className={s.kickerDate}> · {date}</span> : null}
          </p>
          <h1 className={s.title}>{job.title}</h1>
          {job.subtitle ? <p className={s.subtitle}>{cap(job.subtitle)}</p> : null}

          {closed ? (
            <p className={s.closed}>
              Ta rekrutacja jest już zakończona.{" "}
              <a href={careerHref(base, { to: "home" })}>Zobacz otwarte rekrutacje</a>
            </p>
          ) : null}

          <div className={s.metaRow}>
            <dl className={s.meta}>
              {meta.map((m) => (
                <div key={m.label} className={s.metaItem}>
                  <dt>{m.label}</dt>
                  <dd>{m.value}</dd>
                </div>
              ))}
            </dl>
            {closed ? null : (
              <a href="#aplikuj" className={s.button}>
                Aplikuj <span aria-hidden>—</span> 2 minuty
              </a>
            )}
          </div>
        </section>

        {sections.map((sec, i) => (
          <section key={sec.id} id={sec.id} className={s.section} aria-labelledby={`${sec.id}-h`}>
            <h2 id={`${sec.id}-h`} className={s.sectionHead}>
              <span className={s.sectionNo}>{String(i + 1).padStart(2, "0")}</span>
              <span className={s.sectionName}>{sec.name}</span>
            </h2>
            <div className={s.sectionBody}>{sec.body}</div>
          </section>
        ))}
      </main>

      <footer className={s.footer}>
        <div className={s.footerTop}>
          <span className={s.footerBrand}>B2B.NET S.A.</span>
          <a href={careerHref(base, { to: "rodo" })}>Klauzula informacyjna RODO</a>
        </div>
        <p className={s.legal}>{COMPANY_LEGAL_LINE}</p>
      </footer>
    </div>
  );
}
