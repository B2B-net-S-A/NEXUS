"use client";

import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Tablica warsztatowa (analityk biznesowy): karteczki z wymaganiami w kolumnie
 * „Do omówienia”; kliknięta przechodzi do „Mam to” (w kolejności klikania).
 */
export const BOARD_TOP = 40;
export const BOARD_STEP = 94;
const TILT = [-2, 1.5, -1, 2, -1.5];

/** Położenie karteczki: lewa kolumna wg miejsca na liście, prawa wg kolejności przeniesienia. */
export function notePosition(index: number, order: readonly number[]): { column: "todo" | "done"; top: number } {
  const k = order.indexOf(index);
  return k >= 0 ? { column: "done", top: BOARD_TOP + k * BOARD_STEP } : { column: "todo", top: BOARD_TOP + index * BOARD_STEP };
}

export function BoardScene() {
  const { items, order, isOn, toggle, count, total } = useScene();
  return (
    <>
      <SceneFrame label="Tablica warsztatowa: przenieś do „Mam to”, co już robiłeś" className="kr-sc-board">
        <p className="kr-board-col kr-board-col-todo" aria-hidden="true">
          DO OMÓWIENIA · {total - count}
        </p>
        <p className="kr-board-col kr-board-col-done" aria-hidden="true">
          MAM TO · {count}
        </p>
        {items.map((item, i) => {
          const on = isOn(i);
          const pos = notePosition(i, order);
          const tilt = TILT[i % TILT.length] * (on ? -0.5 : 1);
          return (
            <button
              type="button"
              key={item.key}
              className="kr-board-note"
              aria-pressed={on}
              aria-label={itemAria(item)}
              data-on={on ? "" : undefined}
              data-tone={i % 2}
              style={{ top: pos.top, left: pos.column === "done" ? 240 : 16, rotate: `${tilt}deg` }}
              onClick={() => toggle(i)}
            >
              <span className="kr-board-t">{item.name}</span>
              {item.note ? <span className="kr-board-s">{item.note}</span> : null}
              {on ? <span className="kr-board-stamp">{item.kind === "must" ? "MUST · MAM" : "MAM"}</span> : null}
            </button>
          );
        })}
      </SceneFrame>
      <SceneList
        head={`DO OMÓWIENIA · ${total - count}  /  MAM TO · ${count}`}
        hint="dotknij karteczki, którą już robiłeś — trafi do „Mam to”"
        mark={(on) => (on ? "▣ mam to" : "▢ do omówienia")}
      />
    </>
  );
}
