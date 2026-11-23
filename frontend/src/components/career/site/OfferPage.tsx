import type { CareerBoardJob, CareerJobResponse } from "@/lib/career/api";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { bigWord, boardCardFor, similarJobs, wordEm } from "@/lib/career/site";

import { mockJob } from "../layouts/jobModel";
import { ApplyDock } from "./ApplyDock";
import { OfferApply, type OfferApplyProps } from "./OfferApply";
import { OfferChecklist } from "./OfferChecklist";
import { OfferClosed } from "./OfferClosed";
import { QuickApply, type QuickApplyProps } from "./QuickApply";
import { SentGate } from "./SentGate";
import { ChapterMark, SiteFrame, Who, siteStyles as s } from "./SiteFrame";
import { StepsList } from "./Steps";

const TASKS_HEADING = /^czym si[eę] zajmiesz$/i;

/**
 * Strona rekrutacji `/r/<slug>` — jeden szablon dla każdej roli (makiety
 * OfertaA i OfertaManager, decyzja Artura 23.11.2026, zamiast trzech szablonów
 * z 28.10.2026). Cztery rozdziały: oferta z listą „Co już masz?”, projekt,
 * proces i aplikacja. Treść wyłącznie z opublikowanej wersji opisu; tablica
 * (`board`) daje tylko krótkie nazwy umiejętności (wielkie słowo, pogrubienia)
 * i podobne oferty. Bez tablicy strona działa, tylko bez tych dodatków.
 */
