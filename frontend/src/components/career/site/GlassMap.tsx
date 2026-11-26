import type { Facet } from "@/lib/career/site";
import {
  LABEL_FONT,
  MAP_OUTLINE,
  REMOTE_DOTS,
  SLAB,
  buildCityMap,
  columnShape,
  points,
  type MapLabel,
} from "@/lib/career/polandMap";

import g from "./glass.module.css";

/**
 * Szklana mapa Polski (język A, makiety z 26.11.2026). Cztery odmiany:
 * kolumny miast z liczbami ofert (lista), podświetlone miasto oferty,
 * cała mapa świecąca (praca zdalna), przerywany obrys (zamknięta) i pusta,
 * przerywana kolumna (brak wyników). Geometria w `lib/career/polandMap.ts`.
 * `uid` rozróżnia gradienty, gdy na stronie stoją dwie mapy (desktop i telefon).
 */
interface MapBase {
  uid: string;
  className?: string;
}

const OUTLINE = points(MAP_OUTLINE);
/** Najniższa podświetlona kolumna oferty — podpis miasta ma stać nad płytą kraju. */
const LIT_MIN = 200;
const SLAB_PTS = points(MAP_OUTLINE, SLAB);

function safeId(uid: string): string {
  return uid.replace(/[^a-zA-Z0-9_-]/g, "");
}

