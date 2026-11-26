import { highlightSkill } from "@/lib/career/site";

import g from "./glass.module.css";

/**
 * Wymagania jako biała karta pod „O projekcie” (język A, makieta O-oferta,
 * 26.11.2026; wcześniej prawa kolumna nagłówka, wariant P1 z 24.11.2026):
 * zwykła lista z pogrubioną technologią, bez pól do zaznaczania.
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
    <aside className={g.reqCard} aria-label="Wymagania">
      {must.length > 0 ? (
        <>
          <h3>Wymagania</h3>
          <ul className={g.reqList}>
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
          {must.length > 0 ? <h4>Mile widziane</h4> : <h3>Mile widziane</h3>}
          <ul className={`${g.reqList} ${g.reqNice}`}>
            {nice.map((n, i) => (
              <li key={`n${i}`}>
                <Sentence text={n} skills={skills} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className={g.reqNote}>Nie musisz mieć wszystkiego.</p>
    </aside>
  );
}
