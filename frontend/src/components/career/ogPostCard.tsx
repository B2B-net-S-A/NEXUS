/**
 * Grafika posta na LinkedInie 1080×1350 (4:5 — największy kadr, jaki LinkedIn
 * pokazuje w feedzie na telefonie). Decyzja Artura 27.11.2026: warianty
 * „Mapa” (domyślny, język strony kariery), „Konkrety” i karuzela PDF.
 * Link idzie w pierwszym komentarzu, więc grafika nie udaje przycisku, tylko
 * mówi, gdzie jest link. Dane: `buildPostData` (`lib/career/postGraphic.ts`).
 * Rysuje to `next/og` (trasa `kariera/r/[slug]/grafika-posta`) i podgląd
 * w oknie „Udostępnij” — tylko style inline i `display: flex` (wymóg satori).
 */
import { svgDataUri } from "@/lib/career/mapSvg";
import { mapLabelColumn } from "@/lib/career/polandMap";
import type { CarouselSlide, PostData, PostMap } from "@/lib/career/postGraphic";

import { B2BLogo } from "./B2BLogo";

export const POST_SIZE = { width: 1080, height: 1350 };
const W = 1080;
const H = 1350;
const BG =
  "radial-gradient(circle at 70% 72%, rgba(255,214,201,0.30) 0%, rgba(255,214,201,0) 45%), linear-gradient(160deg, #961621 0%, #C42329 52%, #D43424 100%)";
const SOFT = "#FFE3DA";
const RED = "#C42329";
const RED_TEXT = "#B0222A";
const INK = "#1F1115";
const SNOW = "#F5F4EC";
const TEXT = "Source Sans 3, system-ui, sans-serif";
const PAD = 80;

function countLines(text: string, size: number, width: number): number {
  const per = size * 0.62;
  let lines = 1;
  let used = 0;
  for (const word of text.trim().split(/\s+/)) {
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

function fitSize(text: string, sizes: readonly number[], width: number, maxLines: number): number {
  for (const size of sizes) if (countLines(text, size, width) <= maxLines) return size;
  return sizes[sizes.length - 1];
}

function Frame({ children, light = false }: { children: React.ReactNode; light?: boolean }) {
  return (
    <div
      style={{
        width: W,
        height: H,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        backgroundColor: light ? SNOW : RED,
        ...(light ? {} : { backgroundImage: BG }),
        color: light ? INK : "#FFFFFF",
        fontFamily: TEXT,
      }}
    >
      {children}
    </div>
  );
}

function Logo({ light = false }: { light?: boolean }) {
  return (
    <div style={{ position: "absolute", left: PAD, top: 72, display: "flex" }}>
      <B2BLogo variant={light ? "color" : "white"} height={52} />
    </div>
  );
}

function Foot({ text, host, light = false, right }: { text: string; host: string; light?: boolean; right?: string }) {
  return (
    <div
      style={{
        position: "absolute",
        left: PAD,
        right: PAD,
        bottom: 64,
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        borderTop: `2px solid ${light ? "rgba(31,17,21,0.15)" : "rgba(255,255,255,0.35)"}`,
        paddingTop: 26,
      }}
    >
      <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 34, color: light ? RED_TEXT : "#FFFFFF" }}>
        {text}
      </div>
      <div style={{ display: "flex", fontSize: 26, fontWeight: 600, color: light ? "rgba(31,17,21,0.6)" : SOFT }}>
        {right ?? host}
      </div>
    </div>
  );
}

function Chips({ items, onRed = true }: { items: string[]; onRed?: boolean }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
      {items.map((t, i) => (
        <div
          key={t}
          style={{
            display: "flex",
            padding: "8px 18px",
            borderRadius: 6,
            fontSize: 28,
            fontWeight: 600,
            ...(onRed
              ? i === 0
                ? { background: "#FFFFFF", color: RED_TEXT }
                : { border: "2px solid rgba(255,255,255,0.7)" }
              : { background: "#FFFFFF", color: INK, border: "2px solid rgba(31,17,21,0.12)" }),
          }}
        >
          {t}
        </div>
      ))}
    </div>
  );
}

