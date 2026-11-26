/**
 * Szklana mapa Polski strony kariery (język A, makiety z 26.11.2026:
 * A-pierwszy-ekran, A-telefon, O-oferta, O-zdalna, O-zamknieta,
 * O-brak-wynikow). Czysta geometria w układzie makiety (`viewBox` 600 × 540,
 * od y = 60): obrys kraju, kolumny miast, etykiety i linie od największego
 * miasta. Liczby i miasta przychodzą z tablicy (`facetCounts`), tu nic nie
 * jest wpisane na sztywno poza położeniem miast na mapie.
 */
import type { CareerJobParams } from "./api";
import type { Facet } from "./site";

/** Górna ściana płyty kraju (makieta A, ten sam obrys na każdym ekranie). */
export const MAP_OUTLINE: readonly [number, number][] = [
  [10.0, 357.4], [66.9, 345.0], [126.3, 328.3], [195.4, 320.0], [214.8, 336.6], [262.9, 334.6],
  [308.5, 336.6], [383.6, 338.7], [422.8, 338.3], [465.9, 353.3], [507.2, 390.7], [504.4, 411.5],
  [494.3, 428.2], [533.4, 453.1], [569.9, 482.2], [557.2, 503.0], [534.5, 540.5], [539.2, 557.1],
  [482.7, 544.6], [450.6, 548.8], [408.6, 553.0], [369.5, 536.3], [342.3, 540.5], [290.9, 519.7],
  [266.4, 511.4], [227.1, 503.0], [197.6, 494.7], [192.6, 503.0], [119.0, 478.1], [106.8, 473.9],
  [80.1, 444.8], [77.8, 432.3], [31.5, 403.2], [34.3, 382.4],
];
/** Grubość płyty (dolna ściana to obrys przesunięty w dół). */
export const SLAB = 16;

export function points(pts: readonly (readonly [number, number])[], dy = 0): string {
  return pts.map(([x, y]) => `${x.toFixed(1)},${(y + dy).toFixed(1)}`).join(" ");
}

/**
 * Przednia lewa krawędź podstawy kolumny (x) i linia podstawy (y). Osiem
 * miast z makiety ma jej współrzędne co do piksela (Trójmiasto rozsunięte,
 * żeby trzy kolumny się nie zlały); reszta z tego samego rzutu
 * (x ≈ 49,2·λ − 23,8·φ + 587, y ≈ 2605 − 41,6·φ), lekko przesunięta, gdy
 * stałaby w kolumnie sąsiada. Etykieta: strona (`left` / `right`) i wektor
 * od szczytu kolumny do etykiety.
 */
interface CityGeo {
  x: number;
  y: number;
  side: "left" | "right";
  dx: number;
  dy: number;
}
const UP_RIGHT = { side: "right", dx: 36, dy: -36 } as const;
const UP_LEFT = { side: "left", dx: -48, dy: -26 } as const;
const CITY_GEO: Record<string, CityGeo> = {
  Warszawa: { x: 378.0, y: 432.6, side: "right", dx: 38, dy: -38 },
  Gdańsk: { x: 232.7, y: 344.0, side: "right", dx: 32, dy: -36 },
  Gdynia: { x: 176.1, y: 338.2, ...UP_LEFT },
  Sopot: { x: 204.4, y: 341.1, side: "left", dx: -76, dy: -20 },
  Bydgoszcz: { x: 208.3, y: 395.6, side: "left", dx: -70, dy: 20 },
  Łódź: { x: 312.9, y: 452.2, side: "right", dx: 92, dy: 86 },
  Katowice: { x: 327.2, y: 514.6, side: "left", dx: -27, dy: 46 },
  Kraków: { x: 377.3, y: 522.9, side: "right", dx: 25, dy: 18 },
  Wrocław: { x: 209.4, y: 479.2, side: "left", dx: -40, dy: 30 },
  Poznań: { x: 173.0, y: 425.1, ...UP_LEFT },
  Szczecin: { x: 40.0, y: 382.7, side: "right", dx: 20, dy: -40 },
  Lublin: { x: 478.0, y: 473.4, ...UP_RIGHT },
  Białystok: { x: 462.4, y: 395.2, ...UP_RIGHT },
  Rzeszów: { x: 478.8, y: 523.7, side: "right", dx: 24, dy: 16 },
  Toruń: { x: 240.9, y: 400.2, ...UP_RIGHT },
  Olsztyn: { x: 315.5, y: 368.2, ...UP_RIGHT },
  Kielce: { x: 391.7, y: 489.2, ...UP_RIGHT },
  Opole: { x: 263.6, y: 497.5, side: "left", dx: -30, dy: 40 },
  Gliwice: { x: 298.0, y: 513.3, side: "left", dx: -30, dy: 36 },
  Częstochowa: { x: 318.8, y: 491.7, ...UP_LEFT },
};

