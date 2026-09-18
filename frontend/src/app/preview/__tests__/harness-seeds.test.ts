/**
 * Publiczny harness `/preview/*` ma robić ZERO zapytań przy ładowaniu.
 *
 * Niezasiany klucz react-query uruchamia `queryFn`, ten dostaje 401 i strona
 * przerzuca na `/login?reason=session_expired` — czyli harness, który ma
 * pokazywać ekran bez logowania, nie pokazuje niczego. Audyt 18.09.2026 zastał
 * tak `/preview/contracts-consolidation`: `AddProjectDialog` dołożył do klucza
 * klientów drugi element (`"contract-eligible"`), a harness zasiewał wersję
 * jednoelementową sprzed tej zmiany.
 *
 * Test czyta klucze z komponentów i porównuje je z zasiewem — bierze wyłącznie
 * klucze złożone z samych literałów (te z parametrami zależą od stanu, więc
 * nie da się o nich nic powiedzieć statycznie).
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

function read(relativePath: string): string {
  return readFileSync(join(SRC, relativePath), "utf8");
}

/**
 * Komentarze precz — inaczej klucz WYMIENIONY W KOMENTARZU wyciszał strażnika.
 * (Złapane przy pisaniu tego testu: komentarz tłumaczący, czemu klucz jest
 * dwuelementowy, sam w sobie spełniał warunek „zasiany".)
 */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
}

/**
 * Klucze `useQuery` złożone WYŁĄCZNIE z literałów tekstowych.
 *
 * Tylko `useQuery` — `invalidateQueries` i `setQueryData` używają tego samego
 * pola `queryKey`, ale niczego nie pobierają, więc nie mają czego zasiewać.
 */
function literalQueryKeys(source: string): string[] {
  return [
    ...source.matchAll(/useQuery(?:<[^>]*>)?\(\{([\s\S]{0,800}?)\}\s*\)/g),
  ]
    .flatMap((block) => [...block[1].matchAll(/queryKey:\s*(\[[^\]]*\])/g)])
    .map((match) => match[1].replace(/\s+/g, " ").trim())
    .filter((key) => /^\[(\s*"[^"]*"\s*,?)+\]$/.test(key));
}

describe("/preview/contracts-consolidation zasiewa każdy stały klucz", () => {
  const harness = read("app/preview/contracts-consolidation/page.tsx");
  const components = [
    "components/v2/pages/ContractsListV2.tsx",
    "components/contracts/AddProjectDialog.tsx",
  ];

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const missing: string[] = [];
    for (const file of components) {
      for (const key of literalQueryKeys(read(file))) {
        // Zasiew zapisuje ten sam literał (z dokładnością do białych znaków).
        const normalized = withoutComments(harness).replace(/\s+/g, " ");
        if (!normalized.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(
      missing,
      "Niezasiany klucz react-query w harnessie: queryFn wystartuje, dostanie " +
        "401 i strona przerzuci na /login.",
    ).toEqual([]);
  });

  it("nie daje się uciszyć komentarzem", () => {
    expect(
      withoutComments('// ["a", "b"]\nqc.setQueryData(["a"], []);'),
    ).not.toContain('"b"');
  });

  it("rozpoznaje klucze wieloelementowe (inaczej strażnik byłby ślepy)", () => {
    // To jest dokładnie ten kształt, który się rozjechał.
    expect(
      literalQueryKeys(
        'useQuery({ queryKey: ["a-lookup", "contract-eligible"] })',
      ),
    ).toEqual(['["a-lookup", "contract-eligible"]']);
    // Klucz z parametrem jest świadomie pomijany — zależy od stanu ekranu.
    expect(
      literalQueryKeys('useQuery({ queryKey: ["jobs", clientId] })'),
    ).toEqual([]);
    // Unieważnienie cache'u NIE pobiera danych — nie ma czego zasiewać.
    expect(
      literalQueryKeys(
        'queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });',
      ),
    ).toEqual([]);
  });
});
