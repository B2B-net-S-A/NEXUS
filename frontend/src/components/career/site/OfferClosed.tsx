import type { CareerBoardJob, CareerJobResponse } from "@/lib/career/api";
import { boardTagLine } from "@/lib/career/board";
import { careerHref, type CareerBase } from "@/lib/career/host";
import { offerMapMode } from "@/lib/career/polandMap";
import { jobCities, pluralForm } from "@/lib/career/site";

import g from "./glass.module.css";
import { ClosedMap } from "./GlassMap";
import { OfferCard } from "./OfferCard";
import { ChapterMark, siteStyles as s } from "./SiteFrame";

/**
 * Zamknięta rekrutacja (język A, makieta O-zamknieta, 26.11.2026): tytuł
 * z plakietką, przerywany obrys mapy z miastem, otwarte podobne rekrutacje
 * z tablicy („Wciąż szukają”) i prośba o CV. Bez tablicy (awaria API)
 * zostają inne rekrutacje tej osoby z odpowiedzi `/r/` (`other_jobs`).
 */
export function OfferClosed({
  data,
  others,
  base,
  total = null,
}: {
  data: CareerJobResponse;
  others: CareerBoardJob[];
  base: CareerBase;
  /** Liczba otwartych ofert z tablicy („Wszystkie oferty (101)”), `null` bez tablicy. */
  total?: number | null;
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
  const mode = offerMapMode("closed", p ?? null, (city) => jobCities({ city }));
  const cities = mode.kind === "closed" ? mode.cities : [];
  return (
    <main>
      <section className={`${s.ch} ${s.chRed} ${g.closedA}`} aria-label="Rekrutacja zamknięta">
        <ChapterMark index={0} count={1} name="Oferta" />
        <div className={`${s.wrap} ${g.closedGrid}`}>
          <div className={g.sentText}>
            <span className={g.badge}>Rekrutacja zamknięta</span>
            <h1 className={g.sentTitle}>{data.job.title}</h1>
            <p className={g.sentLead}>
              Ta rekrutacja już nie przyjmuje zgłoszeń.
              {n > 0 ? ` Obok ${pluralForm(n) === "one" ? "jest otwarta rekrutacja" : "są otwarte rekrutacje"} o podobnym profilu.` : ""}
              {" "}Możesz też zostawić CV na następny projekt.
            </p>
            {line ? <p className={g.closedLine}>{line}</p> : null}
            <div className={g.btnRow}>
              <a className={`${s.btn} ${s.btnWhite}`} href={`${homeHref}#zostaw-cv`}>
                Zostaw CV na następny projekt
              </a>
              <a className={g.btnGlass} href={homeHref}>
                {`Wszystkie oferty${total ? ` (${total})` : ""}`}
              </a>
            </div>
            <ClosedMap uid="zamknieta" cities={cities} className={g.closedMap} />
          </div>
          {n > 0 ? (
            <div className={g.othersCol} aria-labelledby="podobne">
              <h2 id="podobne">Wciąż szukają</h2>
              {list.map((j) => (
                <OfferCard key={j.slug} job={j} href={careerHref(base, { to: "job", slug: j.slug })} />
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
