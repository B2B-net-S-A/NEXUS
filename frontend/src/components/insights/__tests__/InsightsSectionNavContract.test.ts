/**
 * Pasek sekcji musi obiecywać dokładnie to, co jest na stronie.
 *
 * Każda z trzech zakładek /insights ma tablicę `SECTIONS` (spis treści paska
 * nawigacyjnego) i zestaw `<InsightsSection id="…">` (kotwice, do których ten
 * pasek skacze). To są DWA lustra tej samej listy i rozjeżdżają się w obie
 * strony, obie ciche:
 *
 * - wpis w `SECTIONS` bez sekcji → przycisk, który nigdzie nie przewija;
 *   użytkownik klika i nic się nie dzieje, więc czyta to jako zepsutą stronę,
 * - sekcja bez wpisu → treść, której pasek nie wymienia; spis treści kłamie,
 *   że to już koniec zakładki.
 *
 * To jest ta sama klasa regresji co martwe przyciski toolbara z PR #1316
 * („Wszystko", „Eksportuj", „Reset"): komponent był poprawny i w pełni
 * przetestowany, martwe było jego PODŁĄCZENIE — a testy tego nie widziały, bo
 * kończyły się na argumencie callbacka i nigdy nie przechodziły przez warstwę,
 * która naprawdę przenosi stan.
 *
 * Test patrzy w ŹRÓDŁO, a nie renderuje paneli: każdy z nich ciągnie kilkanaście
 * zapytań i sesję, więc test renderujący padałby z powodów niezwiązanych z tym,
 * czego pilnuje (ten sam kompromis co w `EmailReaderIsReachable.test.ts`).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PANELS = [
  "RekrutacjaPanel.tsx",
  "DeliveryLeadPanel.tsx",
  "RadaNadzorczaPanel.tsx",
] as const;

function readPanel(file: string): string {
  return readFileSync(
    join(process.cwd(), "src/components/insights", file),
    "utf8",
  );
}

/** Identyfikatory ze spisu treści paska — `const SECTIONS = [ { id: "…" } ]`. */
function navIds(source: string): string[] {
  const block = source.match(/const SECTIONS\s*=\s*\[([\s\S]*?)\n\];/);
  if (!block) return [];
  return [...block[1].matchAll(/id:\s*"([^"]+)"/g)].map((m) => m[1]);
}

/** Identyfikatory kotwic — `<InsightsSection … id="…">`, w dowolnej kolejności atrybutów. */
function anchorIds(source: string): string[] {
  return [
    ...source.matchAll(/<InsightsSection\b[^>]*?\sid="([^"]+)"/g),
  ].map((m) => m[1]);
}

describe.each(PANELS)("pasek sekcji ↔ kotwice — %s", (file) => {
  const source = readPanel(file);
  const nav = navIds(source);
  const anchors = anchorIds(source);

  it("ma niepustą tablicę SECTIONS i przynajmniej jedną kotwicę", () => {
    // Zero trafień znaczy najczęściej, że zmienił się KSZTAŁT kodu (np. tablica
    // przeniesiona do osobnego pliku), a nie że pasek zniknął. Bez tej asercji
    // dwie puste listy byłyby sobie równe i test przechodziłby, nie sprawdzając
    // niczego — to jest dokładnie ten wzorzec „test porównujący odpowiedź samą
    // ze sobą", który przepuścił defekt w PR #1314.
    expect(nav.length).toBeGreaterThan(0);
    expect(anchors.length).toBeGreaterThan(0);
  });

  it("każdy wpis paska ma kotwicę na stronie", () => {
    const missing = nav.filter((id) => !anchors.includes(id));
    expect(missing).toEqual([]);
  });

  it("każda sekcja jest wymieniona w pasku", () => {
    const unlisted = anchors.filter((id) => !nav.includes(id));
    expect(unlisted).toEqual([]);
  });

  it("identyfikatory są unikalne po obu stronach", () => {
    // Duplikat w kotwicach to dwa elementy o tym samym `id` w DOM-ie —
    // przeglądarka przewija do pierwszego, więc jedna z sekcji staje się
    // nieosiągalna z paska, mimo że test obecności obu list by przeszedł.
    expect(new Set(nav).size).toBe(nav.length);
    expect(new Set(anchors).size).toBe(anchors.length);
  });
});
