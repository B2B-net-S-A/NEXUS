/**
 * Szklana mapa Polski jako tekst SVG (bez napisów) do grafik Open Graph
 * (`next/og` / satori). Napisy stawia kadr osobno, bo tekst w obrazku SVG
 * nie dostaje fontów satori. Geometria ta sama co na stronie
 * (`polandMap.ts`), wygląd jak makiety OG-lista, OG-oferta i OG-zdalna
 * (język A, 26.11.2026).
 */
import { COL_W, MAP_OUTLINE, REMOTE_DOTS, SLAB, buildCityMap, columnShape, points, type CityMap } from "./polandMap";
import type { Facet } from "./site";

const OUTLINE = points(MAP_OUTLINE);
const SLAB_PTS = points(MAP_OUTLINE, SLAB);
/** Najniższa podświetlona kolumna oferty (jak na stronie). */
const LIT_MIN = 200;

const DEFS = `<defs>
<linearGradient id="F" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.62"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0.10"/></linearGradient>
<linearGradient id="R" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0.30"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0.04"/></linearGradient>
<linearGradient id="H" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF4F0"/><stop offset="1" stop-color="#FFD6C9" stop-opacity="0.55"/></linearGradient>
<pattern id="D" width="11" height="11" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#FFFFFF" opacity="0.3"/></pattern>
<clipPath id="C"><polygon points="${OUTLINE}"/></clipPath>
<filter id="B" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="14"/></filter>
</defs>`;

const SLAB_SVG = `<polygon points="${SLAB_PTS}" fill="#7A111B" stroke="#FFFFFF" stroke-opacity="0.25"/>
<polygon points="${OUTLINE}" fill="#FFFFFF" fill-opacity="0.13" stroke="#FFFFFF" stroke-opacity="0.75" stroke-width="1.4"/>
<rect x="0" y="300" width="600" height="280" fill="url(#D)" clip-path="url(#C)"/>`;

export interface MapSvg {
  svg: string;
  /** Okno rysunku w układzie mapy: x, y, szerokość, wysokość. */
  view: [number, number, number, number];
}

function wrap(view: MapSvg["view"], body: string): MapSvg {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${view.join(" ")}" width="${view[2]}" height="${view[3]}">${DEFS}${body}</svg>`;
  return { svg, view };
}

/** Lista ofert: kolumny miast z danymi, linie od największego miasta. */
export function cityColumnsSvg(map: CityMap): MapSvg {
  const flows = map.flows.map((d) => `<path d="${d}"/>`).join("");
  const hubCol = map.hub ? map.columns.find((c) => c.foot === map.hub) : null;
  const cols = map.columns
    .map((c) => {
      const hot = c === hubCol;
      return `<polygon points="${c.right}" fill="${hot ? "#FFD6C9" : "url(#R)"}" fill-opacity="${hot ? 0.55 : 1}"/><polygon points="${c.front}" fill="url(#${hot ? "H" : "F"})"/><polygon points="${c.top}" fill="#FFFFFF" fill-opacity="${hot ? 1 : 0.8}"/>`;
    })
    .join("");
  const leaders = map.labels
    .map((l) => `<path d="M${l.line[0].toFixed(0)},${l.line[1].toFixed(0)} L${l.line[2].toFixed(0)},${l.line[3].toFixed(0)}"/>`)
    .join("");
  return wrap(
    [0, 60, 600, 540],
    `${SLAB_SVG}<g fill="none" stroke="#FFFFFF" stroke-width="1.4" stroke-opacity="0.7" stroke-dasharray="3 7">${flows}</g>` +
      `<g stroke="#FFFFFF" stroke-opacity="0.8" stroke-width="1" stroke-linejoin="round">${cols}</g>` +
      `<g stroke="#FFFFFF" stroke-opacity="0.75" fill="none">${leaders}</g>`,
  );
}

export interface LitColumn {
  x: number;
  base: number;
  height: number;
}

/**
 * Oferta w mieście: kolumny tablicy przygaszone, miasta oferty podświetlone
 * (co najmniej 200 jednostek, żeby podpis stał nad płytą). Zwraca też
 * kolumny podświetlone — kadr stawia przy pierwszej podpis miasta.
 */
export function offerFocusSvg(facets: readonly Facet[], cities: readonly string[]): MapSvg & { lit: LitColumn[] } {
  const known = buildCityMap(facets).columns;
  const lit = cities
    .map((name) => known.find((k) => k.label === name) ?? buildCityMap([{ id: name, label: name, count: 40 }]).columns[0] ?? null)
    .filter((c): c is NonNullable<typeof c> => c !== null)
    .map((c) => ({ x: c.x, base: c.base, height: Math.max(c.height, LIT_MIN) }));
  const faint = known
    .filter((k) => !cities.includes(k.label))
    .map((c) => `<polygon points="${c.front}" fill="url(#F)"/><polygon points="${c.top}" fill="#FFFFFF"/>`)
    .join("");
  const hot = lit
    .map((c) => {
      const s = columnShape(c.x, c.base, c.height);
      return `<polygon points="${s.right}" fill="#FFD6C9" fill-opacity="0.55"/><polygon points="${s.front}" fill="url(#H)"/><polygon points="${s.top}" fill="#FFFFFF"/>`;
    })
    .join("");
  const glow = lit[0]
    ? `<ellipse cx="${(lit[0].x + COL_W / 2).toFixed(0)}" cy="${(lit[0].base - 2).toFixed(0)}" rx="36" ry="14" fill="#FFD6C9" opacity="0.9" filter="url(#B)"/>`
    : "";
  const svg = wrap(
    [0, 100, 600, 490],
    `${SLAB_SVG}<g opacity="0.3" stroke="#FFFFFF" stroke-width="1">${faint}</g>${glow}<g stroke="#FFFFFF" stroke-width="1.2" stroke-linejoin="round">${hot}</g>`,
  );
  return { ...svg, lit };
}

/** Praca zdalna: cała płyta świeci, czerwone punkty w całym kraju. */
export function remoteSvg(): MapSvg {
  const dots = REMOTE_DOTS.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4"/>`).join("");
  return wrap(
    [0, 290, 600, 300],
    `<ellipse cx="290" cy="450" rx="300" ry="120" fill="#FFD6C9" opacity="0.4" filter="url(#B)"/>` +
      `<polygon points="${SLAB_PTS}" fill="#F3B9A8" stroke="#FFFFFF" stroke-opacity="0.5"/>` +
      `<polygon points="${OUTLINE}" fill="#FFF4F0" fill-opacity="0.92" stroke="#FFFFFF" stroke-width="1.5"/>` +
      `<g fill="#C42329">${dots}</g>`,
  );
}

/** Zamknięta rekrutacja: sam przerywany obrys. */
export function closedSvg(): MapSvg {
  return wrap(
    [0, 300, 600, 290],
    `<polygon points="${OUTLINE}" fill="#FFFFFF" fill-opacity="0.10" stroke="#FFFFFF" stroke-opacity="0.6" stroke-width="1.6" stroke-dasharray="6 6"/>`,
  );
}

/** SVG jako `data:` URI dla `<img>` (satori i przeglądarka). */
export function svgDataUri(svg: string): string {
  let bin = "";
  for (const b of new TextEncoder().encode(svg)) bin += String.fromCharCode(b);
  return `data:image/svg+xml;base64,${btoa(bin)}`;
}
