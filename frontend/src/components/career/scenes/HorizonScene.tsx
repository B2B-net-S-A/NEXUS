"use client";

import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Horyzont (frontend, fullstack): kartridże z umiejętnościami nad siatką
 * horyzontu. Zebrany trafia do ekwipunku, wynik i poziom rosną, siatka
 * przyspiesza. Kartridż zostaje na miejscu jako przycisk — fokus nie ginie.
 */
export const CARTS: readonly [number, number][] = [
  [24, 64],
  [282, 50],
  [304, 176],
  [18, 206],
  [158, 128],
];

export function horizonHud(count: number, total: number): { score: string; level: string } {
  return { score: String(count * 300).padStart(4, "0"), level: `${count}/${total}` };
}

/** Szybkość linii podłogi (s): im więcej zebranych, tym szybciej. */
export function floorSpeed(count: number): number {
  return Math.max(0.6, Number((2.6 - count * 0.4).toFixed(1)));
}

export function HorizonScene() {
  const { items, order, isOn, toggle, count, total } = useScene();
  const hud = horizonHud(count, total);
  const speed = floorSpeed(count);
  return (
    <>
      <SceneFrame label="Horyzont: zbierz power-upy, które masz" className="kr-sc-horizon">
        <svg viewBox="0 0 448 520" className="kr-hz-svg" aria-hidden="true">
          <g className="kr-hz-sun">
            <circle cx={270} cy={300} r={86} />
            <rect x={170} y={318} width={200} height={5} />
            <rect x={170} y={334} width={200} height={8} />
          </g>
          <rect x={0} y={350} width={448} height={170} className="kr-hz-ground" />
          <path d="M0 350H448" className="kr-hz-line" />
          <g className="kr-hz-floor">
            {[-460, -260, -60, 140, 340, 540, 740, 940].map((x) => (
              <path key={x} d={`M224 350L${x / 2 + 112} 520`} />
            ))}
            {[358, 372, 396, 432, 480].map((y) => (
              <path key={y} d={`M0 ${y}H448`} />
            ))}
          </g>
          <g className="kr-hz-fly">
            {[0, 1, 2].map((k) => (
              <path
                key={k}
                d="M0 350H448"
                style={{ animationDuration: `${speed}s`, animationDelay: `${(speed * k) / 3}s` }}
              />
            ))}
          </g>
        </svg>
        <p className="kr-hz-hud" aria-hidden="true">
          <span>WYNIK {hud.score}</span>
          <span>POZIOM {hud.level}</span>
        </p>
        {items.map((item, i) => {
          const on = isOn(i);
          const [x, y] = CARTS[i];
          return (
            <button
              type="button"
              key={item.key}
              className="kr-hz-cart"
              aria-pressed={on}
              aria-label={itemAria(item)}
              data-on={on ? "" : undefined}
              style={{ left: x, top: y, animationDelay: `${i * 0.35}s` }}
              onClick={() => toggle(i)}
            >
              <span className="kr-hz-n">{item.name}</span>
              <span className="kr-hz-t">{on ? "ZEBRANE ✓" : (item.note ?? "POWER-UP").toLocaleUpperCase("pl-PL")}</span>
            </button>
          );
        })}
        <p className="kr-hz-inv" aria-hidden="true">
          <span>EKWIPUNEK:</span>
          {order.length === 0 ? <span>pusto — kliknij kartridż</span> : null}
          {order.map((i) => (
            <span key={items[i]?.key ?? i} className="kr-hz-chip">
              + {items[i]?.name}
            </span>
          ))}
        </p>
      </SceneFrame>
      <SceneList
        head={`WYNIK ${hud.score} · POZIOM ${hud.level}`}
        hint="dotknij power-upu, który masz — trafi do ekwipunku"
        mark={(on) => (on ? "★ ZEBRANE" : "☆")}
      />
    </>
  );
}
