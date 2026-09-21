import { readFile } from "node:fs/promises";
import { join } from "node:path";

import type { ReactNode } from "react";

/**
 * Wspólne klocki grafik Open Graph (LinkedIn) strony kariery — `next/og`.
 *
 * satori czyta TTF/OTF/WOFF, nie woff2 — stąd osobne `.ttf` w `src/app/fonts`.
 * Brak pliku (np. niepełny obraz standalone) nie może zabić grafiki: wtedy
 * renderujemy domyślnym fontem `next/og`, bo zła typografia jest lepsza niż
 * brak podglądu posta.
 */
export const OG_SIZE = { width: 1200, height: 630 };

type OgFont = {
  name: string;
  data: ArrayBuffer;
  weight: 400 | 800;
  style: "normal";
};

async function loadFont(file: string): Promise<ArrayBuffer | null> {
  try {
    const buf = await readFile(join(process.cwd(), "src/app/fonts", file));
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

export async function ogFonts(): Promise<OgFont[]> {
  const [display, mono] = await Promise.all([
    loadFont("Geist-800.ttf"),
    loadFont("JetBrainsMono-400.ttf"),
  ]);
  const fonts: OgFont[] = [];
  if (display) fonts.push({ name: "Geist", data: display, weight: 800, style: "normal" });
  if (mono) fonts.push({ name: "JetBrains Mono", data: mono, weight: 400, style: "normal" });
  return fonts;
}

const C = {
  bg: "#000000",
  grid: "#0E0E0E",
  line: "#1A1A1A",
  text: "#F5F5F5",
  white: "#FFFFFF",
  gray: "#8B8B8B",
  comment: "#737373",
  dim: "#5C5C5C",
  bordo: "#9A142D",
  red: "#C8384F",
};

/** Kadr 1200×630 z makiet OgImage/OgGeneral. */
export function OgFrame({
  path,
  rightLabel,
  command,
  titleFirst,
  titleSecond,
  footLeft,
  footLeftItalic = false,
  host,
}: {
  path: string;
  rightLabel: string;
  command: ReactNode;
  titleFirst: string;
  titleSecond: string;
  footLeft: string;
  footLeftItalic?: boolean;
  host: string;
}) {
  const titleSize = titleFirst.length + titleSecond.length > 30 ? 80 : 100;
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        backgroundColor: C.bg,
        backgroundImage: `linear-gradient(90deg, ${C.grid} 1px, transparent 1px), linear-gradient(${C.grid} 1px, transparent 1px)`,
        backgroundSize: "100px 100px",
        fontFamily: "JetBrains Mono",
      }}
    >
      <div
        style={{
          height: 52,
          padding: "0 28px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderBottom: `1px solid ${C.line}`,
          fontSize: 17,
          color: C.comment,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ width: 14, height: 14, borderRadius: 999, border: `1px solid ${C.dim}` }} />
            <div style={{ width: 14, height: 14, borderRadius: 999, border: `1px solid ${C.dim}` }} />
            <div style={{ width: 14, height: 14, borderRadius: 999, backgroundColor: C.bordo }} />
          </div>
          <div style={{ display: "flex" }}>{path}</div>
        </div>
        <div style={{ display: "flex", letterSpacing: "0.16em" }}>
          <span style={{ color: C.bordo, marginRight: 10 }}>●</span>
          {rightLabel}
        </div>
      </div>
      <div
        style={{
          flexGrow: 1,
          padding: "44px 64px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", fontSize: 26, color: C.text }}>{command}</div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            fontFamily: "Geist",
            fontWeight: 800,
            fontSize: titleSize,
            lineHeight: 0.95,
            letterSpacing: "-0.045em",
          }}
        >
          {titleFirst ? <div style={{ display: "flex", color: C.white }}>{titleFirst}</div> : null}
          <div style={{ display: "flex", alignItems: "flex-end", color: C.bordo }}>
            {titleSecond}
            <div
              style={{
                width: titleSize * 0.42,
                height: titleSize * 0.8,
                marginLeft: 12,
                marginBottom: titleSize * 0.06,
                backgroundColor: C.bordo,
              }}
            />
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 24 }}>
          <span
            style={{ color: footLeftItalic ? C.comment : C.gray, fontStyle: footLeftItalic ? "italic" : "normal" }}
          >
            {footLeft}
          </span>
          <span style={{ color: C.red }}>{host}</span>
        </div>
      </div>
    </div>
  );
}

export const OG_COLORS = C;

/** `undefined` = domyślny font `next/og` (pusta tablica nie zawsze go włącza). */
export async function ogFontsOrDefault(): Promise<OgFont[] | undefined> {
  const fonts = await ogFonts();
  return fonts.length > 0 ? fonts : undefined;
}
