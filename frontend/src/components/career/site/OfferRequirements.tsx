import { highlightSkill } from "@/lib/career/site";

import { siteStyles as s } from "./SiteFrame";

/**
 * Wymagania w prawej kolumnie nagłówka oferty, pod szybką aplikacją (decyzja
 * Artura 23.11.2026, wariant P1): zwykła lista z pogrubioną technologią,
 * bez pól do zaznaczania — zastąpiła „Co już masz?”.
 */
export interface OfferRequirementsProps {
  must: { name: string; note: string | null }[];
  nice: string[];
  /** Krótkie nazwy umiejętności z tablicy — do pogrubienia w zdaniach. */
  skills: readonly string[];
}

function Sentence({ text, skills }: { text: string; skills: readonly string[] }) {
  const h = highlightSkill(text, skills);
  return (
    <>
      {h.before}
      {h.key ? <b>{h.key}</b> : null}
      {h.after}
    </>
  );
}

export function OfferRequirements({ must, nice, skills }: OfferRequirementsProps) {
  return (
    <aside className={s.sideCard} aria-label="Wymagania">
      {must.length > 0 ? (
        <>
          <h2 className={s.sideTitle}>Wymagania</h2>
          <ul className={s.sideList}>
            {must.map((m, i) => (
              <li key={`m${i}`}>
                <Sentence text={m.name} skills={skills} />
                {m.note ? <small> · {m.note}</small> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {nice.length > 0 ? (
        <>
          {must.length > 0 ? <h3 className={s.sideSub}>Mile widziane</h3> : <h2 className={s.sideTitle}>Mile widziane</h2>}
          <ul className={`${s.sideList} ${s.sideNice}`}>
            {nice.map((n, i) => (
              <li key={`n${i}`}>
                <Sentence text={n} skills={skills} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className={s.sideNote}>Nie musisz mieć wszystkiego.</p>
    </aside>
  );
}
