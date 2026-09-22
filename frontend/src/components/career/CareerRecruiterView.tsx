import type { CareerRecruiterResponse } from "@/lib/career/api";
import { jobHandle, recruiterLogin, remoteLabel } from "@/lib/career/format";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";

import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerFooter } from "./CareerFooter";
import { CareerHero, Cmd } from "./CareerHero";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { TerminalChrome } from "./TerminalChrome";

function locationLabel(job: CareerRecruiterResponse["jobs"][number]): string {
  const city = job.city?.trim().toLocaleLowerCase("pl-PL");
  const mode = remoteLabel(job.remote_policy);
  if (job.remote_policy === "remote") return mode ?? "";
  return [city, mode].filter(Boolean).join(" · ");
}

/** Stały link rekrutera (`/<slug>`): „zostaw CV raz" + lista jego rekrutacji. */
export function CareerRecruiterView({
  data,
  base,
  host,
  formPreview,
}: {
  data: CareerRecruiterResponse;
  base: CareerBase;
  host: string;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const { recruiter, jobs } = data;
  const rodoHref = careerHref(base, { to: "rodo" });
  const chromePath = `~/dynaminds/kariera/${recruiter.slug} — zsh`;

  return (
    <CareerSubmitGate
      thanks={{
        variant: "general",
        recruiterFirstName: recruiter.first_name,
        chromePath,
        recruiterPageHref: null,
      }}
    >
      <TerminalChrome path={chromePath} />
      <main className="kr-main kr-main-general">
        <div className="kr-col">
          <CareerHero
            login={recruiterLogin(recruiter.first_name)}
            whoamiNote="rekrutacje IT"
            catPath="witaj.txt"
            title={{ first: "Szukasz kolejnego", second: "projektu IT?" }}
          >
            <span className="kr-c">
              {"// zostaw CV raz — odezwę się, gdy pojawi się projekt dla Ciebie"}
            </span>
          </CareerHero>

          <section aria-label="Jak to działa">
            <Cmd>./jak-to-dziala</Cmd>
            <ol className="kr-checks" style={{ listStyle: "none", margin: 0, padding: 0 }}>
              <li className="kr-ok">
                <span className="kr-r">[01]</span>
                <span className="kr-g">
                  zostawiasz_cv <span className="kr-c">{"// dwie minuty, raz"}</span>
                </span>
              </li>
              <li className="kr-ok">
                <span className="kr-r">[02]</span>
                <span className="kr-g">
                  dopasowujemy <span className="kr-c">{"// do nowych i trwających projektów"}</span>
                </span>
              </li>
              <li className="kr-ok">
                <span className="kr-r">[03]</span>
                <span className="kr-g">
                  dostajesz_propozycję{" "}
                  <span className="kr-c">{"// Ty decydujesz, czy wchodzisz"}</span>
                </span>
              </li>
            </ol>
          </section>

          {jobs.length > 0 ? (
            <section aria-label="Otwarte rekrutacje">
              <Cmd>ls -l ~/{recruiter.slug}/rekrutacje</Cmd>
              <div className="kr-list">
                <div className="kr-row kr-row-head" aria-hidden="true">
                  <span>STANOWISKO</span>
                  <span className="kr-row-loc">LOKALIZACJA</span>
                  <span />
                </div>
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  {jobs.map((job) => (
                    <li key={job.slug}>
                      <a className="kr-row" href={careerHref(base, { to: "job", slug: job.slug })}>
                        <span>{jobHandle(job)}</span>
                        <span className="kr-g kr-row-loc">{locationLabel(job)}</span>
                        <span className="kr-r kr-row-open">otwórz →</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          ) : null}
        </div>

        <aside id="aplikuj" className="kr-form-box" aria-label="Dołącz do bazy">
          <div className="kr-form-bar">
            <span>
              <span className="kr-r" aria-hidden="true">
                ${" "}
              </span>
              ./dolacz-do-bazy.sh
            </span>
            <span className="kr-g">~2 min</span>
          </div>
          <CareerApplyForm
            linkSlug={recruiter.slug}
            variant="general"
            rodoHref={rodoHref}
            preview={formPreview}
          />
        </aside>
      </main>
      <CareerFooter
        rodoHref={rodoHref}
        hostLabel={careerVisibleUrl(host, base, { to: "recruiter", slug: recruiter.slug })}
      />
    </CareerSubmitGate>
  );
}
