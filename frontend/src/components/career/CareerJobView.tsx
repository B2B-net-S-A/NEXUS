import type { CareerJobResponse } from "@/lib/career/api";
import {
  aboutParagraphs,
  genitiveName,
  jobHandle,
  paramRows,
  recruiterLogin,
  splitTitle,
} from "@/lib/career/format";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";

import { ApplyDock } from "./ApplyDock";
import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerFooter } from "./CareerFooter";
import { CareerHero, Cmd } from "./CareerHero";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { CareerThemeScope } from "./CareerThemeScope";
import { ClosedNotice } from "./ClosedNotice";
import { FitSection } from "./FitSection";
import { ParamsPanel } from "./ParamsPanel";
import { ProcessSteps } from "./ProcessSteps";
import { CareerScene, CareerSceneScore } from "./scenes/CareerScene";
import { hasCareerScene, leftoverNice, processSteps, sceneItems } from "./scenes/model";
import { CareerSceneProvider } from "./scenes/SceneContext";
import { GlitchBug } from "./scenes/SceneParts";
import { TerminalChrome } from "./TerminalChrome";
import { DEFAULT_CAREER_THEME, isCareerThemeId } from "./themes";

const HERO_ID = "rekrutacja";

/**
 * Strona rekrutacji (`/r/<slug>`): hero, parametry, opis, wymagania, proces,
 * formularz. Zamknięta rekrutacja → `ClosedNotice`. Po wysłaniu → podziękowanie.
 *
 * Komponent prezentacyjny — dane przychodzą z serwera (strona) albo z mocków
 * (harness `/preview/kariera`).
 */
export function CareerJobView({
  data,
  base,
  host,
  formPreview,
}: {
  data: CareerJobResponse;
  base: CareerBase;
  /** Host żądania do stopki („kariera.dynaminds.pl", „nexus.dynaminds.pl"). */
  host: string;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const { job, recruiter } = data;
  const handle = jobHandle(job);
  const recruiterHref = recruiter.slug
    ? careerHref(base, { to: "recruiter", slug: recruiter.slug })
    : null;
  const rodoHref = careerHref(base, { to: "rodo" });
  const visibleUrl = careerVisibleUrl(host, base, { to: "job", slug: job.slug });

  if (data.status === "closed") {
    return (
      <CareerThemeScope theme={data.theme}>
        <ClosedNotice
          jobHandle={handle}
          recruiterFirstName={recruiter.first_name}
          recruiterPageHref={recruiterHref}
          recruiterSlug={recruiter.slug}
          otherJobs={data.other_jobs ?? []}
          jobHref={(slug) => careerHref(base, { to: "job", slug })}
        />
        <CareerFooter rodoHref={rodoHref} hostLabel={visibleUrl} />
      </CareerThemeScope>
    );
  }

  const show = job.show ?? { must: true, nice: true, params: true, process: true };
  const rows = show.params ? paramRows(job.params) : [];
  const paragraphs = aboutParagraphs(job.about);
  const chromePath = `~/b2bnetwork/kariera — zsh — ${handle}`;
  // Scena roli w hero (po 0478): te same wymagania i kroki co niżej na stronie.
  const theme = isCareerThemeId(data.theme) ? data.theme : DEFAULT_CAREER_THEME;
  const must = show.must ? job.must : [];
  const nice = show.nice ? job.nice : [];
  const items = sceneItems(must, nice);
  const withScene = hasCareerScene(theme) && items.length > 0;
  const login = recruiterLogin(recruiter.first_name);
  const whoamiNote =
    withScene && theme === "glitch" ? (
      <>
        zaprasza Cię do{" "}
        <GlitchBug index={0} wrong="rekrutcaji" right="rekrutacji" what="literówka w słowie „rekrutacji”" />
      </>
    ) : (
      "zaprasza Cię do rekrutacji"
    );

  return (
    <CareerThemeScope theme={data.theme}>
      <CareerSubmitGate
        thanks={{
          variant: "job",
          recruiterFirstName: recruiter.first_name,
          jobHandle: handle,
          chromePath,
          recruiterPageHref: recruiterHref,
          recruiterPageSlug: recruiter.slug,
        }}
      >
        <CareerSceneProvider
          theme={theme}
          items={items}
          extraNice={leftoverNice(nice, items)}
          steps={show.process ? processSteps(recruiter.first_name, job.params?.contract ?? null) : []}
          recruiterFirstName={recruiter.first_name}
          login={login}
          handle={handle}
        >
          <TerminalChrome path={chromePath} />
          <section id={HERO_ID} className="kr-top" aria-label="Rekrutacja" data-kr-with-scene={withScene ? "" : undefined}>
            <div className="kr-stage">
              <CareerHero
                login={login}
                whoamiNote={whoamiNote}
                catPath={`/rekrutacje/${handle}`}
                title={splitTitle(job.title)}
              >
                {job.subtitle ? <span className="kr-c">{"// "}{job.subtitle}</span> : null}
              </CareerHero>
              {withScene ? <CareerScene /> : null}
            </div>
            <div className="kr-side">
              <ParamsPanel rows={rows} />
              {withScene ? (
                <CareerSceneScore />
              ) : (
                <div style={{ padding: "0 16px 16px" }} className="kr-cta-wrap">
                  <a href="#aplikuj" className="kr-cta-mobile">
                    $ ./aplikuj — 2 min
                  </a>
                </div>
              )}
            </div>
          </section>

        <main className="kr-main">
          <div className="kr-col">
            {paragraphs.length > 0 ? (
              <section aria-label="O projekcie">
                <Cmd>cat o_projekcie.md</Cmd>
                {paragraphs.map((p, i) => (
                  <p className="kr-para" key={i}>
                    {p}
                  </p>
                ))}
              </section>
            ) : null}
            {/* „Sprawdź się” (etap 7): karty wymagań połączone ze sceną hero. */}
            <FitSection must={must} />
            {/* Kroki także na telefonie (etap 5). */}
            {show.process ? (
              <ProcessSteps
                recruiterFirstName={recruiter.first_name}
                contract={job.params?.contract ?? null}
              />
            ) : null}
          </div>

          <aside id="aplikuj" className="kr-form-box" aria-label="Aplikuj">
            <div className="kr-form-bar">
              <span>
                <span className="kr-r" aria-hidden="true">
                  ${" "}
                </span>
                ./aplikuj.sh
              </span>
              <span className="kr-g">~2 min</span>
            </div>
            <CareerApplyForm
              linkSlug={job.slug}
              variant="job"
              rodoHref={rodoHref}
              preview={formPreview}
              secondaryLink={
                recruiterHref && recruiter.slug
                  ? {
                      href: recruiterHref,
                      label: `$ cd ~/${recruiter.slug}`,
                      note: `// nie ten projekt? zostaw CV u ${genitiveName(recruiter.first_name)}`,
                    }
                  : null
              }
            />
          </aside>
        </main>
        </CareerSceneProvider>
        <ApplyDock heroId={HERO_ID} formId="aplikuj" />

        <CareerFooter rodoHref={rodoHref} hostLabel={visibleUrl} />
      </CareerSubmitGate>
    </CareerThemeScope>
  );
}
