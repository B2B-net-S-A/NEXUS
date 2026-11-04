import { readFile } from "node:fs/promises";
import { join } from "node:path";

export { OgCard, ogJobTiles, type OgFact } from "./ogCard";

/**
 * Wspólny kadr grafik Open Graph (LinkedIn) strony kariery — `next/og`.
 *
 * Od 29.10.2026 w barwach marki B2B Network jak szablony ogłoszeń (Montserrat
 * + Source Sans 3, czerwień #E73748, logo), zamiast okna terminala: w
 * miniaturze posta (ok. 550 px szerokości, na telefonie ok. 350 px) tytuł jest
 * duży, a lokalizacja, tryb i umowa stoją w kaflach — `$ cat /rekrutacje/…`
 * i mono były tam nieczytelne.
 *
 * Sam kadr (`OgCard`) leży w `ogCard.tsx` bez zależności od Node — rysuje go
 * też podgląd posta w oknie „Udostępnij” (`LinkedInPreviewCard`).
 *
 * satori czyta TTF/OTF/WOFF, nie woff2 — stąd osobne `.ttf` w `src/app/fonts`
 * (instancje z tych samych plików co strona). Brak pliku (np. niepełny obraz
 * standalone) nie może zabić grafiki: wtedy renderujemy domyślnym fontem
 * `next/og`, bo zła typografia jest lepsza niż brak podglądu posta.
 */
export const OG_SIZE = { width: 1200, height: 630 };

type OgFont = {
  name: string;
  data: ArrayBuffer;
  weight: 400 | 600 | 800;
  style: "normal";
};

const FONT_FILES: { file: string; name: string; weight: OgFont["weight"] }[] = [
  { file: "Montserrat-800.ttf", name: "Montserrat", weight: 800 },
  { file: "Montserrat-600.ttf", name: "Montserrat", weight: 600 },
  { file: "SourceSans3-400.ttf", name: "Source Sans 3", weight: 400 },
  { file: "SourceSans3-600.ttf", name: "Source Sans 3", weight: 600 },
];

async function loadFont(file: string): Promise<ArrayBuffer | null> {
  try {
    const buf = await readFile(join(process.cwd(), "src/app/fonts", file));
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

export async function ogFonts(): Promise<OgFont[]> {
  const data = await Promise.all(FONT_FILES.map((f) => loadFont(f.file)));
  return FONT_FILES.flatMap((f, i) => {
    const font = data[i];
    return font ? [{ name: f.name, data: font, weight: f.weight, style: "normal" as const }] : [];
  });
}

/** `undefined` = domyślny font `next/og` (pusta tablica nie zawsze go włącza). */
export async function ogFontsOrDefault(): Promise<OgFont[] | undefined> {
  const fonts = await ogFonts();
  return fonts.length > 0 ? fonts : undefined;
}
