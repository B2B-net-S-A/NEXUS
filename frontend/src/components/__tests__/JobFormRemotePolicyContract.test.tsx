import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Opcje trybu pracy w formularzu rekrutacji muszą pokrywać się z unią
 * `RemotePolicy` (0278) — dokładnie te wartości, w tym pusta ("— nie
 * ustawiono —"), która odpowiada `null`/nieznane. Backendowa kolumna
 * `jobs.remote_policy` straciła domyślną "hybrid" w tej migracji: importer
 * Traffita przestał stemplować, więc "nieznane" jest wreszcie odróżnialne
 * od "chce biura" — select MUSI umieć to wyrazić, inaczej formularz
 * wymuszałby wybór trybu, którego nikt nie potwierdził.
 *
 * Test czyta ŹRÓDŁO zamiast renderować `AddJobModal`/`EditJobModal` — modal
 * wymaga QueryClienta, routera i kilku zapytań, a chroniona własność jest
 * statyczna: dotyczy każdego przyszłego `<option>`, nie tego jednego renderu,
 * który akurat zmontujemy. Wzorzec: `JobFormPriorityContract.test.tsx`.
 */

const SRC = join(__dirname, "..", "..");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

/** Wartości `<option value="...">` z bloku `<FieldGroup label="Tryb pracy (remote policy)">`. */
function remotePolicyOptionValues(): string[] {
  const source = readSource("components/AppShell.tsx");
  const start = source.indexOf(
    '<FieldGroup label="Tryb pracy (remote policy)">',
  );
  expect(
    start,
    "nie znaleziono pola Tryb pracy (remote policy) w AppShell.tsx",
  ).toBeGreaterThan(-1);

  const end = source.indexOf("</FieldGroup>", start);
  const block = source.slice(start, end);
  return [...block.matchAll(/<option value="([^"]*)"/g)].map((m) => m[1]);
}

/** Warianty unii `RemotePolicy` z types/client-profile.ts, plus pusta wartość. */
function acceptedRemotePolicyValues(): string[] {
  const source = readSource("types/client-profile.ts");
  const match = source.match(/export type RemotePolicy\s*=\s*([^;]+);/);
  expect(match, "nie znaleziono typu RemotePolicy").not.toBeNull();
  return ["", ...[...match![1].matchAll(/"([^"]+)"/g)].map((m) => m[1])];
}

describe("formularz rekrutacji — kontrakt trybu pracy (0278)", () => {
  it("oferuje dokładnie te wartości, które przyjmuje backend (plus pustą = nieznane)", () => {
    const offered = remotePolicyOptionValues();
    const accepted = acceptedRemotePolicyValues();

    expect(offered.length).toBeGreaterThan(0);
    expect([...offered].sort()).toEqual([...accepted].sort());
  });

  it("nie oferuje `on_site` — kolumna nigdy nie znała tej wartości", () => {
    expect(remotePolicyOptionValues()).not.toContain("on_site");
  });

  it("pierwsza opcja jest pusta — select startuje jako „nie ustawiono”, nie jako trafny wybór", () => {
    // Kotwica na konkretny incydent: przed 0278 `EMPTY_JOB.remote_policy`
    // było zahardkodowane na "hybrid", więc każda nowa oferta bez świadomego
    // wyboru DL-a "chciała biura" z definicji formularza, nie z decyzji.
    expect(remotePolicyOptionValues()[0]).toBe("");
  });
});
