import type { CareerRecruiterResponse } from "@/lib/career/api";
import { categoryChips } from "@/lib/career/board";
import { genitiveName, jobLocationLabel } from "@/lib/career/format";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";

import { BrandArc, BrandPage, brandStyles as s } from "./brand/BrandShell";
import { CareerApplyForm, type CareerApplyFormProps } from "./CareerApplyForm";
import { CareerSubmitGate } from "./CareerSubmitGate";
import { CareerThemeScope } from "./CareerThemeScope";
import { DEFAULT_CAREER_THEME, type CareerThemeId } from "./themes";

const APPLY_ID = "aplikuj";

/**
 * Stały link rekrutera (`/<slug>`, etap 6 — makieta 6d): inicjał zamiast
 * zdjęcia, samo imię (bez nazwiska i kontaktu — reguła strony kariery),
 * „O mnie”, plakietki kategorii, rekrutacje osoby, formularz „Zostaw CV
 * u <imię>” i odesłanie do tablicy wszystkich rekrutacji. Od 29.10.2026
 * w barwach marki B2B Network jak szablony ogłoszeń, nie w oknie terminala.
 *
 * Komponent prezentacyjny — dane przychodzą z serwera (strona) albo z mocków
 * (harness `/preview/kariera`). Awaria API nie dociera tutaj: strona rzuca
 * błąd (`error.tsx`), więc pusta lista znaczy „brak otwartych rekrutacji”.
 */
export function CareerRecruiterView({
  data,
  base,
  host,
  theme = DEFAULT_CAREER_THEME,
  formPreview,
}: {
  data: CareerRecruiterResponse;
  base: CareerBase;
  host: string;
  theme?: CareerThemeId;
  formPreview?: CareerApplyFormProps["preview"];
}) {
  const { recruiter, jobs } = data;
  const rodoHref = careerHref(base, { to: "rodo" });
  const homeHref = careerHref(base, { to: "home" });
  const hostLabel = careerVisibleUrl(host, base, { to: "recruiter", slug: recruiter.slug });
  const initial = recruiter.first_name.trim().charAt(0).toLocaleUpperCase("pl-PL") || "B";
  const about = recruiter.about?.trim() || null;
  const chips = categoryChips(jobs);
  const atName = genitiveName(recruiter.first_name);

  return (
    <CareerThemeScope theme={theme}>
      <CareerSubmitGate
        thanks={{
          variant: "general",
          recruiterFirstName: recruiter.first_name,
          homeHref,
          rodoHref,
          hostLabel,
          recruiterPageHref: null,
        }}
      >
        <BrandPage
          homeHref={homeHref}
          cta={{ href: `#${APPLY_ID}`, label: "Zostaw CV" }}
          rodoHref={rodoHref}
          hostLabel={hostLabel}
        >
          <main className={s.main}>
            <div className={s.hero}>
              <div className={s.glow} aria-hidden="true" />
              <BrandArc />
              <div className={`${s.wrap} ${s.heroInner} ${s.recGrid}`}>
                <div>
                  <div className={s.recId}>
                    <span className={s.initial} aria-hidden="true">
                      {initial}
                    </span>
                    <span className={s.recRole}>
                      <b>B2B Network</b>
                      Zespół rekrutacji IT
                    </span>
                  </div>
                  <h1 className={s.title}>
                    {recruiter.first_name}. <span className={s.titleTail}>Rekrutuję w IT.</span>
                  </h1>
                  {about ? (
                    <p className={s.about}>{about}</p>
                  ) : (
                    <p className={s.about}>
                      Zostaw CV raz — odezwę się, gdy pojawi się projekt dla Ciebie.
                    </p>
                  )}
                  {chips.length > 0 ? (
                    <ul className={`${s.chips} ${s.recChips}`} aria-label="Rekrutuję w obszarach">
                      {chips.map((chip) => (
                        <li key={chip} className={s.tag}>
                          {chip}
                        </li>
                      ))}
                    </ul>
                  ) : null}

                  <section className={s.recJobs} aria-label="Otwarte rekrutacje">
                    <h2 className={s.sectionTitle}>Moje otwarte rekrutacje</h2>
                    {jobs.length > 0 ? (
                      <ul className={s.jobRows}>
                        {jobs.map((job) => {
                          const where = jobLocationLabel(job);
                          return (
                            <li key={job.slug}>
                              <a className={s.jobRow} href={careerHref(base, { to: "job", slug: job.slug })}>
                                <span className={s.jobRowText}>
                                  <span className={s.jobRowTitle}>{job.title}</span>
                                  {where ? <span className={s.jobRowMeta}>{where}</span> : null}
                                </span>
                                <span className={s.jobRowGo} aria-hidden="true">
                                  Aplikuj →
                                </span>
                              </a>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <p className={s.note}>
                        Teraz nie mam otwartych rekrutacji na tej stronie — zostaw CV, odezwę się
                        z pierwszym pasującym projektem.
                      </p>
                    )}
                  </section>
                </div>

                <aside
                  id={APPLY_ID}
                  tabIndex={-1}
                  className={`${s.apply} ${s.recForm}`}
                  aria-label={`Zostaw CV u ${atName}`}
                >
                  <h2 className={s.applyTitle}>
                    {jobs.length > 0 ? "Nic nie pasuje? " : ""}Zostaw CV u {atName}.
                  </h2>
                  <p className={s.note}>Odezwę się, gdy pojawi się projekt w Twojej technologii.</p>
                  <div className={`${s.form}`} style={{ marginTop: 24 }}>
                    <CareerApplyForm
                      linkSlug={recruiter.slug}
                      variant="general"
                      rodoHref={rodoHref}
                      preview={formPreview}
                      tone="plain"
                    />
                  </div>
                </aside>
              </div>
            </div>
            <nav className={`${s.wrap} ${s.recAll}`} aria-label="Wszystkie rekrutacje">
              <a className={s.btnOutline} href={homeHref}>
                Wszystkie otwarte rekrutacje B2B Network →
              </a>
            </nav>
          </main>
        </BrandPage>
      </CareerSubmitGate>
    </CareerThemeScope>
  );
}
