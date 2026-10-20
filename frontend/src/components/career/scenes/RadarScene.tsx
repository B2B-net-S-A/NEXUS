"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";

import { useScene } from "./SceneContext";
import { ItemName, itemAria, SceneFrame, SceneList } from "./SceneParts";

/**
 * Radar (security): cele = wymagania. Klik namierza cel (ramka namiaru),
 * dziennik pokazuje ostatnie trzy namiary. Z myszą: celownik i odczyt
 * azymutu i zasięgu pod kursorem.
 */
export const RADAR_CENTER: readonly [number, number] = [224, 230];
export const RADAR_RADIUS = 180;
export const BLIPS: readonly [number, number][] = [
  [288, 154],
  [351, 276],
  [211, 301],
  [100, 252],
  [166, 161],
];

/** Azymut (0° = północ, zgodnie z zegarem) i zasięg w % promienia. */
export function radarReadout(x: number, y: number): { az: number; range: number } {
  const dx = x - RADAR_CENTER[0];
  const dy = y - RADAR_CENTER[1];
  const az = Math.round(((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360) % 360;
  const range = Math.min(100, Math.round((Math.hypot(dx, dy) / RADAR_RADIUS) * 100));
  return { az, range };
}

export function RadarScene() {
  const { items, order, isOn, toggle, pointerFx, extraNice } = useScene();
  const [read, setRead] = useState<{ az: number; range: number } | null>(null);
  const frame = useRef(0);
  useEffect(() => () => window.cancelAnimationFrame(frame.current), []);
  const [cx, cy] = RADAR_CENTER;

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!pointerFx || frame.current) return;
    const el = e.currentTarget;
    const { clientX, clientY } = e;
    frame.current = window.requestAnimationFrame(() => {
      frame.current = 0;
      const r = el.getBoundingClientRect();
      setRead(radarReadout(clientX - r.left, clientY - r.top));
    });
  };

  const log = order
    .slice(-3)
    .reverse()
    .map((i) => items[i])
    .filter(Boolean);

  return (
    <>
      <SceneFrame label="Radar: namierz to, co masz w arsenale" className="kr-sc-radar">
        <div className="kr-radar-field" onPointerMove={onMove} onPointerLeave={() => setRead(null)}>
          <svg viewBox="0 0 448 520" className="kr-radar-svg" aria-hidden="true">
            <g className="kr-radar-rings">
              <circle cx={cx} cy={cy} r={60} />
              <circle cx={cx} cy={cy} r={120} />
              <circle cx={cx} cy={cy} r={RADAR_RADIUS} />
            </g>
            <path d={`M${cx - RADAR_RADIUS} ${cy}H${cx + RADAR_RADIUS}M${cx} ${cy - RADAR_RADIUS}V${cy + RADAR_RADIUS}`} className="kr-radar-axis" />
            <g className="kr-radar-sweep">
              <path d={`M${cx} ${cy}L${cx} ${cy - RADAR_RADIUS}A${RADAR_RADIUS} ${RADAR_RADIUS} 0 0 1 ${cx + 127} ${cy - 127}Z`} className="kr-radar-cone" />
              <path d={`M${cx} ${cy}L${cx + 127} ${cy - 127}`} className="kr-radar-beam" />
            </g>
            {extraNice.slice(0, 2).map((n, i) => (
              <circle key={n} cx={i ? 120 : 330} cy={i ? 100 : 380} r={3.5} className="kr-radar-faint" />
            ))}
          </svg>
          {extraNice.slice(0, 2).map((n, i) => (
            <span key={n} className="kr-radar-nice" aria-hidden="true" style={{ left: i ? 64 : 296, top: i ? 80 : 388 }}>
              {n} · mile widziane
            </span>
          ))}
          {items.map((item, i) => {
            const on = isOn(i);
            const [x, y] = BLIPS[i];
            return (
              <button
                type="button"
                key={item.key}
                className="kr-radar-blip"
                aria-pressed={on}
                aria-label={itemAria(item)}
                data-on={on ? "" : undefined}
                data-side={x > 300 ? "left" : undefined}
                style={{ left: x, top: y }}
                onClick={() => toggle(i)}
              >
                {on ? (
                  <svg className="kr-radar-lock" viewBox="0 0 44 44" aria-hidden="true">
                    <path d="M2 12V2H12M32 2H42V12M42 32V42H32M12 42H2V32" />
                  </svg>
                ) : (
                  <span className="kr-radar-halo" />
                )}
                <span className="kr-radar-dot" />
                <span className="kr-radar-tag"><ItemName item={item} /></span>
              </button>
            );
          })}
        </div>
        <div className="kr-radar-log" aria-live="polite">
          <p className="kr-radar-read">
            {read ? `AZ ${String(read.az).padStart(3, "0")}° · ZASIĘG ${read.range}%` : "kliknij cel, który znasz"}
          </p>
          {log.map((item) => (
            <p key={item.key}>
              NAMIERZONO › {item.name}
              {item.note ? ` — ${item.note}` : ""}
            </p>
          ))}
        </div>
      </SceneFrame>
      <SceneList
        head="RADAR · cele"
        hint="dotknij celu, który masz w arsenale — namierzysz go"
        mark={(on) => (on ? "◎ NAMIERZONO" : "○ cel")}
      />
    </>
  );
}