/** Szerokość przedniej ściany i przesunięcie tylnej krawędzi (rzut makiety). */
export const COL_W = 22;
const BACK_X = 6.6;
const BACK_Y = 11.4;
/** Najwyższa kolumna jak Warszawa na makiecie (77 ofert × 3,6). */
const MAX_H = 277.2;
const PER_OFFER = 3.6;
const MIN_H = 6;

export type LabelSize = "big" | "mid" | "inline";

export interface MapColumn {
  id: string;
  label: string;
  count: number;
  x: number;
  base: number;
  height: number;
  front: string;
  right: string;
  top: string;
  /** Środek podstawy — tu kończą się linie od największego miasta. */
  foot: [number, number];
}

export interface MapLabel {
  id: string;
  size: LabelSize;
  anchor: "start" | "end";
  /** Linia od kolumny do etykiety. */
  line: [number, number, number, number];
  x: number;
  y: number;
  count: number;
  name: string;
}

export interface CityMap {
  columns: MapColumn[];
  labels: MapLabel[];
  /** Największe miasto (impuls i linie), `null` przy pustej mapie. */
  hub: [number, number] | null;
  flows: string[];
  /** Opis dla czytnika ekranu: „Warszawa 77, Gdańsk 42…”. */
  summary: string;
}

function cityGeo(label: string): CityGeo | null {
  return CITY_GEO[label] ?? null;
}

export function columnShape(x: number, base: number, height: number) {
  const top = base - height;
  return {
    front: points([[x, base], [x + COL_W, base], [x + COL_W, top], [x, top]]),
    right: points([
      [x + COL_W - BACK_X, base - BACK_Y],
      [x + COL_W, base],
      [x + COL_W, top],
      [x + COL_W - BACK_X, top - BACK_Y],
    ]),
    top: points([[x - BACK_X, top - BACK_Y], [x + COL_W - BACK_X, top - BACK_Y], [x + COL_W, top], [x, top]]),
  };
}

/** Skala: 3,6 jednostki na ofertę jak na makiecie, ściśnięta, gdy największe miasto by nie weszło. */
export function columnScale(max: number): number {
  return max > 0 ? Math.min(PER_OFFER, MAX_H / max) : PER_OFFER;
}