function PostMapBlock({ map, width, bottom }: { map: PostMap; width: number; bottom: number }) {
  if (map.kind === "none") return null;
  const view = map.map.view;
  const k = width / view[2];
  const height = Math.round(view[3] * k);
  const left = Math.round((W - width) / 2) + 60;
  const top = bottom - height;
  let label: React.ReactNode = null;
  const placed =
    map.kind === "focus"
      ? mapLabelColumn(map.lit, [{ text: map.cities, size: 34 }, ...(map.note ? [{ text: map.note, size: 22 }] : [])])
      : null;
  if (map.kind === "focus" && placed) {
    const { column: first, fit } = placed;
    const px = left + (fit.x - view[0]) * k;
    const py = top + (first.base - first.height + 9 - view[1]) * k;
    const size = 34 * fit.scale * k;
    const side = fit.anchor === "start" ? { left: Math.round(px) } : { right: Math.round(W - px) };
    label = (
      <div style={{ position: "absolute", top: Math.round(py - size * 0.92), display: "flex", flexDirection: "column", alignItems: fit.anchor === "end" ? "flex-end" : "flex-start", ...side }}>
        <span style={{ fontFamily: "Montserrat", fontWeight: 800, fontSize: size, lineHeight: 1.05 }}>{map.cities}</span>
        {map.note ? <span style={{ fontWeight: 600, fontSize: 22 * fit.scale * k, color: SOFT }}>{map.note}</span> : null}
      </div>
    );
  }
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={svgDataUri(map.map.svg)} width={width} height={height} alt="" style={{ position: "absolute", left, top, width, height }} />
      {label}
    </>
  );
}

/** A „Mapa”: język strony kariery w pionie — technologie, stanowisko, linia faktów, mapa. */
export function PostCardMap({ d, foot = "Link do aplikacji w komentarzu ↓", footRight }: { d: PostData; foot?: string; footRight?: string }) {
  const size = fitSize(d.title, [120, 104, 92, 80, 68, 60], W - 2 * PAD, 3);
  // Mapa dostaje miejsce, które zostaje pod tekstem (długi tytuł = mniejsza mapa).
  const textBottom =
    190 + (d.tags.length ? 90 : 0) + countLines(d.title, size, W - 2 * PAD) * size * 0.98 + (d.line ? 78 : 0) + (d.sub ? 44 : 0);
  const room = 1190 - textBottom - 30;
  const ratio = d.map.kind === "none" ? 1 : d.map.map.view[3] / d.map.map.view[2];
  const mapWidth = Math.min(d.map.kind === "remote" ? 640 : 700, Math.round(room / ratio));
  return (
    <Frame>
      <Logo />
      <div style={{ position: "absolute", left: PAD, top: 190, width: W - 2 * PAD, display: "flex", flexDirection: "column" }}>
        {d.tags.length ? (
          <div style={{ display: "flex", marginBottom: 30 }}>
            <Chips items={d.tags} />
          </div>
        ) : null}
        <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: size, lineHeight: 0.98, letterSpacing: -3 }}>{d.title}</div>
        {d.line ? <div style={{ display: "flex", marginTop: 30, fontSize: 40, fontWeight: 600 }}>{d.line}</div> : null}
        {d.sub ? <div style={{ display: "flex", marginTop: 8, fontSize: 30, color: SOFT }}>{d.sub}</div> : null}
      </div>
      {mapWidth >= 380 ? <PostMapBlock map={d.map} width={mapWidth} bottom={1190} /> : null}
      <Foot text={foot} host={d.host} right={footRight} />
    </Frame>
  );
}

