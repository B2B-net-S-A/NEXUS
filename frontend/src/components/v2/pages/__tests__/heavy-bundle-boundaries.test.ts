import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Granice `next/dynamic` wokół bibliotek, które dominują wagę trasy.
 *
 * Regresja jest tu maksymalnie CICHA: dopisanie z powrotem
 * `import { EditorContent } from "@tiptap/react"` na poziomie modułu w
 * `CandidateDetailV2` kompiluje się, przechodzi wszystkie testy i niczego nie
 * psuje na ekranie — wraca wyłącznie rachunek, który płaci użytkownik. Profil
 * kandydata to najcięższa trasa w aplikacji (614 kB First Load JS) i ekran
 * otwierany dziesiątki razy dziennie przy triażu bazy 49 tys. kandydatów,
 * a edytor draftu umowy renderuje się dopiero po trzech świadomych krokach
 * (Dokumenty → Umowy → istniejący kontrakt w statusie `draft`). To samo na
 * /dashboard z rechartsem, który ładował się niezależnie od tego, czy ktoś
 * w ogóle doscrollował do wykresu trendu.
 *
 * Repo nie ma bundle-analyzera ani sufitu First Load JS w CI, więc nikt nie
 * dostaje sygnału, gdy ciężka biblioteka wróci do importu na poziomie modułu.
 * Ten test jest tym sygnałem — najtańszym, jaki da się mieć bez nowej
 * zależności.
 *
 * Czytamy ŹRÓDŁO, a nie zaimportowany moduł: import wciągnąłby tu cały
 * ProseMirror, czyli test mierzyłby własny koszt zamiast kosztu trasy.
 */

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

/** Specyfikatory importu z poziomu modułu (poza ciałem `dynamic(() => …)`). */
function staticSpecifiers(source: string): string[] {
  const out: string[] = [];
  // Wyłącznie `import ... from "x"` / `import "x"` — składnia, której nie da
  // się odroczyć. `import("x")` (wyrażenie) jest właśnie tym, czego chcemy,
  // więc celowo NIE jest tu dopasowywane: po `import` musi stać coś innego
  // niż nawias otwierający.
  //
  // `[\s\S]*?` (a nie `[^\n]*?`) jest tu konieczne: import wieloliniowy
  // (`import {\n  EditorContent,\n} from "@tiptap/react"`) to najbardziej
  // naturalny sposób, w jaki ciężka biblioteka wróciłaby niezauważona.
  // Leniwe dopasowanie zatrzymuje się na PIERWSZYM `from`, więc każdy import
  // trafia na własny specyfikator, a nie na cudzy.
  const re = /(?:^|\n)\s*import\s+(?!\()[\s\S]*?\bfrom\s*["']([^"']+)["']/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) out.push(m[1]);
  // `import "polyfill"` — bez klauzuli `from`.
  const bare = /(?:^|\n)\s*import\s+["']([^"']+)["']/g;
  while ((m = bare.exec(source)) !== null) out.push(m[1]);
  return out;
}

const CASES: Array<{
  label: string;
  file: string;
  heavy: RegExp;
  lazyModule: string;
  why: string;
}> = [
  {
    label: "CandidateDetailV2 → edytor draftu umowy",
    file: "components/v2/pages/CandidateDetailV2.tsx",
    heavy: /^@tiptap\//,
    lazyModule: "./ContractDraftEditor",
    why:
      "TipTap/ProseMirror wraca do chunku trasy /candidates/[id] — najcięższej " +
      "w aplikacji — mimo że edytor renderuje się tylko za ścieżką " +
      "Dokumenty → Umowy → draft.",
  },
  {
    label: "RecruitmentStatsSection → wykres trendu",
    file: "components/v2/dashboard/RecruitmentStatsSection.tsx",
    heavy: /^recharts$/,
    lazyModule: "./RecruitmentTrendChart",
    why:
      "Recharts wraca do chunku /dashboard i płaci za niego każde otwarcie " +
      "dashboardu, także gdy użytkownik nigdy nie doscrolluje do wykresu.",
  },
];

describe("ciężkie biblioteki zostają za granicą next/dynamic", () => {
  for (const testCase of CASES) {
    const source = fs.readFileSync(path.join(SRC, testCase.file), "utf8");

    it(`${testCase.label}: brak statycznego importu ciężkiej biblioteki`, () => {
      const offenders = staticSpecifiers(source).filter((spec) =>
        testCase.heavy.test(spec),
      );
      expect(offenders, testCase.why).toEqual([]);
    });

    it(`${testCase.label}: moduł ładowany przez dynamic()`, () => {
      // Bez tej asercji test wyżej przechodziłby także wtedy, gdyby ktoś
      // usunął całą funkcję — czyli zieleń oznaczałaby brak funkcji, a nie
      // lekki bundle.
      expect(source).toMatch(
        new RegExp(
          `dynamic\\(\\s*\\(\\)\\s*=>[\\s\\S]{0,200}?import\\(\\s*["']${testCase.lazyModule.replace(
            /[.*+?^${}()|[\]\\]/g,
            "\\$&",
          )}["']`,
        ),
      );
    });
  }
});

it("wydzielone moduły edytora/wykresu faktycznie niosą ciężką bibliotekę", () => {
  // Gdyby import ciężkiej biblioteki wyparował z modułu docelowego, testy
  // wyżej dalej byłyby zielone, a granica `dynamic()` przestałaby cokolwiek
  // odraczać — pilnujemy więc obu stron granicy naraz.
  const editor = fs.readFileSync(
    path.join(SRC, "components/v2/pages/ContractDraftEditor.tsx"),
    "utf8",
  );
  expect(staticSpecifiers(editor).some((s) => s.startsWith("@tiptap/"))).toBe(true);

  const chart = fs.readFileSync(
    path.join(SRC, "components/v2/dashboard/RecruitmentTrendChart.tsx"),
    "utf8",
  );
  expect(staticSpecifiers(chart)).toContain("recharts");
});
