/**
 * Kadr grafiki Open Graph strony kariery (1200×630) w barwach marki — rysuje
 * go `next/og` (trasy `opengraph-image.tsx`, fonty w `og.tsx`) i podgląd posta
 * w NEXUSIE (`LinkedInPreviewCard`, przeskalowany), więc rekruter widzi przed
 * udostępnieniem dokładnie to, co pokaże LinkedIn. Tylko style inline
 * i `display: flex` (wymóg satori), bez zależności od Node.
 */
import { remoteLabel } from "@/lib/career/format";

import { B2BLogo } from "./B2BLogo";
import { careerTheme, type ThemePalette } from "./themes";

export interface OgFact {
  label: string;
  value: string;
}

/** Parametry rekrutacji potrzebne do kafli (odpowiedź publiczna i podgląd w NEXUSIE). */
export interface OgJobParams {
  city?: string | null;
  remote_policy?: "remote" | "hybrid" | "onsite" | null;
  contract?: string | null;
}

/**
 * Kafle grafiki rekrutacji: Lokalizacja, Tryb pracy, Umowa — każdy w jednej
 * linii („Warszawa, Łódź, Gdynia” → „Warszawa +2”). Zdalnie = bez miasta.
 */
export function ogJobTiles(params: OgJobParams | null | undefined): OgFact[] {
  if (!params) return [];
  const tiles: OgFact[] = [];
  const cities = (params.city ?? "").split(/\s*,\s*/).filter(Boolean);
  if (cities.length > 0 && params.remote_policy !== "remote") {
    tiles.push({
      label: "Lokalizacja",
      value: cities.length > 1 ? `${cities[0]} +${cities.length - 1}` : cities[0],
    });
  }
  const mode = remoteLabel(params.remote_policy);
  if (mode) tiles.push({ label: "Tryb pracy", value: mode.charAt(0).toLocaleUpperCase("pl-PL") + mode.slice(1) });
  const contract = params.contract?.trim();
  if (contract) tiles.push({ label: "Umowa", value: contract });
  return tiles;
}

/** Rozmiar tytułu wg długości — najdłuższe tytuły rekrutacji mają ok. 60 znaków. */
export function ogTitleSize(title: string): number {
  const n = title.length;
  if (n <= 22) return 100;
  if (n <= 34) return 86;
  if (n <= 48) return 74;
  if (n <= 64) return 64;
  return 56;
}

/**
 * Ostatnie słowo w czerwieni marki — tylko słowo z liter (jak tytuł strony
 * w szablonach); numer albo kod na końcu zostaje w kolorze tytułu.
 */
export function ogTitleWords(title: string): { word: string; red: boolean }[] {
  const words = title.trim().split(/\s+/).filter(Boolean);
  const last = words[words.length - 1] ?? "";
  const redLast = words.length > 1 && /^[\p{L}-]+[.!?]?$/u.test(last);
  return words.map((word, i) => ({ word, red: redLast && i === words.length - 1 }));
}

/** Kafle i karty — te same odcienie co `brandPage.module.css`. */
function cardColors(p: ThemePalette) {
  return p.light
    ? { card: "#FFFFFF", coal: "#E1E1E1", glow: "rgba(231,55,72,0.14)" }
    : { card: "#242424", coal: "#3A3A3A", glow: "rgba(231,55,72,0.32)" };
}