/** B „Konkrety”: wielkie słowo na czerwieni, na dole jasny pas z tym, co robisz i czego szukamy. */
export function PostCardFacts({ d }: { d: PostData }) {
  const word = d.word;
  const wordSize = word ? (word.length <= 4 ? 230 : word.length <= 7 ? 190 : word.length <= 10 ? 150 : 118) : 0;
  const titleSize = fitSize(d.title, word ? [64, 56, 48, 42] : [104, 92, 80, 68, 60], W - 2 * PAD, 2);
  // Trzy długie obowiązki (po dwie linie) zepchnęłyby technologie na stopkę.
  const duties = d.duties.slice(0, d.duties.slice(0, 3).join("").length > 170 ? 2 : 3);
  // Jasny pas zaczyna się tuż pod tekstem na czerwieni (bez pustego pola).
  const redBottom =
    160 + 44 + (word ? wordSize * 0.95 + 10 : 4) + countLines(d.title, titleSize, W - 2 * PAD) * titleSize * 1.05 + (d.line ? 64 : 0) + 56;
  const panel = Math.round(Math.min(720, Math.max(600, H - redBottom)));
  return (
    <Frame>
            <Logo />
      <div style={{ position: "absolute", left: PAD, top: 160, width: W - 2 * PAD, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 600, fontSize: 36, color: SOFT }}>Szukamy</div>
        {word ? (
          <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: wordSize, lineHeight: 0.95, letterSpacing: "-0.055em", marginLeft: -8 }}>
            {word}
          </div>
        ) : null}
        <div style={{ display: "flex", marginTop: word ? 10 : 4, fontFamily: "Montserrat", fontWeight: word ? 600 : 800, fontSize: titleSize, lineHeight: 1.05, letterSpacing: -1.5 }}>
          {d.title}
        </div>
        {d.line ? <div style={{ display: "flex", marginTop: 20, fontSize: 36, fontWeight: 600 }}>{d.line}</div> : null}
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: panel,
          display: "flex",
          flexDirection: "column",
          backgroundColor: SNOW,
          color: INK,
          padding: `56px ${PAD}px 0`,
        }}
      >
        {duties.length ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 30, color: RED_TEXT, marginBottom: 14 }}>Czym się zajmiesz</div>
            {duties.map((t) => (
              <div key={t} style={{ display: "flex", fontSize: 30, lineHeight: 1.3, marginBottom: 8 }}>
                <span style={{ display: "flex", color: RED, marginRight: 14, fontWeight: 600 }}>—</span>
                <span style={{ display: "flex" }}>{t}</span>
              </div>
            ))}
          </div>
        ) : null}
        {d.skills.length ? (
          <div style={{ display: "flex", flexDirection: "column", marginTop: 26 }}>
            <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 30, color: RED_TEXT, marginBottom: 16 }}>Czego szukamy</div>
            <Chips items={d.skills.filter((t) => t.length <= 16).slice(0, 4)} onRed={false} />
          </div>
        ) : null}
      </div>
      <Foot text="Aplikuj przez link w komentarzu ↓" host={d.host} light />
    </Frame>
  );
}

