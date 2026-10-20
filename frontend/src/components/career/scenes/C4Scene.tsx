"use client";

import { useRef, useState } from "react";
import { flushSync } from "react-dom";

import { useScene } from "./SceneContext";
import { ItemName, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Architektura C4 (architekt): C1 — kontekst (Ty, projekt, zespół), C2 —
 * kontenery do zaprojektowania. Pierwsze cztery pozycje to kontenery,
 * piąta — granica systemu. Krawędź świeci, gdy oba końce są zaprojektowane.
 */
export const C4_BOXES: readonly [number, number][] = [
  [224, 40],
  [100, 172],
  [348, 172],
  [224, 318],
];

/** Krawędzie między kontenerami (indeksy pozycji). */
export const C4_EDGES: readonly [number, number][] = [
  [0, 1],
  [0, 2],
  [0, 3],
  [2, 3],
];

export function c4EdgeLit(on: (i: number) => boolean, [a, b]: readonly [number, number]): boolean {
  return on(a) && on(b);
}

export function C4Scene() {
  const { items, isOn, toggle, recruiterFirstName } = useScene();
  const [view, setView] = useState<"c1" | "c2">("c2");
  const c2Ref = useRef<HTMLButtonElement>(null);
  // Przycisk „przełącz na C2” znika z widokiem C1 — fokus idzie na przełącznik C2.
  const goC2 = () => {
    flushSync(() => setView("c2"));
    c2Ref.current?.focus();
  };
  const boxes = items.slice(0, C4_BOXES.length);
  const boundary = items.length > C4_BOXES.length ? items[C4_BOXES.length] : null;
  const bIndex = C4_BOXES.length;
  const bOn = boundary ? isOn(bIndex) : false;
  return (
    <>
      <SceneFrame label="Architektura C4: zaprojektuj to, co już budowałeś" className="kr-sc-c4">
        <div className="kr-c4-bar">
          <span>poziom</span>
          <span className="kr-c4-views">
            <button type="button" className="kr-c4-vt" aria-pressed={view === "c1"} onClick={() => setView("c1")}>
              C1 · kontekst
            </button>
            <button
              type="button"
              ref={c2Ref}
              className="kr-c4-vt"
              aria-pressed={view === "c2"}
              onClick={() => setView("c2")}
            >
              C2 · kontenery
            </button>
          </span>
        </div>
        {view === "c1" ? (
          <div className="kr-c4-view" key="c1">
            <svg viewBox="0 0 448 470" aria-hidden="true" className="kr-c4-svg">
              <path d="M224 104V184M224 274V350M128 230H150M298 230H320" className="kr-c4-dash" />
            </svg>
            <p className="kr-c4-person" style={{ left: 150, top: 40 }}>
              [osoba]
              <br />
              Ty
            </p>
            <p className="kr-c4-system" style={{ left: 150, top: 184 }}>
              Projekt
              <br />
              <span>tu pracujesz</span>
            </p>
            <p className="kr-c4-ext" style={{ left: 20, top: 210 }}>
              [osoba]
              <br />
              {recruiterFirstName} · rekrutacja
            </p>
            <p className="kr-c4-ext" style={{ left: 320, top: 210 }}>
              [osoba]
              <br />
              zespół klienta
            </p>
            <p className="kr-c4-ext" style={{ left: 150, top: 350 }}>
              [system zewn.]
              <br />
              integracje
            </p>
            <button type="button" className="kr-c4-go" onClick={goC2}>
              przełącz na C2, żeby zaprojektować wnętrze
            </button>
          </div>
        ) : (
          <div className="kr-c4-view" key="c2">
            {boundary ? (
              <>
                <span className="kr-c4-bnd-line" aria-hidden="true" data-on={bOn ? "" : undefined} />
                <button
                  type="button"
                  className="kr-c4-bnd"
                  aria-pressed={bOn}
                  aria-label={itemAria(boundary)}
                  data-on={bOn ? "" : undefined}
                  onClick={() => toggle(bIndex)}
                >
                  [granica] {boundary.name}
                  {bOn ? " — zaprojektowana" : " — kliknij"}
                </button>
              </>
            ) : null}
            <svg viewBox="0 0 448 470" aria-hidden="true" className="kr-c4-svg">
              {C4_EDGES.filter(([a, b]) => a < boxes.length && b < boxes.length).map(([a, b]) => (
                <path
                  key={`${a}-${b}`}
                  d={`M${C4_BOXES[a][0]} ${C4_BOXES[a][1] + 34}L${C4_BOXES[b][0]} ${C4_BOXES[b][1] + 34}`}
                  className="kr-c4-edge"
                  data-on={c4EdgeLit(isOn, [a, b]) ? "" : undefined}
                />
              ))}
            </svg>
            {boxes.map((item, i) => {
              const on = isOn(i);
              const [x, y] = C4_BOXES[i];
              return (
                <button
                  type="button"
                  key={item.key}
                  className="kr-c4-box"
                  aria-pressed={on}
                  aria-label={itemAria(item)}
                  data-on={on ? "" : undefined}
                  style={{ left: x, top: y }}
                  onClick={() => toggle(i)}
                >
                  <span className="kr-c4-k">[{i === 3 ? "baza" : "kontener"}]</span>
                  <span className="kr-c4-n"><ItemName item={item} /></span>
                  {item.note ? <span className="kr-c4-d">{item.note}</span> : null}
                </button>
              );
            })}
          </div>
        )}
      </SceneFrame>
      <SceneList
        head="C2 · kontenery"
        hint="dotknij klocka, który już budowałeś"
        mark={(on, i) => {
          const kind = i === C4_BOXES.length ? "granica" : i === 3 ? "baza" : "kontener";
          return on ? `[${kind}] ✓` : `[${kind}]`;
        }}
      />
    </>
  );
}