export function OfferPage({
  data,
  board,
  base,
  formPreview,
  quick,
}: {
  data: CareerJobResponse;
  board: readonly CareerBoardJob[] | null;
  base: CareerBase;
  formPreview?: OfferApplyProps["preview"];
  /** Harness: stan szybkiej aplikacji bez wysyłki. */
  quick?: Pick<QuickApplyProps, "preview">;
}) {
  const jobs = board ?? [];
  const card = boardCardFor(jobs, [data.canonical_slug, data.job.slug]);
  const others = similarJobs(jobs, [data.canonical_slug, data.job.slug], card?.category);
  const homeHref = careerHref(base, { to: "home" });
  const rodoHref = careerHref(base, { to: "rodo" });

  if (data.status === "closed") {
    return (
      <SiteFrame homeHref={homeHref} rodoHref={rodoHref}>
        <OfferClosed data={data} others={others} base={base} />
      </SiteFrame>
    );
  }

  const m = mockJob(data);
  const word = bigWord(card);
  const skills = [...(card?.must ?? []), ...(card?.nice ?? [])];
  const name = m.recruiterFirstName.trim();
  const leads = name ? `Prowadzi ${name}` : null;
  const callback = name ? `${name} odezwie się do Ciebie po przejrzeniu CV.` : "Odezwiemy się po przejrzeniu CV.";
  const tasksBlock = m.about.find((b) => b.heading && TASKS_HEADING.test(b.heading) && b.bullets.length > 0);
  const aboutBlocks = m.about.filter((b) => b !== tasksBlock);
  const hasProject = m.about.length > 0;
  const hasChecklist = m.must.length + m.nice.length > 0;
  const chapters = ["Oferta", ...(hasProject ? ["Projekt"] : []), ...(m.steps.length ? ["Proces"] : []), "Aplikacja"];
  const at = (n: string) => chapters.indexOf(n);

  return (
    <SiteFrame homeHref={homeHref} rodoHref={rodoHref}>
      <SentGate
        sent={{
          variant: "job",
          recruiterFirstName: name,
          jobTitle: m.title,
          steps: m.steps,
          others,
          base,
        }}
      >
        <main>
          <section className={`${s.ch} ${s.chRed} ${s.s1}`}>
            <ChapterMark index={0} count={chapters.length} name="Oferta" />
            <div className={s.wrap}>
              {word ? (
                <p
                  aria-hidden="true"
                  className={`${s.display} ${s.word}`}
                  style={{ "--em": wordEm(word) } as React.CSSProperties}
                >
                  {word}
                </p>
              ) : null}
              <div className={s.row1}>
                <div>
                  <h1 className={`${s.title} ${m.title.length > 60 ? s.titleLong : ""}`}>{m.title}</h1>
                  {m.subtitle ? <p className={s.summary}>{m.subtitle}</p> : null}
                  {m.facts.length > 0 ? (
                    <dl className={s.facts}>
                      {m.facts.map((f) => (
                        <div key={f.key}>
                          <dt>{f.label}</dt>
                          <dd>{f.value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                  <div className={s.ctas}>
                    {leads ? <Who name={leads} initialOf={name} white /> : null}
                    <a href="#aplikuj" className={s.fullLink}>
                      Pełny formularz: stawka, dostępność →
                    </a>
                  </div>
                </div>
                {/* Prawa kolumna od 1024 px: szybka aplikacja na pierwszym ekranie, pod nią lista. */}
                <div className={s.side}>
                  <QuickApply linkSlug={m.slug} rodoHref={rodoHref} {...quick} />
                  {hasChecklist ? (
                    <OfferChecklist
                      must={m.must.map((x) => ({ text: x.name, note: x.note }))}
                      nice={m.nice.map((x) => ({ text: x }))}
                      skills={skills}
                    />
                  ) : null}
                </div>
              </div>
            </div>
          </section>

          {hasProject ? (
            <section
              className={`${s.ch} ${s.chSnow} ${s.s2} ${hasChecklist ? s.s2Hang : ""}`}
              aria-label="O projekcie"
            >
              <ChapterMark index={at("Projekt")} count={chapters.length} name="Projekt" />
              <div className={s.wrap}>
                <div className={`${s.row2} ${tasksBlock ? "" : s.row2Solo}`}>
                  <div>
                    <p aria-hidden="true" className={`${s.display} ${s.projectWord}`} style={{ "--em": wordEm("Projekt") } as React.CSSProperties}>
                      Projekt
                    </p>
                    {aboutBlocks.map((b, i) => (
                      <div key={i} className={s.about}>
                        {b.text ? (
                          <p>
                            {i === 0 && !b.heading ? <b>O projekcie. </b> : null}
                            {b.heading ? <b>{b.heading}. </b> : null}
                            {b.text}
                          </p>
                        ) : null}
                        {b.bullets.length > 0 ? (
                          <>
                            {b.heading ? <p><b>{b.heading}</b></p> : null}
                            <ul className={s.tasks}>
                              {b.bullets.map((t, j) => (
                                <li key={j}>
                                  <span className={s.mono}>{String(j + 1).padStart(2, "0")}</span>
                                  {t}
                                </li>
                              ))}
                            </ul>
                          </>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  {tasksBlock ? (
                    <div>
                      <h2 className={s.h2}>Czym się zajmiesz</h2>
                      <ol className={s.tasks}>
                        {tasksBlock.bullets.map((t, i) => (
                          <li key={i}>
                            <span className={s.mono}>{String(i + 1).padStart(2, "0")}</span>
                            {t}
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}
                </div>
              </div>
            </section>
          ) : null}

          {m.steps.length > 0 ? (
            <section className={`${s.ch} ${s.chInk} ${s.s3}`} aria-label="Proces rekrutacji">
              <ChapterMark index={at("Proces")} count={chapters.length} name="Proces" />
              <div className={s.wrap}>
                <div className={s.s3Top}>
                  <span aria-hidden="true" className={`${s.display} ${s.s3Big}`}>
                    {m.steps.length}
                  </span>
                  <h2 className={s.lead}>
                    <span className={s.srOnly}>{m.steps.length}</span>{" "}
                    kroki.
                    <br />
                    Jak wygląda proces
                  </h2>
                  {leads ? <Who name={leads} initialOf={name} note={callback} /> : null}
                </div>
                <StepsList steps={m.steps} recruiterFirstName={name} />
              </div>
            </section>
          ) : null}

          <section id="aplikuj" tabIndex={-1} className={`${s.ch} ${s.chRed} ${s.s4}`} aria-label="Aplikuj">
            <ChapterMark index={chapters.length - 1} count={chapters.length} name="Aplikacja" />
            <div className={s.wrap}>
              <OfferApply
                linkSlug={m.slug}
                variant="job"
                rodoHref={rodoHref}
                recruiterFirstName={name}
                jobTitle={m.title}
                factsLine={m.factsLine}
                preview={formPreview}
                intro={
                  <>
                    <p aria-hidden="true" className={`${s.display} ${s.s4Big}`}>
                      2
                    </p>
                    <h2 className={s.lead}>
                      <span className={s.srOnly}>2</span>{" "}minuty. Aplikuj
                    </h2>
                    <p className={s.body}>{callback}</p>
                    {name ? <Who name={name} note={m.title} white /> : null}
                  </>
                }
              />
            </div>
          </section>
          <ApplyDock />
        </main>
      </SentGate>
    </SiteFrame>
  );
}
