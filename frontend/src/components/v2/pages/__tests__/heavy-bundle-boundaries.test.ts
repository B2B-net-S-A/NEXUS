import fs from "node:fs";
import path from "node:path";

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

// Ścieżki testowe są względem `src/`, a ten plik leży w
// `src/components/v2/pages/__tests__/` — cztery poziomy w górę, nie trzy.
// Trzy dawały `src/components`, stąd `components/components/v2/...` w ENOENT.
// Liczone z `process.cwd()` (vitest startuje w `frontend/`), bo pod jsdom
// `import.meta.url` nie jest URL-em `file:` i `fileURLToPath` rzuca wyjątek.
const SRC = path.resolve(process.cwd(), "src");

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
    // Od 09.2026 zakładka „Pliki i umowy” żyje w osobnym pliku, a profil
    // (`CandidateDetailV2`) importuje ją statycznie — więc granica musi stać
    // TUTAJ, inaczej TipTap wraca do chunku trasy.
    label: "Profil kandydata → edytor draftu umowy",
    file: "components/v2/candidate-profile/FilesContractsTab.tsx",
    heavy: /^@tiptap\//,
    lazyModule: "@/components/v2/pages/ContractDraftEditor",
    why:
      "TipTap/ProseMirror wraca do chunku trasy /candidates/[id] — najcięższej " +
      "w aplikacji — mimo że edytor renderuje się tylko za ścieżką " +
      "Pliki i umowy → istniejący draft.",
  },
  {
    label: "Profil kandydata → edycja CV firmowego",
    file: "components/v2/candidate-profile/RecruitmentsTab.tsx",
    heavy: /^@tiptap\/|CVBrandedEditModal$/,
    lazyModule: "@/components/v2/modals/CVBrandedEditModal",
    why:
      "Modal edycji brandowanego CV (TipTap) renderuje się dopiero po " +
      "kliknięciu na karcie rekrutacji — statyczny import wciąga go do " +
      "każdego otwarcia profilu.",
  },
];

it("profil kandydata nie importuje statycznie edytorów TipTapa", () => {
  // Orkiestrator i każdy plik zakładki — żaden nie może wciągać edytorów.
  const dir = path.join(SRC, "components/v2/candidate-profile");
  const files = [
    path.join(SRC, "components/v2/pages/CandidateDetailV2.tsx"),
    ...fs
      .readdirSync(dir)
      .filter((name) => /\.tsx?$/.test(name))
      .map((name) => path.join(dir, name)),
  ];
  const offenders = files.flatMap((file) =>
    staticSpecifiers(fs.readFileSync(file, "utf8"))
      .filter((spec) => /^@tiptap\/|ContractDraftEditor$|CVBrandedEditModal$/.test(spec))
      .map((spec) => `${path.relative(SRC, file)} → ${spec}`),
  );
  expect(offenders).toEqual([]);
});

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