/** Kadr 1200×630: logo i status, duży tytuł, kafle faktów, adres i wezwanie. */
export function OgCard({
  theme,
  status,
  kicker,
  title,
  facts = [],
  person,
  foot,
  host,
}: {
  /** Szablon rekrutacji (`themes.ts`); nieznany = Grafit. */
  theme?: string | null;
  /** Plakietka w prawym górnym rogu; `closed` = pusta kropka. */
  status?: { label: string; closed?: boolean } | null;
  kicker?: string | null;
  title: string;
  /** Do trzech kafli: Lokalizacja, Tryb pracy, Umowa. */
  facts?: OgFact[];
  /** Strona rekrutera: inicjał i imię nad tytułem zamiast `kicker`. */
  person?: { initial: string; name: string } | null;
  /** Zdanie w stopce po prawej (czerwone), np. „Aplikuj w 2 minuty →”. */
  foot: string;
  host: string;
}) {
  const p = careerTheme(theme);
  const c = cardColors(p);
  const size = ogTitleSize(title);
  const tiles = facts.slice(0, 3);
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        backgroundColor: p.bg,
        backgroundImage: `radial-gradient(circle at 92% 0%, ${c.glow} 0%, transparent 46%)`,
        padding: "48px 64px 44px",
        fontFamily: "Source Sans 3",
        color: p.text,
      }}
    >
      {/* Łuki znaku B2B za treścią, jak w szablonie Grafit. */}
      <svg
        width="420"
        height="485"
        viewBox="0 0 520 600"
        style={{ position: "absolute", right: -40, top: 40, opacity: p.light ? 0.12 : 0.18 }}
      >
        <path
          d="M30 40 H300 A125 125 0 0 1 300 290 H170 M170 290 H330 A140 140 0 0 1 330 570 H30"
          fill="none"
          stroke={p.decor}
          strokeWidth="34"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <B2BLogo variant={p.light ? "color" : "onDark"} height={52} />
        {status ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              height: 48,
              padding: "0 22px",
              borderRadius: 999,
              border: `2px solid ${c.coal}`,
              backgroundColor: c.card,
              fontFamily: "Montserrat",
              fontWeight: 600,
              fontSize: 22,
              color: p.text,
            }}
          >
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: 999,
                backgroundColor: status.closed ? "transparent" : p.decor,
                border: status.closed ? `3px solid ${p.muted}` : "none",
              }}
            />
            {status.label}
          </div>
        ) : null}
      </div>

      <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {person ? (
          <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 22 }}>
            <div
              style={{
                width: 72,
                height: 72,
                borderRadius: 999,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: p.btn,
                color: p.btnText,
                fontFamily: "Montserrat",
                fontWeight: 800,
                fontSize: 36,
              }}
            >
              {person.initial}
            </div>
            <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 600, fontSize: 30, color: p.heading }}>
              {person.name}
            </div>
          </div>
        ) : kicker ? (
          <div
            style={{
              display: "flex",
              marginBottom: 14,
              fontFamily: "Montserrat",
              fontWeight: 600,
              fontSize: 28,
              color: p.accent,
            }}
          >
            {kicker}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            maxWidth: 1000,
            fontFamily: "Montserrat",
            fontWeight: 800,
            fontSize: size,
            lineHeight: 1.06,
            letterSpacing: "-0.025em",
            color: p.heading,
          }}
        >
          {ogTitleWords(title).map(({ word, red }, i) => (
            <span key={i} style={{ marginRight: "0.24em", color: red ? p.title : p.heading }}>
              {word}
            </span>
          ))}
        </div>
      </div>

      {tiles.length > 0 ? (
        <div style={{ display: "flex", gap: 16, marginBottom: 26 }}>
          {tiles.map((f) => (
            <div
              key={f.label}
              style={{
                flex: 1,
                minWidth: 0,
                display: "flex",
                flexDirection: "column",
                padding: "16px 22px 18px",
                borderRadius: 20,
                backgroundColor: c.card,
                border: `2px solid ${c.coal}`,
              }}
            >
              <div style={{ display: "flex", fontSize: 22, color: p.muted }}>{f.label}</div>
              <div
                style={{
                  display: "block",
                  fontFamily: "Montserrat",
                  fontWeight: 800,
                  fontSize: 34,
                  color: p.heading,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {f.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", fontSize: 26, color: p.muted }}>{host}</div>
        <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 28, color: p.accent }}>
          {foot}
        </div>
      </div>
    </div>
  );
}
