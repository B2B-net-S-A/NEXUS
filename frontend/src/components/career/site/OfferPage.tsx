import type { CareerBoardJob, CareerJobResponse } from "@/lib/career/api";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { offerMapMode, officeNote } from "@/lib/career/polandMap";
import { bigWord, boardCardFor, facetCounts, jobCities, offerTags, similarJobs } from "@/lib/career/site";

import { mockJob } from "../layouts/jobModel";
import { ApplyDock } from "./ApplyDock";
import { OfferApply, type OfferApplyProps } from "./OfferApply";
import { OfferRequirements } from "./OfferRequirements";
import { OfferClosed } from "./OfferClosed";
import { QuickApply, type QuickApplyProps } from "./QuickApply";
import { SentGate } from "./SentGate";
import { ChapterMark, SiteFrame, Who, siteStyles as s } from "./SiteFrame";
import { StairsSteps } from "./Steps";
import g from "./glass.module.css";
import { OfferCityMap, RemoteMap } from "./GlassMap";

const TASKS_HEADING = /^czym si[eę] zajmiesz$/i;
const STEP_WORDS = ["", "Jeden krok", "Dwa kroki", "Trzy kroki", "Cztery kroki", "Pięć kroków", "Sześć kroków"];
/** „Cztery kroki do startu” — liczba kroków z procesu rekrutacji. */
export function stepsHeading(n: number): string {
  return `${STEP_WORDS[n] ?? `${n} kroków`} do startu`;
}

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
        <OfferClosed data={data} others={others} base={base} total={board ? jobs.length : null} />
      </SiteFrame>
    );
  }

  const m = mockJob(data);
  const word = bigWord(card);
  const skills = [...(card?.must ?? []), ...(card?.nice ?? [])];
  const tags = offerTags(word, card?.must ?? []);
  const name = m.recruiterFirstName.trim();
  const leads = name ? `Prowadzi ${name}` : null;
  const callback = name ? `${name} odezwie się do Ciebie po przejrzeniu CV.` : "Odezwiemy się po przejrzeniu CV.";
  const tasksBlock = m.about.find((b) => b.heading && TASKS_HEADING.test(b.heading) && b.bullets.length > 0);
  const aboutBlocks = m.about.filter((b) => b !== tasksBlock);
  const hasAbout = aboutBlocks.length > 0;
  const hasChecklist = m.must.length + m.nice.length > 0;
  const hasProject = hasAbout || hasChecklist || Boolean(tasksBlock);
  const steps = m.steps;
  const chapters = ["Oferta", ...(hasProject ? ["Projekt"] : []), ...(steps.length ? ["Proces"] : []), "Aplikacja"];
  const at = (n: string) => chapters.indexOf(n);
  const params = data.job.params;
  const mapMode = offerMapMode("open", params, (city) => jobCities({ city }));
  const facets = facetCounts(jobs);
  const map =
    mapMode.kind === "remote" ? (
      <RemoteMap uid="oferta-zdalna" className={g.offerMap} />
    ) : mapMode.kind === "focus" ? (
      <div className={g.offerMap}>
        <OfferCityMap uid="oferta-miasto" facets={facets} cities={mapMode.cities} note={officeNote(params)} className={g.mapDesk} />
        <OfferCityMap uid="oferta-miasto-tel" facets={facets} cities={mapMode.cities} note={officeNote(params)} phone className={g.mapPhone} />
      </div>
    ) : null;

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
          total: board ? jobs.length : null,
        }}
      >
        <main>
          <section className={`${s.ch} ${s.chRed} ${g.offerHero}`}>
            <ChapterMark index={0} count={chapters.length} name="Oferta" />
            <div className={`${s.wrap} ${g.offerGrid}`}>
              <div className={g.offerText}>
                <a href={homeHref} className={g.back}>
                  ← Wszystkie oferty{board ? ` (${jobs.length})` : ""}
                </a>
                {tags.length > 0 ? (
                  <ul className={g.tags} aria-label="Technologie">
                    {tags.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                ) : null}
                <h1 className={`${g.offerTitle} ${m.title.length > 40 ? g.offerTitleLong : ""}`}>{m.title}</h1>
                {m.subtitle ? <p className={g.offerSummary}>{m.subtitle}</p> : null}
                {m.facts.length > 0 ? (
                  <dl className={g.glassFacts}>
                    {m.facts.map((f) => (
                      <div key={f.key}>
                        <dt>{f.label}</dt>
                        <dd>{f.value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                <div className={g.offerWho}>
                  {leads ? <Who name={leads} initialOf={name} note={callback} white /> : null}
                  <a href="#aplikuj" className={g.fullLinkA}>
                    Pełny formularz: stawka, dostępność →
                  </a>
                </div>
              </div>
              <div className={g.offerAside}>
                {map}
                <QuickApply linkSlug={m.slug} rodoHref={rodoHref} {...quick} />
              </div>
            </div>
          </section>

          {hasProject ? (
            <section className={`${s.ch} ${s.chSnow} ${g.project}`} aria-label="O projekcie">
              <ChapterMark index={at("Projekt")} count={chapters.length} name="Projekt" />
              <div className={`${s.wrap} ${g.projectGrid} ${hasAbout || hasChecklist ? (tasksBlock ? "" : g.projectSolo) : g.projectSolo}`}>
                {hasAbout || hasChecklist ? (
                  <div className={g.projectCol}>
                    {hasAbout ? (
                      <>
                        <h2 className={g.projectH}>O projekcie</h2>
                        <div className={g.projectText}>
                          {aboutBlocks.map((b, i) => (
                            <div key={i}>
                              {b.text ? (
                                <p>
                                  {b.heading ? <b>{b.heading}. </b> : null}
                                  {b.text}
                                </p>
                              ) : null}
                              {b.bullets.length > 0 ? (
                                <>
                                  {b.heading ? (
                                    <p>
                                      <b>{b.heading}</b>
                                    </p>
                                  ) : null}
                                  <ul className={g.taskList}>
                                    {b.bullets.map((t, j) => (
                                      <li key={j}>
                                        <span>{String(j + 1).padStart(2, "0")}</span>
                                        {t}
                                      </li>
                                    ))}
                                  </ul>
                                </>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                    {hasChecklist ? <OfferRequirements must={m.must} nice={m.nice} skills={skills} /> : null}
                  </div>
                ) : null}
                {tasksBlock ? (
                  <div className={g.projectCol}>
                    <h2 className={g.projectH}>Czym się zajmiesz</h2>
                    <ol className={g.taskList}>
                      {tasksBlock.bullets.map((t, i) => (
                        <li key={i}>
                          <span>{String(i + 1).padStart(2, "0")}</span>
                          {t}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          {steps.length > 0 ? (
            <section className={`${s.ch} ${s.chRed} ${g.process}`} aria-label="Proces rekrutacji">
              <ChapterMark index={at("Proces")} count={chapters.length} name="Proces" />
              <div className={s.wrap}>
                <h2 className={g.processH}>{stepsHeading(steps.length)}</h2>
                <StairsSteps steps={steps} uid="oferta-kroki" />
              </div>
            </section>
          ) : null}

          <section id="aplikuj" tabIndex={-1} className={`${s.ch} ${s.chRed} ${s.s4} ${g.applyA}`} aria-label="Aplikuj">
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
                    <h2 className={g.processH}>
                      Aplikuj
                      <br />w 2 minuty
                    </h2>
                    <p className={s.body}>Wystarczy CV. Stawka i dostępność są opcjonalne. {callback}</p>
                    {name ? <Who name={name} note={`rekruter · ${m.title}`} white /> : null}
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
