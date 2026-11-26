import { capitalize } from "@/lib/career/site";
import type { ProcessStep } from "../requirementItems";

import g from "./glass.module.css";

/** Odstęp stopni i ich przyrost w jednostkach rysunku (makieta O-oferta: 270 i 40). */
const STEP_DX = 270;
const STEP_RISE = 40;

/**
 * Kroki procesu (`processSteps`) jako szklane stopnie rosnące w prawo
 * (język A, makieta O-oferta). Pierwszy stopień świeci, nad nimi przerywana
 * ścieżka; pod rysunkiem nazwy kroków z danych. Rysunek jest ozdobą —
 * treść czyta lista.
 */
export function StairsSteps({ steps, uid }: { steps: ProcessStep[]; uid: string }) {
  const id = uid.replace(/[^a-zA-Z0-9_-]/g, "");
  const n = steps.length;
  const rise = n > 1 ? Math.min(STEP_RISE, 160 / (n - 1)) : 0;
  const width = 75 + STEP_DX * (n - 1) + 150;
  const tops = steps.map((_, i) => 246 - rise * i);
  const path = steps
    .map((_, i) => {
      const x = 140 + STEP_DX * i;
      const y = tops[i] - 34;
      if (i === 0) return `M${x},${y}`;
      const px = 140 + STEP_DX * (i - 1);
      return `C${px + 120},${y + 22} ${x - 110},${y + 4} ${x},${y}`;
    })
    .join(" ");
  return (
    <div className={g.stairs}>
      <svg viewBox={`0 30 ${width} 290`} aria-hidden="true" className={g.stairsSvg}>
        <defs>
          <linearGradient id={`${id}F`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.5" />
            <stop offset="1" stopColor="#FFFFFF" stopOpacity="0.08" />
          </linearGradient>
          <linearGradient id={`${id}H`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFF4F0" />
            <stop offset="1" stopColor="#FFD6C9" stopOpacity="0.6" />
          </linearGradient>
        </defs>
        {n > 1 ? <path d={path} fill="none" stroke="#FFFFFF" strokeOpacity="0.8" strokeWidth="1.6" className={g.flow} /> : null}
        <g stroke="#FFFFFF" strokeOpacity="0.8" strokeWidth="1.2" strokeLinejoin="round">
          {steps.map((st, i) => {
            const x = 75 + STEP_DX * i;
            const t = tops[i];
            const on = i === 0;
            return (
              <g key={st.title}>
                <polygon
                  points={`${x},${244} ${x + 30},296 ${x + 30},${t} ${x},${t - 52}`}
                  fill={on ? "#FFD6C9" : "#FFFFFF"}
                  fillOpacity={on ? 0.6 : 0.18}
                />
                <polygon points={`${x + 30},296 ${x + 130},296 ${x + 130},${t} ${x + 30},${t}`} fill={`url(#${id}${on ? "H" : "F"})`} />
                <polygon
                  points={`${x},${t - 52} ${x + 100},${t - 52} ${x + 130},${t} ${x + 30},${t}`}
                  fill="#FFFFFF"
                  fillOpacity={on ? 1 : 0.7}
                />
                <text x={x + 45} y="282" className={`${g.stairNum} ${on ? g.stairNumOn : ""}`}>
                  {String(i + 1).padStart(2, "0")}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <ol className={g.stairList}>
        {steps.map((st, i) => (
          <li key={st.title}>
            <span className={g.stairIdx} aria-hidden="true">
              {String(i + 1).padStart(2, "0")}
            </span>
            <strong>{capitalize(st.title)}</strong>
            <span>{capitalize(st.note)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
