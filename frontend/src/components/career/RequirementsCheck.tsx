import { requirementHandle } from "@/lib/career/format";

import { Cmd } from "./CareerHero";

/** `$ check --wymagania`: [ok] dla must-have, [--] dla mile widzianych. */
export function RequirementsCheck({
  must,
  nice,
}: {
  must: { name: string; note: string | null }[];
  nice: string[];
}) {
  if (must.length === 0 && nice.length === 0) return null;
  return (
    <section aria-label="Wymagania">
      <Cmd>check --wymagania</Cmd>
      <ul className="kr-checks" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {must.map((item) => (
          <li className="kr-ok" key={item.name}>
            <span className="kr-r">
              [ok]<span className="kr-sr"> wymagane:</span>
            </span>
            <span className="kr-g">
              {requirementHandle(item.name)}
              {item.note ? <span className="kr-c"> {"// "}{item.note}</span> : null}
            </span>
          </li>
        ))}
        {nice.length > 0 ? (
          <li className="kr-ok">
            <span className="kr-dim">
              [--]<span className="kr-sr"> mile widziane:</span>
            </span>
            <span className="kr-g">
              {nice.map((n) => n.toLocaleLowerCase("pl-PL")).join(" · ")}
              <span className="kr-c"> {"// mile widziane"}</span>
            </span>
          </li>
        ) : null}
      </ul>
    </section>
  );
}
