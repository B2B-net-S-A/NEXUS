import type { CareerBoardJob, CareerJobResponse } from "@/lib/career/api";
import { boardTagLine } from "@/lib/career/board";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { pluralForm } from "@/lib/career/site";

import { OfferCard } from "./OfferCard";
import { ChapterMark, siteStyles as s } from "./SiteFrame";

/**
 * Zamknięta rekrutacja (plansza OfertaZakonczona): pieczątka „Zamknięta”,
 * otwarte podobne rekrutacje z tablicy i prośba o CV. Bez tablicy (awaria API)
 * zostają inne rekrutacje tej osoby z odpowiedzi `/r/` (`other_jobs`).
 */
export function OfferClosed({
  data,
  others,
  base,
}: {
  data: CareerJobResponse;
  others: CareerBoardJob[];
  base: CareerBase;
}) {
  const homeHref = careerHref(base, { to: "home" });
  const p = data.job.params;
  const line = [p ? boardTagLine({ city: p.city, remote_policy: p.remote_policy }) : "", p?.contract?.trim()]
    .filter(Boolean)
    .join(" · ");
  // Bez tablicy: inne rekrutacje tej osoby (kształt `/r/`), jako proste karty.
  const fallback: CareerBoardJob[] = (data.other_jobs ?? []).map((j) => ({
    slug: j.slug,
    title: j.title,
    subtitle: null,
    city: j.city,
    remote_policy: j.remote_policy,
    category: j.category ?? null,
    theme: j.theme ?? "",
    recruiter_first_name: data.recruiter.first_name,
    must: [],
  }));
  const list = others.length > 0 ? others : fallback.slice(0, 3);
  const n = list.length;
  const chapters = n > 0 ? 3 : 2;
  return (
    <main>
      <section className={`${s.ch} ${s.chRed} ${s.sent1}`}>
        <ChapterMark index={0} count={chapters} name="Oferta" />
        <div className={s.wrap}>
          <p aria-hidden="true" className={`${s.display} ${s.closedWord}`}>
            Zamknięta
          </p>
          <div className={s.sentRow}>
            <div>
              <h1 className={s.lead}>Ta rekrutacja już nie przyjmuje zgłoszeń.</h1>
              <p className={s.body}>
                Ten adres nie prowadzi już do aktywnej oferty.
                {n > 0 ? " Niżej masz otwarte rekrutacje o podobnym profilu." : ""}
              </p>
              <a className={`${s.btn} ${s.btnWhite}`} href={homeHref}>
                Wszystkie rekrutacje →
              </a>
            </div>
            <aside className={s.ticket} aria-label="Zamknięta oferta">
              <h2>{data.job.title}</h2>
              {line ? <p>{line}</p> : null}
              <span className={s.stamp}>Zamknięta</span>
            </aside>
          </div>
        </div>
      </section>

      {n > 0 ? (
        <section className={`${s.ch} ${s.chSnow} ${s.others}`} aria-labelledby="podobne">
          <ChapterMark index={1} count={chapters} name="Podobne" />
          <div className={s.wrap}>
            <div className={s.s3Top} style={{ marginBottom: 24 }}>
              <span aria-hidden="true" className={`${s.display} ${s.bigN}`}>
                {n}
              </span>
              <h2 id="podobne" className={s.lead}>
                <span className={s.srOnly}>{n}</span>{" "}
                {pluralForm(n) === "one" ? "otwarta, podobna rekrutacja" : "otwarte, podobne rekrutacje"}
              </h2>
            </div>
            <div className={s.grid}>
              {list.map((j) => (
                <OfferCard key={j.slug} job={j} href={careerHref(base, { to: "job", slug: j.slug })} />
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className={`${s.ch} ${s.chRed} ${s.band}`} aria-label="Zostaw CV">
        <ChapterMark index={chapters - 1} count={chapters} name="CV" />
        <div className={`${s.wrap} ${s.bandInner}`}>
          <div>
            <h2>Nie widzisz nic dla siebie?</h2>
            <p>Zostaw CV, odezwiemy się, gdy pojawi się projekt w Twojej technologii.</p>
          </div>
          <a className={`${s.btn} ${s.btnWhite}`} href={`${homeHref}#zostaw-cv`}>
            Zostaw CV
          </a>
        </div>
      </section>
    </main>
  );
}
