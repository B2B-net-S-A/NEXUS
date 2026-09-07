import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Checkboxy „Tryb pracy” kandydata muszą oferować DOKŁADNIE te wartości, które
 * przyjmuje backendowy walidator `preferences.remote_modes` (0278) — czyli
 * unię `RemotePolicy` z `types/client-profile.ts`, którą oferta i kandydat
 * dzielą po nazwie (patrz `REMOTE_MODE_VALUES` w `app/schemas/candidate.py`,
 * zbudowane wprost z backendowego `RemotePolicy`).
 *
 * Do tej migracji jeden z trzech checkboxów wysyłał `on_site` — literówkę,
 * którą backend milcząco zapisywał do JSONB (walidatora jeszcze nie było).
 * Naprawiona wartość jest teraz WYMUSZONA przez `_normalize_remote_modes` —
 * checkbox z niepoprawną wartością dawałby 422 przy KAŻDYM zapisie
 * formularza, w którym ktoś by go zaznaczył.
 *
 * Test czyta ŹRÓDŁO zamiast renderować `AddCandidateModal` — modal wymaga
 * QueryClienta i kilku zapytań, a chroniona własność jest statyczna: dotyczy
 * każdego przyszłego `<CB>`, nie tego jednego renderu, który akurat
 * zmontujemy. Wzorzec: `JobFormPriorityContract.test.tsx`.
 */

const SRC = join(__dirname, "..", "..");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC, relativePath), "utf-8");
}

/** Wartości `<CB field="pref_remote_modes" value="...">` z bloku „Tryb pracy”. */
function remoteModeCheckboxValues(): string[] {
  const source = readSource("components/AppShell.tsx");
  const start = source.indexOf('<FieldGroup label="Tryb pracy">');
  expect(start, "nie znaleziono pola Tryb pracy w AppShell.tsx").toBeGreaterThan(-1);

  const end = source.indexOf("</FieldGroup>", start);
  const block = source.slice(start, end);
  return [
    ...block.matchAll(/<CB field="pref_remote_modes" value="([^"]*)"/g),
  ].map((m) => m[1]);
}

/** Warianty unii `RemotePolicy` z types/client-profile.ts. */
function remotePolicyUnionValues(): string[] {
  const source = readSource("types/client-profile.ts");
  const match = source.match(/export type RemotePolicy\s*=\s*([^;]+);/);
  expect(match, "nie znaleziono typu RemotePolicy").not.toBeNull();
  return [...match![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

describe("formularz kandydata — kontrakt trybu pracy (0278)", () => {
  it("oferuje dokładnie te wartości, które przyjmuje backend", () => {
    const offered = remoteModeCheckboxValues();
    const accepted = remotePolicyUnionValues();

    expect(offered.length).toBeGreaterThan(0);
    expect([...offered].sort()).toEqual([...accepted].sort());
  });

  it("nie oferuje `on_site` — historyczna literówka naprawiona migracją 0278", () => {
    // Kotwica na konkretny incydent, nie tylko na równość zbiorów. Gdyby ktoś
    // „naprawił" rozjazd, dopisując z powrotem `on_site` do checkboxa I do
    // unii `RemotePolicy` naraz, test wyżej znów by przechodził, a 422
    // wróciłoby przy pierwszym zapisie formularza.
    expect(remoteModeCheckboxValues()).not.toContain("on_site");
    expect(remotePolicyUnionValues()).not.toContain("on_site");
  });
});
