"use client";

import { useState } from "react";

import { useScene } from "./SceneContext";
import { ItemName, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Plan (PM, Scrum, PMO): harmonogram czterech kroków procesu (klik = opis
 * etapu) i zakres do odhaczenia z pierścieniem gotowości. Celownik za
 * kursorem jak w narzędziu do planowania (tylko mysz).
 */
const BARS: readonly [number, number][] = [
  [0, 25],
  [21, 33],
  [50, 29],
  [75, 25],
];
export const RING_LENGTH = 289;

/** Gotowość w procentach (zaokrąglona) i długość łuku pierścienia. */
export function readiness(count: number, total: number): { pct: number; arc: number } {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return { pct, arc: Math.round((RING_LENGTH * pct) / 100) };
}

export function PlanScene() {
  const { items, steps, isOn, toggle, count, total } = useScene();
  const [step, setStep] = useState(0);
  const { pct, arc } = readiness(count, total);
  const cur = steps[step];
  return (
    <>
      <SceneFrame label="Plan: harmonogram rekrutacji i zakres, który już masz" className="kr-sc-plan">
        <span className="kr-plan-guide" aria-hidden="true" />
        <p className="kr-plan-head" aria-hidden="true">
          <span>HARMONOGRAM · REKRUTACJA</span>
          <span>T1 — T{Math.max(steps.length, 1)}</span>
        </p>
        {steps.length > 0 ? (
          <div className="kr-plan-sec">
            <p className="kr-plan-st">ETAPY — KLIKNIJ, BY ZOBACZYĆ</p>
            {steps.map((g, i) => {
              const [x, w] = BARS[i] ?? [0, 25];
              return (
                <button
                  type="button"
                  key={g.title}
                  className="kr-plan-gb"
                  aria-pressed={i === step}
                  data-state={i === step ? "now" : i < step ? "past" : undefined}
                  onClick={() => setStep(i)}
                >
                  <span className="kr-plan-gt">
                    {String(i + 1).padStart(2, "0")} {g.title}
                  </span>
                  <span className="kr-plan-lane" aria-hidden="true">
                    <span className="kr-plan-bar" style={{ left: `${x}%`, width: `${w}%` }} />
                  </span>
                </button>
              );
            })}
            {cur ? (
              <p className="kr-plan-call" aria-live="polite">
                <span>
                  {String(step + 1).padStart(2, "0")} · {cur.title}
                </span>{" "}
                — {cur.note}
              </p>
            ) : null}
          </div>
        ) : null}
        <div className="kr-plan-sec kr-plan-scope">
          <div className="kr-plan-list">
            <p className="kr-plan-st">ZAKRES — CO JUŻ MASZ</p>
            {items.map((item, i) => {
              const on = isOn(i);
              return (
                <button
                  type="button"
                  key={item.key}
                  className="kr-plan-ck"
                  aria-pressed={on}
                  aria-label={itemAria(item)}
                  data-on={on ? "" : undefined}
                  onClick={() => toggle(i)}
                >
                  <span className="kr-plan-box" aria-hidden="true">
                    {on ? "✓" : ""}
                  </span>
                  <span>
                    <ItemName item={item} />
                    {item.note ? <span className="kr-plan-note"> · {item.note}</span> : null}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="kr-plan-ring" aria-hidden="true">
            <svg width="112" height="112" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="46" className="kr-plan-ring-bg" />
              <circle
                cx="60"
                cy="60"
                r="46"
                className="kr-plan-ring-fg"
                strokeDasharray={`${arc} ${RING_LENGTH}`}
                transform="rotate(-90 60 60)"
              />
            </svg>
            <span className="kr-plan-pct">
              <b>{pct}%</b>
              <span>GOTOWOŚĆ</span>
            </span>
          </div>
        </div>
      </SceneFrame>
      <SceneList
        head={`ZAKRES — gotowość ${pct}%`}
        hint="dotknij tego, co już prowadziłeś"
        mark={(on) => (on ? "[✓]" : "[ ]")}
      />
    </>
  );
}
