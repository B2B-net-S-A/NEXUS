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

import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerFooter } from "./CareerFooter";
import { CareerHero, Cmd } from "./CareerHero";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { ClosedNotice } from "./ClosedNotice";
import { ManifestoBlock } from "./ManifestoBlock";
import { ParamsPanel } from "./ParamsPanel";
import { ProcessSteps } from "./ProcessSteps";
import { RequirementsCheck } from "./RequirementsCheck";
import { TerminalChrome } from "./TerminalChrome";

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
      <>
        <ClosedNotice
          jobHandle={handle}
          recruiterFirstName={recruiter.first_name}
          recruiterPageHref={recruiterHref}
          recruiterSlug={recruiter.slug}
        />
        <CareerFooter rodoHref={rodoHref} hostLabel={visibleUrl} />
      </>
    );
  }

  const show = job.show ?? { must: true, nice: true, params: true, process: true };
  const rows = show.params ? paramRows(job.params) : [];
  const paragraphs = aboutParagraphs(job.about);
  const chromePath = `~/dynaminds/kariera — zsh — ${handle}`;

  return (
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
      <TerminalChrome path={chromePath} />
      <section className="kr-top" aria-label="Rekrutacja">
        <CareerHero
          login={recruiterLogin(recruiter.first_name)}
          whoamiNote="zaprasza Cię do rekrutacji"
          catPath={`/rekrutacje/${handle}`}
          title={splitTitle(job.title)}
        >
          {job.subtitle ? <span className="kr-c">{"// "}{job.subtitle}</span> : null}
        </CareerHero>
        <div className="kr-side">
          <ParamsPanel rows={rows} />
          <div style={{ padding: "0 16px 16px" }} className="kr-cta-wrap">
            <a href="#aplikuj" className="kr-cta-mobile">
              $ ./aplikuj — 2 min
            </a>
          </div>
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
          <RequirementsCheck
            must={show.must ? job.must : []}
            nice={show.nice ? job.nice : []}
          />
          {show.process ? (
            <div className="kr-desktop-only">
              <ProcessSteps
                recruiterFirstName={recruiter.first_name}
                contract={job.params?.contract ?? null}
              />
            </div>
          ) : null}
          <div className="kr-desktop-only">
            <ManifestoBlock />
          </div>
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

      <CareerFooter rodoHref={rodoHref} hostLabel={visibleUrl} />
    </CareerSubmitGate>
  );
}