it("„CV do klienta” nie wciąga generatora CV do chunku /jobs/[id]", () => {
  // Ciężarem nie jest tu zewnętrzna biblioteka, tylko własne komponenty:
  // warsztaty z formularzami i (dawniej) osadzonym generatorem CV. Od wersji 3 warsztaty żyją w PANELU OSOBY, a panel jest
  // domyślnym widokiem rekrutacji — statyczny import warsztatu gdziekolwiek
  // na ścieżce strona → tabela → panel przenosi ten koszt na KAŻDE otwarcie
  // rekrutacji. Regresja jest cicha jak przy TipTapie: ekran działa, rośnie
  // tylko rachunek.
  const heavy = /jobs\/(ScreeningWorkbench|CvHandoffWorkbench)$/;
  const recruitmentDir = path.join(SRC, "components/v2/recruitment");
  const onPath = [
    path.join(SRC, "app/jobs/[id]/page.tsx"),
    ...fs
      .readdirSync(recruitmentDir)
      .filter((name) => /\.tsx?$/.test(name))
      .map((name) => path.join(recruitmentDir, name)),
  ];
  const offenders = onPath.flatMap((file) =>
    staticSpecifiers(fs.readFileSync(file, "utf8"))
      .filter((spec) => heavy.test(spec))
      .map((spec) => `${path.relative(SRC, file)} → ${spec}`),
  );
  expect(
    offenders,
    "Warsztaty Screening/CV wróciły do statycznego importu na ścieżce /jobs/[id].",
  ).toEqual([]);

  const boundary = fs.readFileSync(
    path.join(recruitmentDir, "panel-workbenches.tsx"),
    "utf8",
  );
  for (const mod of ["ScreeningWorkbench", "CvHandoffWorkbench"]) {
    // Bez tej połowy zieleń oznaczałaby „nie ma funkcji", a nie „lekki bundle".
    expect(boundary).toMatch(
      new RegExp(
        `dynamic\\(\\s*\\(\\)\\s*=>[\\s\\S]{0,200}?import\\(\\s*["']@/components/v2/jobs/${mod}["']`,
      ),
    );
  }
  // …i panel osoby bierze warsztaty z TEJ granicy.
  const panel = fs.readFileSync(path.join(recruitmentDir, "PersonPanel.tsx"), "utf8");
  expect(staticSpecifiers(panel)).toContain("./panel-workbenches");

  // Od generatora CV v3 warsztat NIE osadza generatora: karta „CV do klienta”
  // otwiera go w oknie, a okno ładuje formularz dopiero przy otwarciu.
  const workbench = fs.readFileSync(
    path.join(SRC, "components/v2/jobs/CvHandoffWorkbench.tsx"),
    "utf8",
  );
  expect(staticSpecifiers(workbench)).toContain("@/components/v2/recruitment/CvToClientCard");
  expect(staticSpecifiers(workbench)).not.toContain(
    "@/components/v2/pages/CVGeneratorStandaloneV2",
  );
});

it("karta „CV do klienta” i okno generatora trzymają generator i edytor za dynamic()", () => {
  // Karta jest na ścieżce /jobs/[id] (panel osoby) i na profilu kandydata
  // okno generatora jest montowane przy każdym otwarciu — żadna z nich nie
  // może wciągnąć formularza generatora ani TipTapa do chunku trasy.
  const heavy =
    /^@tiptap\/|CVBrandedEditModal$|cv-generator\/CvGenerator$|CVGeneratorStandaloneV2$/;
  const files = [
    "components/v2/recruitment/CvToClientCard.tsx",
    "components/v2/cv-generator/CvGeneratorDialog.tsx",
    "components/v2/pages/CandidateDetailV2.tsx",
    "components/v2/candidate-profile/RecruitmentsTab.tsx",
    "components/v2/jobs/PipelineCandidateDock.tsx",
  ];
  const offenders = files.flatMap((file) =>
    staticSpecifiers(fs.readFileSync(path.join(SRC, file), "utf8"))
      .filter((spec) => heavy.test(spec))
      .map((spec) => `${file} → ${spec}`),
  );
  expect(offenders).toEqual([]);

  // …i te moduły naprawdę są ładowane leniwie, a nie usunięte.
  const card = fs.readFileSync(path.join(SRC, "components/v2/recruitment/CvToClientCard.tsx"), "utf8");
  expect(card).toMatch(
    /dynamic\(\s*\(\)\s*=>[\s\S]{0,200}?import\(\s*["']@\/components\/v2\/modals\/CVBrandedEditModal["']/,
  );
  const dialog = fs.readFileSync(path.join(SRC, "components/v2/cv-generator/CvGeneratorDialog.tsx"), "utf8");
  expect(dialog).toMatch(
    /dynamic\(\s*\(\)\s*=>[\s\S]{0,200}?import\(\s*["']@\/components\/v2\/cv-generator\/CvGenerator["']/,
  );
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
  // Przypadek „RecruitmentStatsSection → wykres trendu" usunięty razem
  // z martwymi komponentami pulpitu (audyt 17.09.2026) — nigdzie nie montowane.
});
