import type { CareerRecruiterJob } from "@/lib/career/api";
import { genitiveName, jobHandle, jobLocationLabel } from "@/lib/career/format";

import { TerminalChrome } from "./TerminalChrome";

/**
 * Rekrutacja zamknięta (albo link odwołany). Odsyła do innych otwartych
 * rekrutacji tej osoby (lista z API — działa także bez stałego linku) i do jej
 * stałego linku, gdy go ma (makieta 5b, etap 5). Bez obu — prośba o kontakt
 * tam, skąd kandydat ma link, zamiast ślepego „szukaj na LinkedInie”.
 */
export function ClosedNotice({
  jobHandle: closedHandle,
  recruiterFirstName,
  recruiterPageHref,
  recruiterSlug,
  otherJobs,
  jobHref,
}: {
  jobHandle: string;
  recruiterFirstName: string;
  recruiterPageHref: string | null;
  recruiterSlug: string | null;
  otherJobs: CareerRecruiterJob[];
  jobHref: (slug: string) => string;
}) {
  const firstName = recruiterFirstName.trim();
  const who = firstName || "Nasz zespół";
  const hasJobs = otherJobs.length > 0;
  return (
    <>
      <TerminalChrome path={`~/dynaminds/kariera — zsh — ${closedHandle}`} state="closed" />
      <main className="kr-log">
        <span>
          <span className="kr-r" aria-hidden="true">
            ${" "}
          </span>
          ./aplikuj.sh
        </span>
        <span>
          <span className="kr-r">[err]</span> <span className="kr-g">{closedHandle}</span>{" "}
          <span className="kr-c">{"// rekrutacja została zamknięta"}</span>
        </span>
        <h1 className="kr-log-title">
          <span className="kr-title-a">Ten proces jest</span>{" "}
          <span className="kr-title-b">zakończony.</span>
        </h1>
        {hasJobs ? (
          <span className="kr-log-text">
            {who} prowadzi teraz inne rekrutacje — zobacz, czy coś
            pasuje{recruiterPageHref ? ", albo zostaw CV do bazy." : "."}
          </span>
        ) : recruiterPageHref ? (
          <span className="kr-log-text">
            {who} prowadzi kolejne rekrutacje. Zostaw CV — odezwie się, gdy pojawi się
            podobny projekt.
          </span>
        ) : (
          <span className="kr-log-text">
            {firstName
              ? `Odezwij się do ${genitiveName(firstName)} tam, skąd masz ten link — podpowie, co jest teraz otwarte.`
              : "Odezwij się do osoby, od której masz ten link — podpowie, co jest teraz otwarte."}
          </span>
        )}

        {hasJobs ? (
          <section aria-label="Inne otwarte rekrutacje" className="kr-list" style={{ marginTop: 16 }}>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {otherJobs.map((job) => (
                <li key={job.slug}>
                  <a className="kr-row" href={jobHref(job.slug)}>
                    <span>{jobHandle(job)}</span>
                    <span className="kr-g kr-row-loc">{jobLocationLabel(job)}</span>
                    <span className="kr-r kr-row-open">otwórz →</span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {recruiterPageHref ? (
          <a className="kr-btn" href={recruiterPageHref}>
            $ cd ~/{recruiterSlug} — zostaw CV w bazie
          </a>
        ) : null}
      </main>
    </>
  );
}