function Defs({ id, dots = 11 }: { id: string; dots?: number }) {
  return (
    <defs>
      <linearGradient id={`${id}F`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.62" />
        <stop offset="1" stopColor="#FFFFFF" stopOpacity="0.10" />
      </linearGradient>
      <linearGradient id={`${id}R`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.30" />
        <stop offset="1" stopColor="#FFFFFF" stopOpacity="0.04" />
      </linearGradient>
      <linearGradient id={`${id}H`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#FFF4F0" stopOpacity="1" />
        <stop offset="1" stopColor="#FFD6C9" stopOpacity="0.55" />
      </linearGradient>
      <pattern id={`${id}D`} width={dots} height={dots} patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r={dots > 11 ? 1.3 : 1} fill="#FFFFFF" opacity="0.30" />
      </pattern>
      <clipPath id={`${id}C`}>
        <polygon points={OUTLINE} />
      </clipPath>
      <filter id={`${id}B`} x="-20%" y="-50%" width="140%" height="200%">
        <feGaussianBlur stdDeviation="16" />
      </filter>
    </defs>
  );
}

/** Płyta kraju: cień, dolna ściana, szklana góra i kropki. */
function Slab({ id }: { id: string }) {
  return (
    <>
      <ellipse cx="300" cy="520" rx="290" ry="62" fill="#4E0810" opacity="0.45" filter={`url(#${id}B)`} />
      <polygon points={SLAB_PTS} fill="#7A111B" stroke="#FFFFFF" strokeOpacity="0.25" strokeWidth="1" />
      <polygon points={OUTLINE} fill="#FFFFFF" fillOpacity="0.13" stroke="#FFFFFF" strokeOpacity="0.75" strokeWidth="1.3" />
      <rect x="0" y="300" width="600" height="280" fill={`url(#${id}D)`} clipPath={`url(#${id}C)`} />
    </>
  );
}

function Label({ l, phone }: { l: MapLabel; phone: boolean }) {
  const font = phone ? LABEL_FONT.phone : LABEL_FONT.desktop;
  const [x1, y1, x2, y2] = l.line;
  return (
    <g>
      <path d={`M${x1.toFixed(0)},${y1.toFixed(0)} L${x2.toFixed(0)},${y2.toFixed(0)}`} className={g.leader} />
      {l.size === "inline" ? (
        <text x={l.x} y={l.y} textAnchor={l.anchor} fontSize={font.inline} className={g.mapName}>
          <tspan className={g.mapNum}>{l.count}</tspan> {l.name}
        </text>
      ) : (
        <>
          <text x={l.x} y={l.y} textAnchor={l.anchor} fontSize={font[l.size]} className={g.mapNum}>
            {l.count}
          </text>
          <text x={l.x} y={l.y + font.name + 6} textAnchor={l.anchor} fontSize={font.name} className={g.mapName}>
            {l.name}
          </text>
        </>
      )}
    </g>
  );
}

/**
 * Lista ofert: kolumna na miasto, wysokość i liczba z tablicy, linie od
 * największego miasta. `phone` = większe etykiety tylko czterech największych.
 */
export function CityColumnsMap({ uid, facets, phone = false, className }: MapBase & { facets: readonly Facet[]; phone?: boolean }) {
  const id = safeId(uid);
  const map = buildCityMap(facets, { phone });
  const label = map.columns.length
    ? `Szklana mapa Polski. Otwarte rekrutacje według miast: ${map.summary}.`
    : "Szklana mapa Polski.";
  return (
    <svg viewBox={phone ? "0 70 600 520" : "0 60 600 540"} role="img" aria-label={label} className={`${g.map} ${className ?? ""}`}>
      <Defs id={id} dots={phone ? 13 : 11} />
      <Slab id={id} />
      <g className={g.flows}>
        {map.flows.map((d) => (
          <path key={d} d={d} className={g.flow} />
        ))}
      </g>
      {map.hub ? (
        <>
          <circle cx={map.hub[0]} cy={map.hub[1]} r="6" className={g.pulse} />
          <circle cx={map.hub[0]} cy={map.hub[1]} r="6" className={`${g.pulse} ${g.pulse2}`} />
        </>
      ) : null}
      <g className={g.cols}>
        {map.columns.map((c) => {
          const hot = map.hub !== null && c.foot === map.hub;
          return (
            <g key={c.id}>
              <polygon points={c.right} fill={hot ? "#FFD6C9" : `url(#${id}R)`} fillOpacity={hot ? 0.55 : 1} />
              <polygon points={c.front} fill={`url(#${id}${hot ? "H" : "F"})`} />
              <polygon points={c.top} fill="#FFFFFF" fillOpacity={hot ? 1 : 0.8} />
            </g>
          );
        })}
      </g>
      {map.labels.map((l) => (
        <Label key={l.id} l={l} phone={phone} />
      ))}
    </svg>
  );
}

/**
 * Strona oferty: kolumny tablicy przygaszone, miasta oferty podświetlone,
 * podpis z nazwą i trybem biura. Bez tablicy kolumna oferty stoi sama.
 */
export function OfferCityMap({
  uid,
  facets,
  cities,
  note,
  phone = false,
  className,
}: MapBase & { facets: readonly Facet[]; cities: readonly string[]; note: string | null; phone?: boolean }) {
  const id = safeId(uid);
  const known = buildCityMap(facets).columns;
  const lit = cities
    .map((name) => {
      const c = known.find((k) => k.label === name);
      if (c) return c;
      const alone = buildCityMap([{ id: name, label: name, count: 40 }]).columns[0];
      return alone ?? null;
    })
    .filter((c): c is NonNullable<typeof c> => c !== null);
  const faint = known.filter((k) => !cities.includes(k.label));
  const first = lit[0] ?? null;
  // Kolumna oferty nie bywa niższa niż 200 jednostek — ma być widać, gdzie jest biuro.
  const litShapes = lit.map((c) => ({ c, h: Math.max(c.height, LIT_MIN) }));
  const head = first ? first.base - Math.max(first.height, LIT_MIN) : 0;
  const font = phone ? { name: 36, note: 26 } : { name: 28, note: 18 };
  const labelX = first ? first.x - 36 : 0;
  const ariaCities = cities.join(", ");
  return (
    <svg
      viewBox="0 120 600 470"
      role="img"
      aria-label={`Mapa Polski z zaznaczonym miejscem pracy: ${ariaCities}${note ? `, ${note}` : ""}.`}
      className={`${g.map} ${className ?? ""}`}
    >
      <Defs id={id} />
      <Slab id={id} />
      <g opacity="0.3" stroke="#FFFFFF" strokeWidth="1">
        {faint.map((c) => (
          <g key={c.id}>
            <polygon points={c.front} fill={`url(#${id}F)`} />
            <polygon points={c.top} fill="#FFFFFF" />
          </g>
        ))}
      </g>
      {first ? (
        <>
          <circle cx={first.foot[0]} cy={first.foot[1]} r="6" className={g.pulse} />
          <circle cx={first.foot[0]} cy={first.foot[1]} r="6" className={`${g.pulse} ${g.pulse2}`} />
        </>
      ) : null}
      <g stroke="#FFFFFF" strokeWidth="1" strokeLinejoin="round">
        {litShapes.map(({ c, h }) => {
          const s = columnShape(c.x, c.base, h);
          return (
            <g key={c.id}>
              <polygon points={s.right} fill="#FFD6C9" fillOpacity="0.55" />
              <polygon points={s.front} fill={`url(#${id}H)`} />
              <polygon points={s.top} fill="#FFFFFF" />
            </g>
          );
        })}
      </g>
      {first ? (
        <>
          <path d={`M${first.x - 2},${head + 15} L${labelX + 8},${head + 15}`} className={g.leader} />
          <text x={labelX} y={head + 9} textAnchor="end" fontSize={font.name} className={g.mapNum}>
            {cities.join(", ")}
          </text>
          {note ? (
            <text x={labelX} y={head + 9 + font.note + 8} textAnchor="end" fontSize={font.note} className={g.mapName}>
              {note}
            </text>
          ) : null}
        </>
      ) : null}
    </svg>
  );
}

/** Praca zdalna: cała płyta świeci, punkty migają w całym kraju. */
export function RemoteMap({ uid, className }: MapBase) {
  const id = safeId(uid);
  return (
    <svg viewBox="0 250 600 360" role="img" aria-label="Cała mapa Polski świeci: pracujesz zdalnie, z dowolnego miejsca w kraju." className={`${g.map} ${className ?? ""}`}>
      <Defs id={id} />
      <ellipse cx="290" cy="450" rx="300" ry="120" fill="#FFD6C9" opacity="0.35" filter={`url(#${id}B)`} />
      <polygon points={SLAB_PTS} fill="#F3B9A8" stroke="#FFFFFF" strokeOpacity="0.5" />
      <polygon points={OUTLINE} fill="#FFF4F0" fillOpacity="0.92" stroke="#FFFFFF" strokeWidth="1.5" />
      <g fill="#C42329">
        {REMOTE_DOTS.map(([x, y], i) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="4" className={`${g.twinkle} ${g[`tw${i % 4}`]}`} />
        ))}
      </g>
      <text x="300" y="290" textAnchor="middle" fontSize="30" className={g.mapNum}>
        Zdalnie z całej Polski
      </text>
    </svg>
  );
}

/** Zamknięta rekrutacja: przerywany obrys i przerywana kolumna miasta. */
export function ClosedMap({ uid, cities, className }: MapBase & { cities: readonly string[] }) {
  const first = cities.length > 0 ? buildCityMap([{ id: cities[0], label: cities[0], count: 30 }]).columns[0] : null;
  void uid;
  return (
    <svg viewBox="0 300 600 290" aria-hidden="true" className={`${g.map} ${className ?? ""}`}>
      <polygon points={OUTLINE} fill="#FFFFFF" fillOpacity="0.10" stroke="#FFFFFF" strokeOpacity="0.5" strokeWidth="1.3" />
      {first ? (
        <>
          <g fill="none" stroke="#FFFFFF" strokeOpacity="0.7" strokeWidth="1.4" strokeDasharray="5 5">
            <polygon points={columnShape(first.x, first.base, 90).front} />
            <polygon points={columnShape(first.x, first.base, 90).top} />
          </g>
          <text x={first.x + 34} y={first.base - 86} fontSize="28" className={g.mapMono}>
            {cities.join(", ")} · zamknięta
          </text>
        </>
      ) : null}
    </svg>
  );
}

/** Brak wyników: jasna mapa i pusta, przerywana kolumna „<hasło>: 0”. */
export function GhostMap({ uid, word, className }: MapBase & { word: string }) {
  const id = safeId(uid);
  const s = columnShape(278, 452, 122);
  return (
    <svg viewBox="0 280 600 320" role="img" aria-label={`Mapa Polski z pustym miejscem na kolumnę: dziś nie ma projektu z ${word}.`} className={`${g.map} ${className ?? ""}`}>
      <defs>
        <linearGradient id={`${id}E`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#C42329" stopOpacity="0.25" />
          <stop offset="1" stopColor="#C42329" stopOpacity="0.04" />
        </linearGradient>
      </defs>
      <polygon points={SLAB_PTS} fill="#E6D6D3" />
      <polygon points={OUTLINE} fill="#FFFFFF" stroke="#C4B2B4" strokeWidth="1.3" />
      <g className={g.ghost} fill={`url(#${id}E)`} stroke="#C42329" strokeWidth="1.6">
        <polygon points={s.front} />
        <polygon points={s.top} />
      </g>
      <text x="312" y="342" fontSize="30" className={g.ghostText}>
        {word}: 0
      </text>
    </svg>
  );
}
