/**
 * Kadr grafiki Open Graph strony kariery w języku A (makiety OG-lista,
 * OG-oferta, OG-zdalna, 26.11.2026): czerwone pole, logo i tytuł przy lewej
 * krawędzi (portale tną obrazek do kwadratowej miniatury od lewej), po prawej
 * szklana mapa Polski. Bez udawanych przycisków. Tylko style inline
 * i `display: flex` (wymóg satori), bez zależności od Node.
 *
 * Mapa to obrazek SVG (`lib/career/mapSvg.ts`), a napisy na niej stoją jako
 * zwykłe bloki, bo tekst w obrazku SVG nie dostaje fontów satori.
 */
import { svgDataUri, type MapSvg } from "@/lib/career/mapSvg";
import { mapLabelColumn, type MapLabel } from "@/lib/career/polandMap";

import { B2BLogo } from "./B2BLogo";

const W = 1200;
const H = 630;
const BG =
  "radial-gradient(circle at 76% 56%, rgba(255,214,201,0.30) 0%, rgba(255,214,201,0) 42%), linear-gradient(90deg, #961621 0%, #C42329 52%, #D43424 100%)";
const SOFT = "#FFE3DA";
const RED_TEXT = "#B0222A";
const TEXT = "Source Sans 3, system-ui, sans-serif";

/** Gdzie stoi mapa na kadrze (px) — z tego liczymy pozycje napisów. */
interface Placed {
  map: MapSvg;
  left: number;
  top: number;
  width: number;
}

function toPx(p: Placed, x: number, y: number): [number, number] {
  const k = p.width / p.map.view[2];
  return [p.left + (x - p.map.view[0]) * k, p.top + (y - p.map.view[1]) * k];
}

function MapImage({ p }: { p: Placed }) {
  const height = Math.round((p.width * p.map.view[3]) / p.map.view[2]);
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={svgDataUri(p.map.svg)}
      width={p.width}
      height={height}
      alt=""
      style={{ position: "absolute", left: p.left, top: p.top, width: p.width, height }}
    />
  );
}

/** Napis przy punkcie mapy: `anchor` jak w SVG (start = od punktu w prawo). */
function At({
  p,
  x,
  y,
  size,
  anchor,
  children,
}: {
  p: Placed;
  x: number;
  y: number;
  size: number;
  anchor: "start" | "end";
  children: React.ReactNode;
}) {
  const k = p.width / p.map.view[2];
  const [px, py] = toPx(p, x, y);
  const top = Math.round(py - size * k * 0.92);
  const side = anchor === "start" ? { left: Math.round(px) } : { right: Math.round(W - px) };
  return <div style={{ position: "absolute", top, display: "flex", whiteSpace: "nowrap", ...side }}>{children}</div>;
}

const OG_FONT = { big: 44, mid: 32, inline: 20, name: 22 } as const;

function CityLabel({ p, l }: { p: Placed; l: MapLabel }) {
  const k = p.width / p.map.view[2];
  if (l.size === "inline") {
    return (
      <At p={p} x={l.x} y={l.y} size={OG_FONT.inline} anchor={l.anchor}>
        <span style={{ fontFamily: TEXT, fontWeight: 600, fontSize: OG_FONT.inline * k, color: SOFT }}>
          {l.count} {l.name}
        </span>
      </At>
    );
  }
  const num = l.size === "big" ? OG_FONT.big : OG_FONT.mid;
  return (
    <At p={p} x={l.x} y={l.y} size={num} anchor={l.anchor}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: l.anchor === "end" ? "flex-end" : "flex-start" }}>
        <span style={{ fontFamily: "Montserrat", fontWeight: 800, fontSize: num * k, lineHeight: 1, letterSpacing: -1 }}>
          {l.count}
        </span>
        <span style={{ fontFamily: TEXT, fontWeight: 600, fontSize: OG_FONT.name * k, lineHeight: 1.2, color: SOFT }}>
          {l.name}
        </span>
      </div>
    </At>
  );
}

function Frame({ host, children }: { host: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        width: W,
        height: H,
        position: "relative",
        display: "flex",
        overflow: "hidden",
        backgroundColor: "#C42329",
        backgroundImage: BG,
        color: "#FFFFFF",
        fontFamily: TEXT,
      }}
    >
      <div style={{ position: "absolute", left: 64, top: 52, display: "flex" }}>
        <B2BLogo variant="white" height={48} />
      </div>
      {children}
      <div style={{ position: "absolute", left: 64, bottom: 46, display: "flex", fontSize: 24, fontWeight: 600, color: SOFT }}>
        {host}
      </div>
    </div>
  );
}

/** Lista ofert: hasło, liczba otwartych rekrutacji, mapa miast z danymi. */
export function OgListCard({
  openLabel,
  cityLine,
  map,
  labels,
  host,
}: {
  /** „101 otwartych rekrutacji IT”; `null` (awaria API) = bez liczby. */
  openLabel: string | null;
  /** „Zdalnie, hybrydowo i w biurze w ośmiu miastach”. */
  cityLine: string;
  map: MapSvg | null;
  labels: readonly MapLabel[];
  host: string;
}) {
  const p: Placed | null = map ? { map, left: 590, top: 48, width: 590 } : null;
  return (
    <Frame host={host}>
      <div style={{ position: "absolute", left: 64, top: 150, width: 560, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 60, lineHeight: 1.02, letterSpacing: -2.4 }}>
          Dołącz do projektów, które muszą działać.
        </div>
        {openLabel ? (
          <div style={{ display: "flex", marginTop: 26, fontSize: 32, fontWeight: 600, lineHeight: 1.25 }}>{openLabel}</div>
        ) : null}
        <div style={{ display: "flex", marginTop: openLabel ? 6 : 26, fontSize: 24, lineHeight: 1.35, color: SOFT }}>{cityLine}</div>
      </div>
      {p ? <MapImage p={p} /> : null}
      {p ? labels.map((l) => <CityLabel key={l.id} p={p} l={l} />) : null}
    </Frame>
  );
}

