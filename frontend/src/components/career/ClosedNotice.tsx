import type { CareerRecruiterJob } from "@/lib/career/api";
import { genitiveName, jobLocationLabel } from "@/lib/career/format";

import { BrandPage, BrandTitle, brandStyles as s } from "./brand/BrandShell";

/**
 * Rekrutacja zamknięta (albo link odwołany). Odsyła do innych otwartych
 * rekrutacji tej osoby (lista z API — działa także bez stałego linku) i do jej
 * stałego linku, gdy go ma (makieta 5b, etap 5). Bez obu — prośba o kontakt
 * tam, skąd kandydat ma link, zamiast ślepego „szukaj na LinkedInie”.
 * Od 29.10.2026 w barwach marki (szablon rekrutacji), nie jako log terminala.
 */
export function ClosedNotice({
  jobTitle,
  recruiterFirstName,
  recruiterPageHref,
  otherJobs,
  jobHref,
  homeHref,
  rodoHref,
  hostLabel,
}: {
  jobTitle: string;
  recruiterFirstName: string;
  recruiterPageHref: string | null;
  otherJobs: CareerRecruiterJob[];
  jobHref: (slug: string) => string;
  homeHref: string;
  rodoHref: string;
  hostLabel: string;
}) {
  const firstName = recruiterFirstName.trim();
  const who = firstName || "Nasz zespół";
  const hasJobs = otherJobs.length > 0;
  return (
    <BrandPage homeHref={homeHref} rodoHref={rodoHref} hostLabel={hostLabel}>
      <main className={s.main}>
        <div className={`${s.wrap} ${s.message}`}>
          <p className={s.badge}>
            <span className={`${s.badgeDot} ${s.badgeDotOff}`} aria-hidden="true" />
            Rekrutacja zamknięta · {jobTitle}
          </p>
          <BrandTitle text="Ten proces jest zakończony." />
          <p className={s.messageText}>
            {hasJobs
              ? `${who} prowadzi teraz inne rekrutacje — zobacz, czy coś pasuje${recruiterPageHref ? ", albo zostaw CV do bazy." : "."}`
              : recruiterPageHref
                ? `${who} prowadzi kolejne rekrutacje. Zostaw CV — odezwie się, gdy pojawi się podobny projekt.`
                : firstName
                  ? `Odezwij się do ${genitiveName(firstName)} tam, skąd masz ten link — podpowie, co jest teraz otwarte.`
                  : "Odezwij się do osoby, od której masz ten link — podpowie, co jest teraz otwarte."}
          </p>

          {hasJobs ? (
            <section aria-label="Inne otwarte rekrutacje" className={s.otherJobs}>
              <ul className={s.jobRows}>
                {otherJobs.map((job) => {
                  const where = jobLocationLabel(job);
                  return (
                    <li key={job.slug}>
                      <a className={s.jobRow} href={jobHref(job.slug)}>
                        <span className={s.jobRowText}>
                          <span className={s.jobRowTitle}>{job.title}</span>
                          {where ? <span className={s.jobRowMeta}>{where}</span> : null}
                        </span>
                        <span className={s.jobRowGo} aria-hidden="true">
                          Zobacz →
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          <div className={`${s.actions} ${s.messageActions}`}>
            {recruiterPageHref ? (
              <a className={s.btn} href={recruiterPageHref}>
                Zostaw CV u {genitiveName(firstName)}
              </a>
            ) : null}
            <a className={recruiterPageHref ? s.btnOutline : s.btn} href={homeHref}>
              Wszystkie otwarte rekrutacje
            </a>
          </div>
        </div>
      </main>
    </BrandPage>
  );
}
