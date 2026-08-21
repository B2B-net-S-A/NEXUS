import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Strażnik martwych kluczy cache'u — wąsko, na trzech naprawionych miejscach.
 *
 * `invalidateQueries` z kluczem, pod którym NIE stoi żadna kwerenda, jest
 * cichym no-opem: mutacja się udaje, toast mówi „dodano", a lista pokazuje
 * stan sprzed zapisu tak długo, jak długo dane są świeże (`staleTime` 30 s,
 * a dla panelu wygasających 5 min). Kwerendy żyją w komponentach stron, więc
 * przełączenie zakładki ich nie odmontowuje i `refetchOnMount` nie ratuje.
 * Użytkownik wnioskuje, że zapis przepadł, i robi go DRUGI raz — stąd
 * zdublowani klienci i zdublowani kandydaci w pipelinie.
 *
 * Trzy udokumentowane przyczyny dryfu: zmiana nazwy klucza listy (V1 → V2)
 * bez aktualizacji miejsc inwalidacji, klucz wymyślony „na oko" (`clients-v2`
 * nigdy nie istniał) oraz rozjazd TYPU parametru trasy (react-query porównuje
 * prymitywy przez `===`, więc `["kanban", 123]` nie trafia w `["kanban", "123"]`).
 *
 * Zakres celowo ograniczony do plików naprawionych w tej zmianie — szerszy skan
 * „każdy literał ma producenta" wskazuje dziś także miejsca poza nią.
 */

const SRC_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function listSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__" || entry.name === "test") continue;
      listSourceFiles(full, out);
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

/** Pierwszy człon każdego `queryKey: [ … ]` znalezionego w `src/`. */
function producedKeyRoots(): Set<string> {
  const roots = new Set<string>();
  for (const file of listSourceFiles(SRC_DIR)) {
    const source = fs.readFileSync(file, "utf8");
    for (const m of source.matchAll(/queryKey:\s*\[\s*["'`]([^"'`]+)["'`]/g)) {
      roots.add(m[1]);
    }
  }
  return roots;
}

function read(relative: string): string {
  return fs.readFileSync(path.join(SRC_DIR, relative), "utf8");
}

const QUICK_ACTIONS = "components/v2/shell/QuickActionsV2.tsx";
const REQUEST_HISTORY = "components/RequestHistorySection.tsx";
const TERMINATION = "components/contracts/ContractTerminationDialog.tsx";

describe("klucze inwalidacji mają producenta", () => {
  const roots = producedKeyRoots();

  it("skan widzi kwerendy (strażnik nie jest pusty)", () => {
    expect(roots.size).toBeGreaterThan(50);
  });

  it.each([
    "clients-directory",
    "client-contacts",
    "contracts-v2",
    "contracts-expiring-v2",
    "contractors-v2",
    "contractors-stats-v2",
    "client-profile",
    "kanban",
    "job",
    "pipeline-scores",
  ])("pod kluczem %s stoi co najmniej jedna kwerenda", (root) => {
    expect(roots.has(root)).toBe(true);
  });

  it("globalne menu Dodaj nie wraca do wymyślonych kluczy", () => {
    const source = read(QUICK_ACTIONS);
    expect(source).not.toContain('queryKey: ["clients-v2"]');
    expect(source).not.toContain('queryKey: ["contacts"]');
    expect(source).toContain('queryKey: ["clients-directory"]');
    expect(source).toContain('queryKey: ["client-contacts"]');
  });

  it("dialog zakończenia współpracy nie wraca do osieroconego ['contracts']", () => {
    const source = read(TERMINATION);
    expect(source).not.toContain('queryKey: ["contracts"]');
    expect(source).toContain('queryKey: ["contracts-v2"]');
    expect(source).toContain('queryKey: ["contracts-expiring-v2"]');
  });

  it("dodanie championa unieważnia kanban i nagłówek w OBU formach parametru", () => {
    const source = read(REQUEST_HISTORY);
    for (const key of ["kanban", "job"]) {
      // `jobId` jest liczbą, a strona cachuje surowym parametrem trasy (string).
      expect(source).toContain(`queryKey: ["${key}", jobKey]`);
      expect(source).toContain(`queryKey: ["${key}", jobId]`);
    }
    expect(source).toContain("const jobKey = String(jobId)");
  });
});
