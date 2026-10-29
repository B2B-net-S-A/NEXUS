"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useRef } from "react";

import type { CareerBoardJob } from "@/lib/career/api";

import { sceneItems, type SceneItem } from "./requirementItems";
import {
  careerTheme,
  DEFAULT_CAREER_THEME,
  isCareerThemeId,
  type CareerThemeId,
  type ThemePalette,
} from "./themes";

gsap.registerPlugin(useGSAP);

/** `gsap.from` tylko dla niepustej listy — pusty cel to ostrzeżenie w konsoli. */
function fromIf(targets: Element[], vars: gsap.TweenVars): void {
  if (targets.length > 0) gsap.from(targets, vars);
}

/**
 * Żywy podgląd sceny na tablicy (etap 7, D2 = A, 21.10.2026; prototyp
 * https://claude.ai/artifact/TsUgULCMSSjVTiYWvoGN3b). Najechanie albo fokus na
 * wierszu buduje tu szkic rekrutacji z jej wymagań w kolorach szablonu.
 * To ozdoba obok listy (`aria-hidden` rysunku). Ruch tylko od 1024 px i bez
 * „ograniczonego ruchu” — inaczej szkic stoi w stanie końcowym.
 */

type Layout = "list" | "net" | "lanes";

// Trzy szablony od 28.10.2026 — każdy z innym rytmem znaku i podglądu.
const LAYOUTS: Record<CareerThemeId, Layout> = {
  terminal: "list",
  grafit: "net",
  jasny: "lanes",
};

/** Punkty sceny w polu 400 × 300 — po jednym na wymaganie, najwyżej pięć. */
const POINTS: Record<Layout, readonly [number, number][]> = {
  list: [
    [40, 78],
    [40, 124],
    [40, 170],
    [40, 216],
    [40, 262],
  ],
  net: [
    [70, 150],
    [184, 70],
    [184, 232],
    [306, 108],
    [326, 222],
  ],
  lanes: [
    [40, 78],
    [96, 124],
    [152, 170],
    [70, 216],
    [190, 262],
  ],
};

const NET_EDGES: readonly [number, number][] = [
  [0, 1],
  [0, 2],
  [1, 3],
  [2, 4],
  [3, 4],
  [1, 2],
];
/** Szerokość znaku kroju mono przy 12 px — do zmieszczenia podpisu w polu. */
const CHAR_W = 7.3;

/** Środek podpisu pod punktem, przesunięty tak, żeby nie wyszedł poza scenę. */
function labelX(x: number, text: string): number {
  const half = (text.length * CHAR_W) / 2;
  return Math.min(Math.max(x, 12 + half), 388 - half);
}

function Decor({
  layout,
  p,
  n,
}: {
  layout: Layout;
  p: ThemePalette;
  n: number;
}) {
  const pts = POINTS[layout].slice(0, n);
  switch (layout) {
    case "net":
      return (
        <g>
          {NET_EDGES.filter(([a, b]) => a < n && b < n).map(([a, b]) => (
            <line
              key={`${a}-${b}`}
              className="kr-bp-link"
              x1={pts[a][0]}
              y1={pts[a][1]}
              x2={pts[b][0]}
              y2={pts[b][1]}
              stroke={p.decor}
              strokeWidth="1.2"
              opacity=".75"
            />
          ))}
          {n > 1 ? (
            <circle
              className="kr-bp-packet"
              r="3.2"
              cx={pts[0][0]}
              cy={pts[0][1]}
              fill={p.accent}
            />
          ) : null}
        </g>
      );
    case "lanes":
      return (
        <g>
          {pts.map(([x, y], i) => (
            <rect
              key={i}
              className="kr-bp-bar"
              x={x}
              y={y - 9}
              width={150 + ((i * 37) % 80)}
              height="18"
              rx="4"
              fill={p.decor}
              opacity=".28"
            />
          ))}
          <line
            className="kr-bp-today"
            x1="230"
            y1="48"
            x2="230"
            y2="284"
            stroke={p.accent}
            strokeWidth="1.2"
            strokeDasharray="4 4"
          />
        </g>
      );
    case "list":
      return (
        <g>
          <text x="20" y="34" fill={p.muted} className="kr-bp-cmd">
            $ ./check --wymagania
          </text>
          <rect
            className="kr-bp-cursor"
            x="20"
            y={Math.min(278, 52 + n * 46)}
            width="9"
            height="14"
            fill={p.accent}
          />
        </g>
      );
  }
}

/** Podgląd na tablicy: szkic sceny z wymagań karty. */
export function BoardPreviewScene({ job }: { job: CareerBoardJob }) {
  const items = sceneItems(
    (job.must ?? []).map((name) => ({ name, note: null })),
    job.nice ?? [],
  );
  // `key`: każda rekrutacja to nowy szkic — animacje i pętle poprzedniego
  // giną z nim, zamiast narastać przy każdym najechaniu (audyt 21.10.2026).
  return <SceneSketch key={job.slug} theme={job.theme} items={items} animateKey={job.slug} />;
}

/**
 * Szkic sceny: tło szablonu, ozdoba układu i punkty wymagań z podpisami
 * (wymagania pełne, mile widziane puste).
 */
