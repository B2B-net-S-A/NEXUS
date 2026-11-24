import type { CareerBoardJob, CareerRecruiterResponse } from "@/lib/career/api";
import { genitiveName } from "@/lib/career/format";
import { careerHref, careerVisibleUrl, type CareerBase } from "@/lib/career/host";
import { boardCardFor, wordEm } from "@/lib/career/site";

import { OfferApply, type OfferApplyProps } from "./OfferApply";
import { OfferCard } from "./OfferCard";
import { SentGate } from "./SentGate";
import { ChapterMark, SiteFrame, Who, siteStyles as s } from "./SiteFrame";

const APPLY_ID = "aplikuj";

/**
 * Stały link rekrutera (`/<slug>`) w szablonie nowej strony B2B Network, jak
 * lista i oferta (24.11.2026, wcześniej rama Grafit): inicjał i samo imię
 * (bez nazwiska i kontaktu — reguła strony kariery), „O mnie”, rekrutacje
 * osoby jako karty ofert (bez kategorii, decyzja Artura 23.11.2026) i „Zostaw
 * CV u <imię>” z jedną, obowiązkową zgodą na przyszłe procesy.
 *
 * Tablica (`board`) daje kartom tylko podtytuł i technologie; bez niej karty
 * mają tytuł i miejsce. Awaria API rekrutera nie dociera tutaj: strona rzuca
 * błąd (`error.tsx`), więc pusta lista znaczy „brak otwartych rekrutacji”.
 */
export function RecruiterPage({
  data,
  board,
  base,
  host,
  formPreview,
}: {
  data: CareerRecruiterResponse;
  board: readonly CareerBoardJob[] | null;
  base: CareerBase;
  host: string;
  formPreview?: OfferApplyProps["preview"];
}) {
  const { recruiter } = data;
  const name = recruiter.first_name.trim();
  const homeHref = careerHref(base, { to: "home" });
  const rodoHref = careerHref(base, { to: "rodo" });
  const about = recruiter.about?.trim() || "Zostaw CV raz — odezwę się, gdy pojawi się projekt dla Ciebie.";
  const atName = genitiveName(name);
  // Kształt karty tablicy: z tablicy podtytuł i technologie, imię rekrutera zbędne na jego stronie.
  const jobs: CareerBoardJob[] = data.jobs.map((j) => {
    const card = boardCardFor(board ?? [], [j.slug]);
    return {
      slug: j.slug,
      title: j.title,
      subtitle: card?.subtitle ?? null,
      city: j.city,
      remote_policy: j.remote_policy,
      category: j.category ?? null,
      theme: j.theme ?? "",
      recruiter_first_name: "",
      must: card?.must ?? [],
    };
  });

  return (
    <SiteFrame
      homeHref={homeHref}
      rodoHref={rodoHref}
      pageLabel={careerVisibleUrl(host, base, { to: "recruiter", slug: recruiter.slug })}
    >
      <SentGate sent={{ variant: "general", recruiterFirstName: name, others: jobs.slice(0, 3), base }}>
        <main>
          <section className={`${s.ch} ${s.chRed} ${s.rec1}`}>
            <ChapterMark index={0} count={3} name="Rekruter" />
            <div className={s.wrap}>
              <Who name="B2Bnetwork" initialOf={name || "B"} note="Zespół rekrutacji IT" white />
              <h1>
                <span
                  className={`${s.display} ${s.recName}`}
                  style={{ "--em": wordEm(`${name}.`) } as React.CSSProperties}
                >
                  {name}.
                </span>{" "}
                <span className={`${s.lead} ${s.recLead}`}>Rekrutuję w IT.</span>
              </h1>
              <p className={`${s.body} ${s.recAbout}`}>{about}</p>
              <div className={s.actions}>
                <a className={`${s.btn} ${s.btnWhite}`} href={`#${APPLY_ID}`}>
                  Zostaw CV
                </a>
              </div>
            </div>
          </section>

          <section className={`${s.ch} ${s.chSnow} ${s.others}`} aria-labelledby="moje-rekrutacje">
            <ChapterMark index={1} count={3} name="Rekrutacje" />
            <div className={s.wrap}>
              <div className={s.othersTop}>
                <h2 id="moje-rekrutacje" className={s.h2}>
                  Moje otwarte rekrutacje
                </h2>
                <a className={s.ulink} href={homeHref}>
                  Wszystkie otwarte rekrutacje B2Bnetwork →
                </a>
              </div>
              {jobs.length > 0 ? (
                <div className={s.grid}>
                  {jobs.map((j) => (
                    <OfferCard key={j.slug} job={j} href={careerHref(base, { to: "job", slug: j.slug })} />
                  ))}
                </div>
              ) : (
                <div className={s.empty} role="status">
                  <p>
                    Teraz nie mam otwartych rekrutacji na tej stronie — zostaw CV, odezwę się z pierwszym
                    pasującym projektem.
                  </p>
                </div>
              )}
            </div>
          </section>

          <section
            id={APPLY_ID}
            tabIndex={-1}
            className={`${s.ch} ${s.chInk} ${s.cvSection}`}
            aria-label={`Zostaw CV u ${atName}`}
          >
            <ChapterMark index={2} count={3} name="CV" />
            <div className={s.wrap}>
              <OfferApply
                linkSlug={recruiter.slug}
                variant="general"
                rodoHref={rodoHref}
                recruiterFirstName={name}
                preview={formPreview}
                intro={
                  <>
                    <p aria-hidden="true" className={`${s.display} ${s.cvBig}`}>
                      CV
                    </p>
                    <h2 className={s.lead}>
                      {jobs.length > 0 ? "Nic nie pasuje? " : ""}Zostaw CV u {atName}.
                    </h2>
                    <p className={s.body}>
                      Odezwę się, gdy pojawi się projekt w Twojej technologii. To zgłoszenie nie dotyczy
                      konkretnej oferty, więc proszę tylko o zgodę na przyszłe rekrutacje. Dane
                      przechowujemy do czasu wycofania zgody, nie dłużej niż 3 lata.
                    </p>
                  </>
                }
              />
            </div>
          </section>
        </main>
      </SentGate>
    </SiteFrame>
  );
}
