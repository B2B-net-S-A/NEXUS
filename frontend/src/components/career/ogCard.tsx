/**
 * Kadr grafiki Open Graph strony kariery (1200×630) — rysuje go `next/og`
 * (trasy `opengraph-image.tsx`, fonty w `og.tsx`) i podgląd posta w NEXUSIE
 * (`LinkedInPreviewCard`, przeskalowany), więc rekruter widzi przed
 * udostępnieniem dokładnie to, co pokaże LinkedIn. Tylko style inline
 * i `display: flex` (wymóg satori), bez zależności od Node.
 *
 * Od 24.11.2026 jeden wygląd jak nagłówek oferty na nowej stronie kariery
 * (wariant G1 „Czerwona”, decyzja Artura; od 25.11.2026 w gradiencie wariantu 5): czerwone tło, wielkie słowo,
 * tytuł, fakty w jednej linii i biały przycisk. Trzy dawne szablony (Grafit,
 * Terminal, Jasny) nie zmieniają już grafiki.
 */
import { remoteLabel } from "@/lib/career/format";

import { B2BLogo } from "./B2BLogo";

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

// Wariant 5 „Czerwień w gradientach tech” (decyzja Artura 25.11.2026): czerwień
// #C42329 w gradiencie bordo › czerwień › ciepły blask jak nagłówek strony,
// morelowa plakietka zamiast limonki (limonka zostaje tylko w DYNAMINDS Labs).
const C = {
  red: "#C42329",
  redText: "#B0222A",
  ink: "#1F1115",
  white: "#FFFFFF",
  accent: "#FFD6C9",
};
const RED_TECH = "linear-gradient(90deg, #961621 0%, #C42329 52%, #D43424 100%)";

const TEXT = "Source Sans 3, system-ui, sans-serif";

/** Wielkie słowo nad tytułem (krótka umiejętność z tablicy, „Python”). */
export function ogWordSize(word: string): number {
  const n = word.length;
  if (n <= 4) return 210;
  if (n <= 7) return 170;
  if (n <= 10) return 130;
  return 104;
}

/** Tytuł: z wielkim słowem mniejszy, bez niego jest głównym napisem. */
export function ogTitleSize(title: string, withWord = false): number {
  const n = title.length;
  if (withWord) return n <= 30 ? 52 : n <= 50 ? 44 : 38;
  if (n <= 24) return 96;
  if (n <= 40) return 78;
  if (n <= 60) return 64;
  return 54;
}

/** Kadr 1200×630: logo i status, wielkie słowo, tytuł, fakty, adres i przycisk. */
export function OgCard({
  status,
  kicker,
  word,
  title,
  facts = [],
  person,
  foot,
  host,
}: {
  /** Plakietka w prawym górnym rogu; `closed` = obrys zamiast morelowego tła. */
  status?: { label: string; closed?: boolean } | null;
  /** Mały napis nad tytułem, gdy nie ma wielkiego słowa ani osoby. */
  kicker?: string | null;
  /** Krótka umiejętność z tablicy („Python”); bez niej sam tytuł. */
  word?: string | null;
  title: string;
  /** Do trzech faktów (Lokalizacja, Tryb pracy, Umowa) — w jednej linii. */
  facts?: OgFact[];
  /** Strona rekrutera: inicjał i podpis nad tytułem. */
  person?: { initial: string; name: string } | null;
  /** Napis na białym przycisku, np. „Wyślij CV →”. */
  foot: string;
  host: string;
}) {
  const w = word?.trim() || null;
  const factsLine = facts
    .slice(0, 3)
    .map((f) => f.value)
    .join(" · ");
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        backgroundColor: C.red,
        backgroundImage: RED_TECH,
        color: C.white,
        padding: "48px 64px 44px",
        fontFamily: TEXT,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <B2BLogo variant="white" height={50} />
        {status ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              height: 44,
              padding: "0 20px",
              borderRadius: 999,
              backgroundColor: status.closed ? "transparent" : C.accent,
              border: status.closed ? `2px solid ${C.white}` : "none",
              color: status.closed ? C.white : C.ink,
              fontFamily: "Montserrat",
              fontWeight: 600,
              fontSize: 21,
            }}
          >
            {status.label}
          </div>
        ) : null}
      </div>

      <div style={{ display: "flex", flexDirection: "column", flexGrow: 1, justifyContent: "center" }}>
        {person ? (
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 999,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: C.white,
                color: C.redText,
                fontFamily: "Montserrat",
                fontWeight: 800,
                fontSize: 32,
              }}
            >
              {person.initial}
            </div>
            <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 600, fontSize: 30 }}>{person.name}</div>
          </div>
        ) : !w && kicker ? (
          <div style={{ display: "flex", marginBottom: 12, fontFamily: "Montserrat", fontWeight: 600, fontSize: 28 }}>
            {kicker}
          </div>
        ) : null}
        {w ? (
          <div
            style={{
              display: "flex",
              fontFamily: "Montserrat",
              fontWeight: 800,
              fontSize: ogWordSize(w),
              lineHeight: 0.92,
              letterSpacing: "-0.055em",
              marginLeft: -6,
              whiteSpace: "nowrap",
            }}
          >
            {w}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            marginTop: w ? 14 : 0,
            maxWidth: 1060,
            fontFamily: "Montserrat",
            fontWeight: w ? 600 : 800,
            fontSize: ogTitleSize(title, Boolean(w)),
            lineHeight: 1.1,
            letterSpacing: "-0.03em",
          }}
        >
          {title}
        </div>
        {factsLine ? (
          <div style={{ display: "flex", marginTop: 16, fontSize: 30, fontWeight: 600 }}>{factsLine}</div>
        ) : null}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 18 }}>
        <div style={{ display: "flex", fontSize: 26, fontWeight: 600 }}>{host}</div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            height: 60,
            padding: "0 28px",
            borderRadius: 10,
            backgroundColor: C.white,
            color: C.redText,
            fontFamily: "Montserrat",
            fontWeight: 800,
            fontSize: 28,
          }}
        >
          {foot}
        </div>
      </div>
    </div>
  );
}