export function SceneSketch({
  theme: themeId,
  items,
  animateKey,
}: {
  theme: string;
  items: readonly SceneItem[];
  animateKey: string;
}) {
  const theme = isCareerThemeId(themeId) ? themeId : DEFAULT_CAREER_THEME;
  const p = careerTheme(theme);
  const layout = LAYOUTS[theme];
  const pts = POINTS[layout];
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      // Bez `matchMedia` (jsdom, bardzo stare przeglądarki) scena stoi.
      if (
        typeof window === "undefined" ||
        typeof window.matchMedia !== "function"
      )
        return;
      const mm = gsap.matchMedia();
      mm.add(
        "(min-width: 1024px) and (prefers-reduced-motion: no-preference)",
        () => {
          const q = gsap.utils.selector(root);
          const links: Element[] = q(".kr-bp-link");
          links.forEach((l) => {
            const len = Math.hypot(
              Number(l.getAttribute("x2")) - Number(l.getAttribute("x1")),
              Number(l.getAttribute("y2")) - Number(l.getAttribute("y1")),
            );
            gsap.fromTo(
              l,
              { strokeDasharray: len, strokeDashoffset: len },
              {
                strokeDashoffset: 0,
                duration: 0.7,
                ease: "power2.out",
                delay: 0.15,
              },
            );
          });
          fromIf(q(".kr-bp-dot"), {
            scale: 0,
            transformOrigin: "50% 50%",
            stagger: 0.07,
            duration: 0.45,
            ease: "back.out(2.4)",
          });
          fromIf(q(".kr-bp-label"), {
            opacity: 0,
            y: 6,
            stagger: 0.05,
            duration: 0.35,
            delay: 0.1,
          });
          fromIf(q(".kr-bp-bar, .kr-bp-note"), {
            scaleX: 0,
            transformOrigin: "0% 50%",
            stagger: 0.05,
            duration: 0.5,
            ease: "power3.out",
          });

          // Spokojna pętla — jedna na układ, bez migania (≤ 1 zmiana na sekundę).
          if (layout === "lanes")
            gsap.fromTo(
              q(".kr-bp-today"),
              { attr: { x1: 150, x2: 150 } },
              {
                attr: { x1: 320, x2: 320 },
                duration: 7,
                ease: "none",
                repeat: -1,
                yoyo: true,
              },
            );
          if (layout === "list")
            gsap.to(q(".kr-bp-cursor"), {
              opacity: 0,
              duration: 0.6,
              ease: "steps(1)",
              repeat: -1,
              yoyo: true,
            });
          if (layout === "net" && items.length > 1) {
            const path = NET_EDGES.filter(
              ([a, b]) => a < items.length && b < items.length,
            );
            const tl = gsap.timeline({ repeat: -1 });
            path.forEach(([a, b]) => {
              tl.fromTo(
                q(".kr-bp-packet"),
                { attr: { cx: pts[a][0], cy: pts[a][1] } },
                {
                  attr: { cx: pts[b][0], cy: pts[b][1] },
                  duration: 0.9,
                  ease: "power1.inOut",
                },
              );
            });
          }
        },
      );
      return () => mm.revert();
    },
    { scope: root, dependencies: [animateKey], revertOnUpdate: true },
  );

  return (
    <div
      ref={root}
      className="kr-bp-stage"
      style={{ background: p.bg, borderColor: p.line }}
    >
      <svg viewBox="0 0 400 300" aria-hidden="true" focusable="false">
        <Decor layout={layout} p={p} n={items.length} />
        {items.map((item, i) => {
          const [x, y] = pts[i];
          const inline = layout === "list" || layout === "lanes";
          const nice = item.kind === "nice";
          const lx = inline ? x + 18 : labelX(x, item.name);
          const ly = inline ? y + 4 : y + 24;
          const on = item.kind === "must";
          const color = p.accent;
          return (
            <g key={item.key}>
              <circle
                className="kr-bp-dot"
                cx={x}
                cy={y}
                r="6"
                fill={on ? color : p.bg}
                stroke={color}
                strokeWidth="2"
              />
              <text
                className="kr-bp-label"
                x={lx}
                y={ly}
                textAnchor={inline ? "start" : "middle"}
                fill={p.text}
              >
                {item.name}
                {nice && inline ? (
                  <tspan fill={p.muted}> · mile widziane</tspan>
                ) : null}
                {nice && !inline ? (
                  <tspan x={labelX(x, "mile widziane")} dy="14" fill={p.muted}>
                    mile widziane
                  </tspan>
                ) : null}
              </text>
            </g>
          );
        })}
        {items.length === 0 ? (
          <text
            className="kr-bp-label"
            x="200"
            y="156"
            textAnchor="middle"
            fill={p.muted}
          >
            wymagania na stronie rekrutacji
          </text>
        ) : null}
      </svg>
    </div>
  );
}

/** Znak rekrutacji przy wierszu tablicy: kolory i rytm jej szablonu. */
export function BoardGlyph({ theme }: { theme: string }) {
  const id = isCareerThemeId(theme) ? theme : DEFAULT_CAREER_THEME;
  const p = careerTheme(id);
  const layout = LAYOUTS[id];
  const pts = POINTS[layout]
    .slice(0, 3)
    .map(([x, y]) => [8 + (x / 400) * 28, 8 + (y / 300) * 28] as const);
  return (
    <svg
      className="kr-brow-glyph"
      viewBox="0 0 44 44"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="44" height="44" rx="10" fill={p.bg} stroke={p.line} />
      {layout === "list" ? (
        <g fill={p.accent}>
          <rect x="11" y="13" width="4" height="7" />
          <rect x="18" y="15" width="15" height="2.4" opacity=".6" />
          <rect x="18" y="22" width="11" height="2.4" opacity=".6" />
          <rect x="18" y="29" width="13" height="2.4" opacity=".6" />
        </g>
      ) : (
        <g>
          <polyline
            points={pts.map((q) => q.join(",")).join(" ")}
            fill="none"
            stroke={p.decor}
            strokeWidth="1.4"
          />
          {pts.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="2.6" fill={p.accent} />
          ))}
        </g>
      )}
    </svg>
  );
}