export type OgOfferMap =
  | { kind: "focus"; map: MapSvg; lit: { x: number; base: number; height: number }[]; cities: string; note: string | null }
  | { kind: "remote"; map: MapSvg }
  | { kind: "closed"; map: MapSvg }
  | { kind: "none" };

const TITLE_SIZES = [96, 80, 64, 54, 46, 40] as const;

/** Liczba linii tytułu po zawinięciu po słowach (szacunek szerokości Montserrat 800). */
function titleLines(title: string, size: number, width: number): number {
  const per = size * 0.62;
  let lines = 1;
  let used = 0;
  for (const word of title.trim().split(/\s+/)) {
    const w = word.length * per;
    const add = used === 0 ? w : used + per * 0.3 + w;
    if (add <= width || used === 0) used = add;
    else {
      lines += 1;
      used = w;
    }
  }
  return lines;
}

/**
 * Największy rozmiar tytułu, przy którym mieści się w miejscu nad linią
 * „{miasto} · {tryb} · B2B” — bez nachodzenia na adres w stopce kadru.
 */
export function ogOfferTitleSize(title: string, width = 590, height = 212): number {
  for (const size of TITLE_SIZES) {
    if (titleLines(title, size, width) * size * 0.98 <= height) return size;
  }
  return TITLE_SIZES[TITLE_SIZES.length - 1];
}

/** Oferta: technologie, stanowisko, „{miasto} · {tryb} · B2B”, mapa z miastem albo cała świecąca. */
export function OgOfferCard({
  tags,
  title,
  line,
  sub,
  status,
  map,
  host,
}: {
  tags: readonly string[];
  title: string;
  line: string | null;
  sub: string | null;
  /** Plakietka zamiast technologii (zamknięta rekrutacja). */
  status?: string | null;
  map: OgOfferMap;
  host: string;
}) {
  const placed: Placed | null =
    map.kind === "focus"
      ? { map: map.map, left: 640, top: 96, width: 540 }
      : map.kind === "remote"
        ? { map: map.map, left: 640, top: 160, width: 540 }
        : map.kind === "closed"
          ? { map: map.map, left: 680, top: 230, width: 480 }
          : null;
  const textWidth = placed ? 590 : 1000;
  const chips = status ? [status] : tags;
  const label =
    map.kind === "focus"
      ? mapLabelColumn(map.lit, [{ text: map.cities, size: 34 }, ...(map.note ? [{ text: map.note, size: 22 }] : [])])
      : null;
  const first = label?.column ?? null;
  const fit = label?.fit ?? null;
  const head = first ? first.base - first.height : 0;
  // Miejsce na tytuł: od y = 160 do 16 px nad adresem (y ≈ 554), minus plakietki
  // (68), linia „miasto · tryb · B2B” (62) i druga linia (36), gdy są.
  const titleSize = ogOfferTitleSize(title, textWidth, 212 + (sub ? 0 : 36) + (chips.length ? 0 : 68) + (line ? 0 : 62));
  return (
    <Frame host={host}>
      <div style={{ position: "absolute", left: 64, top: 160, width: textWidth, display: "flex", flexDirection: "column" }}>
        {chips.length > 0 ? (
          <div style={{ display: "flex", gap: 10, marginBottom: 22 }}>
            {chips.map((t, i) => (
              <div
                key={t}
                style={{
                  display: "flex",
                  padding: "6px 14px",
                  borderRadius: 4,
                  fontSize: 24,
                  fontWeight: 600,
                  ...(i === 0 ? { background: "#FFFFFF", color: RED_TEXT } : { border: "2px solid rgba(255,255,255,0.7)" }),
                }}
              >
                {t}
              </div>
            ))}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            fontFamily: "Montserrat",
            fontWeight: 800,
            fontSize: titleSize,
            lineHeight: 0.98,
            letterSpacing: -2.5,
          }}
        >
          {title}
        </div>
        {line ? <div style={{ display: "flex", marginTop: 22, fontSize: 32, fontWeight: 600, lineHeight: 1.25 }}>{line}</div> : null}
        {sub ? <div style={{ display: "flex", marginTop: 6, fontSize: 24, color: SOFT }}>{sub}</div> : null}
      </div>
      {placed ? <MapImage p={placed} /> : null}
      {placed && fit && map.kind === "focus" ? (
        <At p={placed} x={fit.x} y={head + 9} size={34 * fit.scale} anchor={fit.anchor}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: fit.anchor === "end" ? "flex-end" : "flex-start" }}>
            <span style={{ fontFamily: "Montserrat", fontWeight: 800, fontSize: 34 * fit.scale * (placed.width / 600), lineHeight: 1.05 }}>
              {map.cities}
            </span>
            {map.note ? (
              <span style={{ fontWeight: 600, fontSize: 22 * fit.scale * (placed.width / 600), color: SOFT }}>{map.note}</span>
            ) : null}
          </div>
        </At>
      ) : null}
    </Frame>
  );
}

