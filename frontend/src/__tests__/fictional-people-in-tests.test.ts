/**
 * Testy (frontend, e2e, backend) i dokumenty w `docs/` noszą WYŁĄCZNIE
 * fikcyjne osoby.
 *
 * Repo i logi Actions są publiczne. 14.10.2026 w 18 plikach testów stały
 * imiona i nazwiska prawdziwych konsultantów z zamówień, Delivery Leada
 * i osób zgłaszających błędy — przepisane z ticketów razem z danymi
 * zamówień. 26.11.2026 to samo wyszło w `docs/`: raporty z importów zamówień
 * niosły osoby razem ze stawkami. Ten sam zbiór skrótów co strażnik harnessów
 * (`fixtures/real-people.ts`); nowa prawdziwa osoba w teście albo dokumencie
 * = dopisz jej skrót tam, a w treści użyj fikcyjnej (Anna Przykładowa, Jan
 * Testowy) albo identyfikatora (numer kontraktu, kandydata, zamówienia).
 * Stawek przy osobach nie przepisuj do repo wcale.
 *
 * Testy backendu i `docs/` czyta ten strażnik, bo wspólny zbiór skrótów jest
 * tu. Katalog `src/__tests__/` biegnie na każdym PR-ze (job „Strażnicy repo”)
 * i w kolejce merge'ów, więc PR z samym backendem albo dokumentacją też go
 * uruchamia.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { personDigest, realPeopleIn } from "./fixtures/real-people";

const FRONTEND = process.cwd();
const REPO = join(FRONTEND, "..");

/**
 * Testy, które sprawdzają treść historycznej korekty danych: migracja 0238
 * i jej lustro w `backend/entrypoint.sh` wpisują nazwiska dziewięciu osób
 * z umowy BIK, a testy pilnują, że obie ścieżki je mają. Usunięcie nazwisk
 * stąd wymaga najpierw zmiany tamtego kodu (osobna decyzja — korekta
 * biegnie przy wdrożeniu).
 */
const ALLOWED = new Set([
  "backend/tests/test_contract_order_workflows_migration.py",
  "backend/tests/test_migration_0238_name_matching.py",
]);

const TEST_FILE = /(\.test\.|\.spec\.)[jt]sx?$/;

function walk(dir: string, keep: (path: string) => boolean): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (name === "node_modules" || name.startsWith(".")) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path, keep);
    return keep(path) ? [path] : [];
  });
}

const FILES = [
  // Testy frontendu i ich dane (`__tests__/**`, `*.test.*`). Harnessy
  // `/preview/*` ma własny strażnik.
  ...walk(join(FRONTEND, "src"), (path) =>
    /[/\\]__tests__[/\\]/.test(path) || /[/\\]__fixtures__[/\\]/.test(path) || TEST_FILE.test(path),
  ),
  ...walk(join(FRONTEND, "e2e"), (path) => /\.(ts|tsx|json)$/.test(path)),
  ...walk(join(REPO, "backend", "tests"), (path) => /\.(py|json)$/.test(path)),
];

/** Dokumenty tekstowe z `docs/`; plików binarnych (docx) strażnik nie czyta. */
const DOCS = walk(join(REPO, "docs"), (path) => /\.(md|json|ya?ml|txt|csv|py|sh|mjs)$/.test(path));

/**
 * Właściciel produktu: dokumenty operacyjne (konta, kontakt, podpis) nazywają
 * go z imienia i nazwiska. Wyjątek dotyczy tylko `docs/`, nie testów.
 */
const DOCS_ALLOWED_DIGESTS = new Set(["6d119e9e293c962d", "e47e42f943727248"]);

const repoPath = (path: string) => relative(REPO, path).split("\\").join("/");

/** Ścieżka → skróty osób z listy, tylko dla plików z trafieniem. */
function scan(paths: string[], ignored: ReadonlySet<string> = new Set()): Map<string, string[]> {
  const hits = new Map<string, string[]>();
  for (const path of paths) {
    const found = realPeopleIn(readFileSync(path, "utf8")).filter((d) => !ignored.has(d));
    if (found.length > 0) hits.set(repoPath(path), found);
  }
  return hits;
}

const messages = (hits: [string, string[]][]) =>
  hits.map(([path, digests]) => `${path}: osoba (skrót ${digests.join(", ")})`);

describe("testy bez prawdziwych osób", () => {
  // Kilka tysięcy plików i skrót dla każdego słowa — skan raz, przy zbieraniu
  // testów, nie w `it` z domyślnym limitem 5 s.
  const hits = scan(FILES);

  it("skanuje testy frontendu, e2e i backendu (strażnik nie jest pusty)", () => {
    const paths = FILES.map(repoPath);
    // 14.10.2026: 975 plików frontendu — próg to połowa, nie dokładna liczba.
    expect(paths.filter((p) => p.startsWith("frontend/src/")).length).toBeGreaterThan(450);
    expect(paths.filter((p) => p.startsWith("backend/tests/")).length).toBeGreaterThan(500);
    expect(paths.some((p) => p.startsWith("frontend/e2e/"))).toBe(true);
  });

  it("żaden test nie nosi prawdziwej osoby", () => {
    expect(messages([...hits].filter(([path]) => !ALLOWED.has(path)))).toEqual([]);
  });

  it("wyjątki są aktualne — po zmianie korekty 0238 zdejmij je z listy", () => {
    expect([...ALLOWED].filter((path) => !hits.has(path))).toEqual([]);
  });

  it("rozpoznaje osobę z listy w każdym zapisie, także na styku linii komentarza", () => {
    // Na fikcyjnej osobie i jej własnym skrócie — prawdziwa stałaby tu tekstem.
    const listed = new Set([personDigest("lukasz zoltek")]);
    const comment = "/* zgłosił: Łukasz\n * ŻÓŁTEK */";
    expect(realPeopleIn(comment, listed)).toEqual([personDigest("lukasz zoltek")]);
    expect(realPeopleIn("contractor_name: 'Lukasz Zoltek'", listed)).toHaveLength(1);
    expect(realPeopleIn("Łukasz Żółtowski", listed)).toEqual([]);
  });
});

describe("dokumenty bez prawdziwych osób", () => {
  const hits = scan(DOCS, DOCS_ALLOWED_DIGESTS);

  it("skanuje docs/ (strażnik nie jest pusty)", () => {
    // 26.11.2026: ok. 1200 plików tekstowych — próg to mniej niż połowa.
    expect(DOCS.length).toBeGreaterThan(500);
    expect(DOCS.map(repoPath).some((p) => p.endsWith("-completion-report.md"))).toBe(true);
  });

  it("żaden dokument nie nosi prawdziwej osoby z listy", () => {
    expect(messages([...hits])).toEqual([]);
  });
});
