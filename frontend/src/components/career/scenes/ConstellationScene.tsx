"use client";

import { useScene } from "./SceneContext";
import { itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Konstelacja (data / AI): gwiazdy = wymagania. Klikane po kolei łączą się
 * linią w Twój gwiazdozbiór; nazwa rośnie z liczbą gwiazd. Tło lekko płynie
 * za kursorem (tylko mysz, bez ograniczenia ruchu).
 */
export const STAR_POSITIONS: readonly [number, number][] = [
  [84, 130],
  [232, 84],
  [362, 186],
  [312, 326],
  [150, 300],
];

const CONSTELLATIONS = ["", "Samotna Gwiazda", "Podwójny Układ", "Trójkąt Danych", "Wielki Potok", "Pełna Platforma"];

export function constellationName(count: number): string {
  if (count <= 0) return "Twój gwiazdozbiór: jeszcze pusty";
  return `Twój gwiazdozbiór: „${CONSTELLATIONS[Math.min(count, CONSTELLATIONS.length - 1)]}”`;
}

/** Punkty linii w kolejności klikania. */
export function constellationPoints(order: readonly number[]): string {
  return order
    .filter((i) => i < STAR_POSITIONS.length)
    .map((i) => STAR_POSITIONS[i].join(","))
    .join(" ");
}

const SKY: readonly [number, number, number][] = [
  [30, 470, 1], [110, 420, 0.8], [270, 470, 1.1], [400, 40, 0.9], [420, 300, 0.7],
  [20, 20, 0.8], [250, 20, 0.7], [430, 470, 1.1], [190, 200, 0.6], [330, 450, 0.9],
  [60, 250, 0.7], [400, 120, 0.8],
];

export function ConstellationScene() {
  const { items, order, isOn, toggle, clear, count, extraNice, still } = useScene();
  const pts = constellationPoints(order);
  return (
    <>
      <SceneFrame label="Konstelacja: połącz gwiazdy, które znasz" className="kr-sc-const">
        <svg className="kr-const-sky" viewBox="0 0 448 520" aria-hidden="true">
          {SKY.map(([x, y, r], i) => (
            <circle key={i} cx={x} cy={y} r={r} className={`kr-const-tw kr-const-tw${i % 3}`} />
          ))}
        </svg>
        <svg className="kr-const-lines" viewBox="0 0 448 520" aria-hidden="true">
          <path
            d={`M${STAR_POSITIONS.slice(0, items.length)
              .map((p) => p.join(" "))
              .join("L")}${items.length > 2 ? "Z" : ""}`}
            className="kr-const-guide"
          />
          {order.length > 1 ? (
            <polyline points={pts} className={still ? "kr-const-path" : "kr-const-path kr-const-draw"} key={pts} />
          ) : null}
          {extraNice.slice(0, 2).map((n, i) => (
            <g key={n}>
              <circle cx={i ? 110 : 396} cy={i ? 400 : 420} r={3} className="kr-const-faint" />
            </g>
          ))}
        </svg>
        {extraNice.slice(0, 2).map((n, i) => (
          <span
            key={n}
            className="kr-const-nice"
            aria-hidden="true"
            style={{ left: i ? 70 : 300, top: i ? 410 : 430 }}
          >
            {n} · mile widziane
          </span>
        ))}
        {items.map((item, i) => {
          const on = isOn(i);
          const [x, y] = STAR_POSITIONS[i];
          return (
            <button
              type="button"
              key={item.key}
              className="kr-const-star"
              aria-pressed={on}
              aria-label={itemAria(item)}
              data-on={on ? "" : undefined}
              style={{ left: x, top: y }}
              onClick={() => toggle(i)}
            >
              <span className="kr-const-core" />
              {on ? <span className="kr-const-num">{order.indexOf(i) + 1}</span> : null}
              <span className="kr-const-lab">{item.name}</span>
            </button>
          );
        })}
        <div className="kr-const-res" aria-live="polite">
          <p className="kr-const-name">{constellationName(count)}</p>
          <p>{count === 0 ? "kliknij pierwszą gwiazdę" : order.map((i) => items[i]?.name).join(" → ")}</p>
          {/* Zawsze w DOM (aria-disabled przy zerze), żeby fokus nie spadł na <body>. */}
          <button
            type="button"
            className="kr-const-clr"
            aria-disabled={count === 0}
            onClick={count > 0 ? clear : undefined}
          >
            zacznij od nowa
          </button>
        </div>
      </SceneFrame>
      <SceneList
        head={constellationName(count)}
        hint="dotknij gwiazdy, którą znasz — połączy się z resztą"
        mark={(on, i) => (on ? `★ ${order.indexOf(i) + 1}` : "☆")}
      />
    </>
  );
}