function SlideHead({ n, total, title, light }: { n: number; total: number; title: string; light: boolean }) {
  return (
    <div style={{ position: "absolute", left: PAD, right: PAD, top: 72, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <B2BLogo variant={light ? "color" : "white"} height={44} />
        <div style={{ display: "flex", fontSize: 26, fontWeight: 600, color: light ? "rgba(31,17,21,0.55)" : SOFT }}>
          {n} / {total}
        </div>
      </div>
      <div style={{ display: "flex", marginTop: 90, fontFamily: "Montserrat", fontWeight: 800, fontSize: 76, letterSpacing: -2.5, color: light ? RED_TEXT : "#FFFFFF" }}>
        {title}
      </div>
    </div>
  );
}

function clip(t: string, n = 110): string {
  return t.length > n ? `${t.slice(0, n).replace(/\s+\S*$/, "")}…` : t;
}

/** Numerowana lista slajdu: obowiązki albo wymagania (kolejność coś znaczy — tak stoją w opisie). */
function SlideList({ items, nice }: { items: string[]; nice?: string[] }) {
  return (
    <div style={{ position: "absolute", left: PAD, right: PAD, top: 330, display: "flex", flexDirection: "column" }}>
      {items.map((t, i) => (
        <div key={`${i}-${t}`} style={{ display: "flex", alignItems: "flex-start", marginBottom: 30 }}>
          <div style={{ display: "flex", width: 56, flexShrink: 0, fontFamily: "Montserrat", fontWeight: 800, fontSize: 34, color: RED }}>
            {String(i + 1).padStart(2, "0")}
          </div>
          <div style={{ display: "flex", fontSize: 36, lineHeight: 1.28 }}>{clip(t)}</div>
        </div>
      ))}
      {nice && nice.length ? (
        <div style={{ display: "flex", flexDirection: "column", marginTop: 10 }}>
          <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 30, color: RED_TEXT, marginBottom: 10 }}>Mile widziane</div>
          <div style={{ display: "flex", fontSize: 30, lineHeight: 1.3, color: "rgba(31,17,21,0.75)" }}>{clip(nice.slice(0, 2).join(" · "), 150)}</div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Slajd karuzeli (dokument PDF na LinkedInie). `slides` z `carouselSlides`:
 * okładka jak „Mapa”, potem obowiązki i wymagania, gdy są w opisie, na końcu
 * proces (gdy sekcja jest pokazana) i gdzie jest link.
 */
export function PostCarouselSlide({ d, slides, index }: { d: PostData; slides: readonly CarouselSlide[]; index: number }) {
  const total = slides.length;
  const kind = slides[index] ?? "cover";
  const n = index + 1;
  if (kind === "cover") return <PostCardMap d={d} foot="Przesuń, żeby zobaczyć więcej →" footRight={`1 / ${total}`} />;
  if (kind === "duties" || kind === "must") {
    return (
      <Frame light>
        <SlideHead n={n} total={total} title={kind === "duties" ? "Czym się zajmiesz" : "Czego szukamy"} light />
        <SlideList items={(kind === "duties" ? d.duties : d.must).slice(0, 5)} nice={kind === "must" ? d.nice : undefined} />
        <Foot text={clip(d.title, 40)} host={d.host} light right="Przesuń →" />
      </Frame>
    );
  }
  return (
    <Frame>
      <SlideHead n={n} total={total} title={d.steps.length ? "Jak wygląda proces" : "Jak aplikować"} light={false} />
      <div style={{ position: "absolute", left: PAD, right: PAD, top: 330, display: "flex", flexDirection: "column" }}>
        {d.steps.map((step, i) => (
          <div key={step.title} style={{ display: "flex", alignItems: "center", marginBottom: 34 }}>
            <div
              style={{
                display: "flex",
                width: 76,
                height: 76,
                borderRadius: 999,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: "#FFFFFF",
                color: RED_TEXT,
                fontFamily: "Montserrat",
                fontWeight: 800,
                fontSize: 36,
                marginRight: 30,
                flexShrink: 0,
              }}
            >
              {i + 1}
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 40 }}>
                {step.title.charAt(0).toLocaleUpperCase("pl-PL") + step.title.slice(1)}
              </div>
              <div style={{ display: "flex", fontSize: 30, color: SOFT }}>{step.note}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: PAD, right: PAD, bottom: 170, display: "flex", fontFamily: "Montserrat", fontWeight: 800, fontSize: 56, lineHeight: 1.05, letterSpacing: -1.5 }}>
        Link do aplikacji czeka w pierwszym komentarzu ↓
      </div>
      <Foot text="Wystarczy samo CV" host={d.host} />
    </Frame>
  );
}
