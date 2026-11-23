import type { CareerBoardJob } from "@/lib/career/api";
import { boardTagLine } from "@/lib/career/board";

import s from "./site.module.css";

/** Najwięcej technologii na karcie (makieta: cztery). */
export const CARD_TAGS = 4;

/**
 * Karta oferty jak na planszy KarieraA: tytuł, zdanie o projekcie,
 * technologie, miasto · tryb, rekruter i „Zobacz” (bez kategorii, 23.11.2026). Cała karta
 * prowadzi na stronę oferty (`::after` linku).
 */
export function OfferCard({ job, href }: { job: CareerBoardJob; href: string }) {
  const tags = (job.must ?? []).filter((t) => t.trim()).slice(0, CARD_TAGS);
  const place = boardTagLine(job);
  return (
    <article className={s.offer}>
      <div className={s.offerHead}>
        <h3>{job.title}</h3>
        {job.subtitle ? <p className={s.snippet}>{job.subtitle}</p> : null}
        {tags.length > 0 ? (
          <ul className={`${s.tags} ${s.mono}`} aria-label="Technologie">
            {tags.map((t, i) => (
              <li key={`${t}-${i}`}>{t}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className={s.meta}>
        <span className={s.place}>{place}</span>
        <span>{job.recruiter_first_name ? `Rekruter: ${job.recruiter_first_name}` : null}</span>
        <a href={href} className={s.go} aria-label={`Zobacz: ${job.title}`}>
          Zobacz <span aria-hidden="true">→</span>
        </a>
      </div>
    </article>
  );
}
