"use client";

import { methodName } from "./model";
import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Diagram sekwencji (analityk systemowy): komunikaty Ty → :Projekt. Kliknięty
 * komunikat rysuje strzałkę, wraca „200 OK” z notatką, pasek aktywacji rośnie.
 */
export const SEQ_FIRST_Y = 84;
export const SEQ_STEP_Y = 90;

/** Wysokość paska aktywacji po stronie projektu (px). */
export function activationHeight(count: number): number {
  return count * SEQ_STEP_Y;
}

export function SequenceScene() {
  const { items, isOn, toggle, count } = useScene();
  return (
    <>
      <SceneFrame label="Diagram sekwencji: obsłuż komunikaty, które znasz" className="kr-sc-seq">
        <span className="kr-seq-frame" aria-hidden="true">
          sd Ty → Projekt
        </span>
        <span className="kr-seq-part kr-seq-part-a" aria-hidden="true">
          Ty
        </span>
        <span className="kr-seq-part kr-seq-part-b" aria-hidden="true">
          :Projekt
        </span>
        <span className="kr-seq-life kr-seq-life-a" aria-hidden="true" />
        <span className="kr-seq-life kr-seq-life-b" aria-hidden="true" />
        <span className="kr-seq-act" aria-hidden="true" style={{ height: activationHeight(count) }} />
        {items.map((item, i) => {
          const on = isOn(i);
          return (
            <button
              type="button"
              key={item.key}
              className="kr-seq-msg"
              aria-pressed={on}
              aria-label={itemAria(item)}
              style={{ top: SEQ_FIRST_Y + i * SEQ_STEP_Y }}
              onClick={() => toggle(i)}
              data-on={on ? "" : undefined}
            >
              <span className="kr-seq-lab">
                {i + 1}: {methodName(item.name)}()
              </span>
              <span className="kr-seq-ghost" />
              <span className="kr-seq-arr" />
              <span className="kr-seq-rep" />
              <span className="kr-seq-rlab">200 OK · {item.note ?? item.name}</span>
            </button>
          );
        })}
        <p className="kr-seq-hint" aria-hidden="true">
          {"// kliknij komunikat, który obsłużysz"}
        </p>
      </SceneFrame>
      <SceneList
        head="sd Ty → Projekt"
        hint="dotknij komunikatu, który obsłużysz — wróci 200 OK"
        mark={(on, i) => (on ? `${i + 1} → 200 OK` : `${i + 1} →`)}
      />
    </>
  );
}
