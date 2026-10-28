import type { CareerRecruiterResponse } from "@/lib/career/api";
import { categoryChips } from "@/lib/career/board";
import { genitiveName, jobLocationLabel, recruiterLogin } from "@/lib/career/format";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";

import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerFooter } from "./CareerFooter";
import { Cmd, TwoToneTitle } from "./CareerHero";
import { CareerMotion } from "./CareerMotion";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { TerminalChrome } from "./TerminalChrome";

/**
 * Stały link rekrutera (`/<slug>`, etap 6 — makieta 6d): inicjał zamiast
 * zdjęcia, samo imię (bez nazwiska i kontaktu — reguła strony kariery),
 * „O mnie”, plakietki kategorii, rekrutacje osoby z nazwą sceny, formularz
 * „Zostaw CV u <imię>” i odesłanie do tablicy wszystkich rekrutacji.
 *
 * Komponent prezentacyjny — dane przychodzą z serwera (strona) albo z mocków
 * (harness `/preview/kariera`). Awaria API nie dociera tutaj: strona rzuca
 * błąd (`error.tsx`), więc pusta lista znaczy „brak otwartych rekrutacji”.
 */
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
  const chromePath = `~/b2bnetwork/kariera — zsh — ${recruiter.slug}`;
  const login = recruiterLogin(recruiter.first_name);
  const handle = login.split("@")[0];
  const initial = recruiter.first_name.trim().charAt(0).toLocaleUpperCase("pl-PL") || "B";
  const about = recruiter.about?.trim() || null;
  const chips = categoryChips(jobs);
  const atName = genitiveName(recruiter.first_name);

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
      <CareerMotion />
      <main className="kr-main kr-main-general">
        <div className="kr-col">
          <div className="kr-hero kr-rec-hero">
            <div className="kr-rec-id">
              <span className="kr-rec-initial" aria-hidden="true">
                {initial}
              </span>
              <span className="kr-rec-whoami">
                <span>
                  <span className="kr-r" aria-hidden="true">
                    ${" "}
                  </span>
                  <span data-kr-scramble="">whoami</span>
                </span>
                <span className="kr-w">{login}</span>
              </span>
            </div>
            <TwoToneTitle first={`${recruiter.first_name}.`} second="Rekrutuję w IT." />
            {about ? (
              <p className="kr-rec-about">{about}</p>
            ) : (
              <span className="kr-g kr-rec-note">
                {"// zostaw CV raz — odezwę się, gdy pojawi się projekt dla Ciebie"}
              </span>
            )}
            {chips.length > 0 ? (
              <ul className="kr-rec-chips" aria-label="Rekrutuję w obszarach">
                {chips.map((chip) => (
                  <li key={chip} className="kr-rec-chip">
                    {chip}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <section aria-label="Otwarte rekrutacje">
            <Cmd>ls ~/{handle}/rekrutacje --open</Cmd>
            {jobs.length > 0 ? (
              <ul className="kr-rec-jobs">
                {jobs.map((job) => {
                  const where = jobLocationLabel(job);
                  return (
                    <li key={job.slug}>
                      <a
                        className="kr-rec-job"
                        href={careerHref(base, { to: "job", slug: job.slug })}
                      >
                        <span className="kr-rec-job-text">
                          <span className="kr-rec-job-title">{job.title}</span>
                          {where ? (
                            <span className="kr-g kr-rec-job-meta">[{where}]</span>
                          ) : null}
                        </span>
                        <span className="kr-r kr-rec-job-open" aria-hidden="true">
                          ./aplikuj →
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="kr-g kr-rec-note">
                {"// teraz nie mam otwartych rekrutacji na tej stronie — zostaw CV, odezwę się z pierwszym pasującym projektem"}
              </p>
            )}
          </section>
        </div>

        <aside id="aplikuj" tabIndex={-1} className="kr-form-box" aria-label={`Zostaw CV u ${atName}`}>
          <div className="kr-form-bar">
            <span>
              <span className="kr-r" aria-hidden="true">
                ${" "}
              </span>
              ./zostaw-cv --do {handle}
            </span>
            <span className="kr-g">~2 min</span>
          </div>
          <div className="kr-rec-form-head">
            <h2 className="kr-rec-form-title">
              {jobs.length > 0 ? "Nic nie pasuje? " : ""}Zostaw CV u {atName}.
            </h2>
            <p className="kr-g kr-rec-form-note">
              Odezwę się, gdy pojawi się projekt w Twojej technologii.
            </p>
          </div>
          <CareerApplyForm
            linkSlug={recruiter.slug}
            variant="general"
            rodoHref={rodoHref}
            preview={formPreview}
          />
        </aside>
      </main>
      <nav className="kr-rec-all" aria-label="Wszystkie rekrutacje">
        <a href={careerHref(base, { to: "home" })}>cd ~/rekrutacje</a>
        <span className="kr-g"> — wszystkie otwarte rekrutacje B2B Network</span>
      </nav>
      <CareerFooter
        rodoHref={rodoHref}
        hostLabel={careerVisibleUrl(host, base, { to: "recruiter", slug: recruiter.slug })}
      />
    </CareerSubmitGate>
  );
}