/** Szacunek szerokości tekstu (Montserrat / Source Sans 3, bez pomiaru w DOM). */
export function textWidth(text: string, size: number): number {
  return text.length * size * 0.56;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
function overlaps(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/** Rozmiary etykiet w jednostkach mapy: desktop jak makieta A, telefon (mapa 0,62×) większe. */
export const LABEL_FONT = {
  desktop: { big: 46, mid: 32, inline: 17, name: 18 },
  phone: { big: 44, mid: 36, inline: 27, name: 27 },
} as const;

/**
 * Kolumny miast z liczbami ofert. Miasta spoza listy położeń pomijamy na
 * mapie (zostają w chipach pod listą). Etykiety: największe miasto „big”,
 * miasta z co najmniej 10 ofertami „mid”, reszta w jednej linii („5 Sopot”);
 * na telefonie tylko cztery największe. Etykieta, która nachodziłaby na już
 * postawioną, znika — kolumna zostaje, a liczba jest w opisie i chipach.
 */
export function buildCityMap(facets: readonly Facet[], opts: { phone?: boolean } = {}): CityMap {
  const placed = facets
    .map((f) => ({ f, geo: cityGeo(f.label) }))
    .filter((p): p is { f: Facet; geo: CityGeo } => p.geo !== null && p.f.count > 0);
  const max = Math.max(0, ...placed.map((p) => p.f.count));
  const scale = columnScale(max);
  const font = opts.phone ? LABEL_FONT.phone : LABEL_FONT.desktop;

  const columns: MapColumn[] = placed
    .map(({ f, geo }) => {
      const height = Math.max(MIN_H, f.count * scale);
      return {
        id: f.id,
        label: f.label,
        count: f.count,
        x: geo.x,
        base: geo.y,
        height,
        ...columnShape(geo.x, geo.y, height),
        foot: [geo.x + COL_W / 2, geo.y - 6] as [number, number],
      };
    })
    // Od tyłu do przodu: kolumna bliżej widza zasłania dalszą.
    .sort((a, b) => a.base - b.base);

  const byRank = [...placed].sort((a, b) => b.f.count - a.f.count);
  const labels: MapLabel[] = [];
  const boxes: Box[] = [];
  // Kolumny są przeszkodą dla etykiet innych miast (np. „Gdańsk” wchodzący w kolumnę Warszawy).
  const colBox = (c: MapColumn): Box => ({ x0: c.x - BACK_X, x1: c.x + COL_W, y0: c.base - c.height - BACK_Y, y1: c.base });
  byRank.forEach(({ f, geo }, rank) => {
    if (opts.phone && rank >= 4) return;
    const col = columns.find((c) => c.id === f.id)!;
    const top = col.base - col.height;
    const size: LabelSize = rank === 0 ? "big" : f.count >= 10 || opts.phone ? "mid" : "inline";
    const w =
      size === "inline"
        ? textWidth(`${f.count} ${f.label}`, font.inline)
        : Math.max(textWidth(String(f.count), font[size]), textWidth(f.label, font.name));
    const h = size === "inline" ? font.inline : font[size] + font.name + 4;
    const obstacles = [...boxes, ...columns.filter((c) => c !== col).map(colBox)];
    // Najpierw strona z makiety, coraz bliżej kolumny; potem strona przeciwna.
    const tries: { side: "left" | "right"; dx: number }[] = [1, 0.6, 0.3].map((k) => ({ side: geo.side, dx: geo.dx * k }));
    tries.push({ side: geo.side === "right" ? "left" : "right", dx: -geo.dx });
    for (const t of tries) {
      const sx = t.side === "right" ? col.x + COL_W : col.x - BACK_X;
      const sy = top - 5;
      const ex = sx + t.dx;
      // Etykieta nie wychodzi nad górną krawędź mapy.
      const ey = Math.max(sy + geo.dy, 60 + (size === "inline" ? font.inline : font[size]));
      const tx = t.side === "right" ? ex + 6 : ex - 6;
      const anchor = t.side === "right" ? "start" : "end";
      const yTop = size === "inline" ? ey - font.inline : ey - font[size] * 0.8;
      const box = anchor === "start" ? { x0: tx, x1: tx + w, y0: yTop, y1: yTop + h } : { x0: tx - w, x1: tx, y0: yTop, y1: yTop + h };
      if (box.x0 < 0 || box.x1 > 600 || obstacles.some((b) => overlaps(b, box))) continue;
      boxes.push(box);
      labels.push({ id: f.id, size, anchor, line: [sx, sy, ex, ey], x: tx, y: ey, count: f.count, name: f.label });
      return;
    }
  });

  const hubCol = byRank.length > 0 ? columns.find((c) => c.id === byRank[0].f.id)! : null;
  const hub = hubCol ? hubCol.foot : null;
  const flows = hub
    ? columns
        .filter((c) => c !== hubCol)
        .map((c) => {
          const [hx, hy] = hub;
          const [cx, cy] = c.foot;
          const dist = Math.hypot(cx - hx, cy - hy);
          const mx = (hx + cx) / 2;
          const my = (hy + cy) / 2 - dist * 0.3;
          return `M${hx.toFixed(0)},${hy.toFixed(0)} Q${mx.toFixed(0)},${my.toFixed(0)} ${cx.toFixed(0)},${cy.toFixed(0)}`;
        })
    : [];

  return {
    columns,
    labels,
    hub,
    flows,
    summary: [...facets].map((f) => `${f.label} ${f.count}`).join(", "),
  };
}

export interface FittedLabel {
  anchor: "start" | "end";
  x: number;
  /** Mnożnik czcionki (< 1 tylko, gdy podpis nie mieści się po żadnej stronie). */
  scale: number;
}

/**
 * Podpis obok kolumny, który mieści się w szerokości mapy (0–600): najpierw
 * strona `prefer`, potem przeciwna, a gdy żadna nie wystarcza — większa z nich
 * z mniejszą czcionką. Bo mapa ma `overflow: visible` i za długi podpis
 * („Gdańsk, Gdynia, Sopot”, „Kraków · zamknięta”) wchodził w tekst oferty
 * albo dawał poziomy pasek przewijania na telefonie.
 */
export function fitLabel(
  colX: number,
  lines: readonly { text: string; size: number }[],
  prefer: "left" | "right",
  gap = 36,
): FittedLabel {
  const w = Math.max(...lines.map((l) => textWidth(l.text, l.size)));
  const leftX = colX - gap;
  const rightX = colX + COL_W + gap;
  const left: FittedLabel = { anchor: "end", x: leftX, scale: 1 };
  const right: FittedLabel = { anchor: "start", x: rightX, scale: 1 };
  const fitsLeft = leftX - w >= 0;
  const fitsRight = rightX + w <= 600;
  if (prefer === "left" && fitsLeft) return left;
  if (fitsRight) return right;
  if (fitsLeft) return left;
  const roomLeft = leftX;
  const roomRight = 600 - rightX;
  return roomLeft >= roomRight ? { ...left, scale: roomLeft / w } : { ...right, scale: roomRight / w };
}

/** Co pokazuje mapa na stronie oferty. */
export type OfferMapMode =
  | { kind: "closed"; cities: string[] }
  | { kind: "remote" }
  | { kind: "focus"; cities: string[] }
  | { kind: "none" };

/**
 * Wybór mapy oferty: zamknięta rekrutacja = przerywany obrys (z miastem,
 * gdy je znamy); praca zdalna = cała mapa świeci; hybryda i biuro =
 * podświetlone miasta oferty. Miasto, którego nie umiemy postawić na mapie
 * („Polska”, „do ustalenia”), daje mapę bez podświetlenia.
 */
export function offerMapMode(
  status: "open" | "closed",
  params: Pick<CareerJobParams, "city" | "remote_policy"> | null,
  cityNames: (city: string | null) => string[],
): OfferMapMode {
  const cities = params?.remote_policy === "remote" ? [] : cityNames(params?.city ?? null).filter((c) => cityGeo(c));
  if (status === "closed") return { kind: "closed", cities };
  if (params?.remote_policy === "remote") return { kind: "remote" };
  if (cities.length > 0) return { kind: "focus", cities };
  return { kind: "none" };
}

/** Podpis pod podświetlonym miastem: „biuro 1 dzień w tygodniu”, „praca w biurze”. */
export function officeNote(params: Pick<CareerJobParams, "remote_policy" | "onsite_days_per_week" | "onsite_days_per_month"> | null): string | null {
  if (!params) return null;
  if (params.remote_policy === "onsite") return "praca w biurze";
  if (params.remote_policy !== "hybrid") return null;
  if (params.onsite_days_per_month) return `biuro ${params.onsite_days_per_month} dni w miesiącu`;
  const d = params.onsite_days_per_week;
  if (d) return `biuro ${d} ${d === 1 ? "dzień" : "dni"} w tygodniu`;
  return "praca hybrydowa";
}

/** „w ośmiu miastach” — liczba miast na pierwszym ekranie słowem (do 12), dalej cyfrą. */
const LOCATIVE = ["", "jednym", "dwóch", "trzech", "czterech", "pięciu", "sześciu", "siedmiu", "ośmiu", "dziewięciu", "dziesięciu", "jedenastu", "dwunastu"];
export function inCities(n: number): string | null {
  if (n <= 0) return null;
  if (n === 1) return "w jednym mieście";
  return `w ${LOCATIVE[n] ?? n} miastach`;
}

/** Czy miasto ma położenie na mapie (miasta spoza listy zostają w chipach). */
export function onMap(label: string): boolean {
  return cityGeo(label) !== null;
}

/** Ziarno rozmieszczenia migających punktów na mapie zdalnej (makieta O-zdalna). */
export const REMOTE_DOTS: readonly [number, number][] = [
  [80, 380], [130, 360], [190, 345], [260, 352], [320, 355], [390, 356], [450, 372], [488, 402],
  [150, 420], [220, 410], [300, 400], [370, 395], [440, 425], [490, 462], [110, 448], [200, 462],
  [270, 472], [340, 485], [410, 505], [475, 515], [525, 487], [300, 440], [240, 497], [380, 452],
];
