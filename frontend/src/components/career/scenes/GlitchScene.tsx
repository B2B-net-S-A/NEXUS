"use client";

import { useState } from "react";

import { GLITCH_BUG_COUNT, useScene } from "./SceneContext";
import { GlitchBug, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Glitch (tester automatyzujący): runner testów — wymaganie, które zdasz,
 * dostaje PASS — i trzy celowe błędy na stronie do znalezienia (w hero, w
 * nagłówku runnera i w panelu wyniku). Błędy nie liczą się do „x z 5”.
 */
export function huntMessage(found: number): string {
  if (found === 0) return "wskazówka: patrz na to, co drga";
  if (found >= GLITCH_BUG_COUNT) return "wszystkie 3 znalezione. Dokładnie tego szukamy.";
  return `znalezione ${found}/3 — szukaj dalej`;
}

/** Błąd 2: nazwa pliku w nagłówku runnera (pełna scena i lista na telefonie). */
function SpecName() {
  return <GlitchBug index={1} wrong="kandydat.spce.ts" right="kandydat.spec.ts" what="literówka w nazwie pliku testów" />;
}

function Hunt() {
  const { bugs } = useScene();
  const found = bugs.filter(Boolean).length;
  return (
    <div className="kr-gl-hunt">
      <p>
        <span className="kr-gl-tag">bug hunt</span> · na tej stronie są 3 błędy. Znajdziesz je?
      </p>
      <span className="kr-gl-dots" aria-hidden="true">
        {bugs.map((b, i) => (
          <span key={i} data-on={b ? "" : undefined} />
        ))}
      </span>
      <p aria-live="polite" data-done={found >= GLITCH_BUG_COUNT ? "" : undefined} className="kr-gl-msg">
        {huntMessage(found)}
      </p>
    </div>
  );
}

export function GlitchScene() {
  const { items, isOn, toggle, count, total, still } = useScene();
  const [run, setRun] = useState(0);
  return (
    <>
      <SceneFrame label="Runner testów: oznacz testy, które zdasz" className="kr-sc-glitch">
        <div className="kr-gl-head">
          <span>
            <SpecName /> · {count} passed · {total - count} pending
          </span>
          <button type="button" className="kr-gl-run" onClick={() => setRun((r) => r + 1)}>
            <span aria-hidden="true">▶ </span>uruchom
          </button>
        </div>
        {run > 0 && !still ? <span className="kr-gl-prog" key={run} aria-hidden="true" /> : null}
        {items.map((item, i) => {
          const on = isOn(i);
          return (
            <button
              type="button"
              key={item.key}
              className="kr-gl-row"
              aria-pressed={on}
              aria-label={itemAria(item)}
              data-on={on ? "" : undefined}
              onClick={() => toggle(i)}
            >
              <span className="kr-gl-ic">{on ? "✓" : "○"}</span>
              <span>
                <span className="kr-w">test(&apos;{item.name}&apos;)</span>
                {item.note ? (
                  <>
                    <br />
                    <span className="kr-gl-note">
                      {"// "}
                      {item.note}
                    </span>
                  </>
                ) : null}
              </span>
              <span className="kr-gl-st">{on ? "PASS" : "CZEKA"}</span>
            </button>
          );
        })}
        <p className="kr-gl-hint">kliknij test, który zdasz — mam to = PASS</p>
        <Hunt />
      </SceneFrame>
      <SceneList
        head={
          <>
            test <SpecName />
          </>
        }
        hint="dotknij testu, który zdasz — PASS"
        mark={(on) => (on ? "✓ PASS" : "○ CZEKA")}
        footer={<Hunt />}
      />
    </>
  );
}
