"use client";

import { useState } from "react";

import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Topologia sieci (DevOps / Cloud): węzły = technologie, „TY” po lewej.
 * Kliknięty węzeł zestawia łącze z TY i puszcza po nim pakiety; najechany
 * albo z fokusem pokazuje notatkę.
 */
export const TOPO_YOU: readonly [number, number] = [96, 260];
export const TOPO_NODES: readonly [number, number][] = [
  [300, 72],
  [390, 196],
  [384, 344],
  [288, 428],
  [232, 250],
];
const MESH: readonly [number, number][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [0, 4],
  [4, 2],
  [1, 4],
  [3, 4],
];

/** Dymek pod węzłem, a dla dolnej połowy sceny — nad nim (nie wychodzi poza ramkę). */
export function tipPosition([x, y]: readonly [number, number]): { left: number; bottom?: number; top?: number } {
  const left = Math.max(8, Math.min(x - 100, 236));
  return y > 260 ? { left, bottom: 520 - y + 40 } : { left, top: y + 36 };
}

/** Opóźnienie „pingu” do zespołu maleje z każdym łączem (ozdoba). */
export function pingMs(count: number): number {
  return Math.max(12, 120 - count * 22);
}

export function TopologyScene() {
  const { items, isOn, toggle, count, extraNice } = useScene();
  const [hover, setHover] = useState<number | null>(null);
  const nodes = items.slice(0, TOPO_NODES.length);
  const [tx, ty] = TOPO_YOU;
  const tip = hover !== null ? nodes[hover] : null;
  return (
    <>
      <SceneFrame label="Topologia sieci: połącz się z tym, co znasz" className="kr-sc-topo">
        <svg viewBox="0 0 448 520" className="kr-topo-svg" aria-hidden="true">
          <g className="kr-topo-mesh">
            {MESH.filter(([a, b]) => a < nodes.length && b < nodes.length).map(([a, b]) => (
              <line
                key={`${a}-${b}`}
                x1={TOPO_NODES[a][0]}
                y1={TOPO_NODES[a][1]}
                x2={TOPO_NODES[b][0]}
                y2={TOPO_NODES[b][1]}
              />
            ))}
          </g>
          {nodes.map((item, i) => (
            <line
              key={item.key}
              x1={tx}
              y1={ty}
              x2={TOPO_NODES[i][0]}
              y2={TOPO_NODES[i][1]}
              className="kr-topo-link"
              data-on={isOn(i) ? "" : undefined}
            />
          ))}
          {nodes.map((item, i) =>
            isOn(i) ? (
              <circle
                key={`pk-${item.key}`}
                r={4}
                className={`kr-topo-pk${i % 2 ? " kr-topo-pk2" : ""}`}
                style={{ offsetPath: `path('M${tx} ${ty}L${TOPO_NODES[i][0]} ${TOPO_NODES[i][1]}')` }}
              />
            ) : null,
          )}
          <circle cx={tx} cy={ty} r={22} className="kr-topo-ping" />
          <circle cx={tx} cy={ty} r={24} className="kr-topo-you" />
        </svg>
        <span className="kr-topo-you-lab" aria-hidden="true" style={{ left: tx, top: ty }}>
          TY
        </span>
        {nodes.map((item, i) => {
          const on = isOn(i);
          const [x, y] = TOPO_NODES[i];
          return (
            <button
              type="button"
              key={item.key}
              className="kr-topo-node"
              aria-pressed={on}
              aria-label={itemAria(item)}
              data-on={on ? "" : undefined}
              style={{ left: x, top: y }}
              onClick={() => toggle(i)}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              <span className="kr-topo-c" />
              <span className="kr-topo-l">{item.name}</span>
            </button>
          );
        })}
        {tip && hover !== null ? (
          <p
            className="kr-topo-tip"
            aria-hidden="true"
            style={tipPosition(TOPO_NODES[hover])}
          >
            <b>{tip.name}</b>
            {tip.note ?? (tip.kind === "nice" ? "mile widziane" : "")}
            <br />
            <span>{isOn(hover) ? "łącze zestawione — kliknij, by rozłączyć" : "kliknij, jeśli to znasz"}</span>
          </p>
        ) : null}
        <p className="kr-topo-stat" aria-hidden="true">
          ping do zespołu: {pingMs(count)} ms
          {extraNice.length > 0 ? ` · mile widziane: ${extraNice.join(", ").toLocaleLowerCase("pl-PL")}` : ""}
        </p>
      </SceneFrame>
      <SceneList
        head="TY ⇄ zespół"
        hint="dotknij węzła, który znasz — zestawi łącze"
        mark={(on) => (on ? "●━━ łącze" : "○ ┄ ┄")}
      />
    </>
  );
}
