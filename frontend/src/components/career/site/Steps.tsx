import { capitalize } from "@/lib/career/site";
import type { ProcessStep } from "../requirementItems";

import { siteStyles as s } from "./SiteFrame";

/**
 * Cztery kroki procesu (`processSteps`): pierwszy na białej karcie z inicjałem
 * rekrutera, reszta na graficie. Ten sam układ na ofercie i po wysłaniu.
 */
export function StepsList({
  steps,
  recruiterFirstName,
}: {
  steps: ProcessStep[];
  recruiterFirstName: string;
}) {
  const initial = recruiterFirstName.trim().charAt(0).toLocaleUpperCase("pl-PL");
  return (
    <ol className={s.steps}>
      {steps.map((st, i) => (
        <li key={st.title} className={`${s.st} ${i === 0 ? s.stLit : ""}`}>
          {i === 0 && initial ? (
            <span aria-hidden="true" className={`${s.av} ${s.stAv}`}>
              {initial}
            </span>
          ) : null}
          <span className={s.n} aria-hidden="true">
            {String(i + 1).padStart(2, "0")}
          </span>
          <div>
            <b className={s.t}>{capitalize(st.title)}</b>
            <span className={s.d}>{capitalize(st.note)}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
