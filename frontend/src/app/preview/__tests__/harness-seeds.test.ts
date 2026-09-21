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

describe("/preview/recruitment-v3 zasiewa każdy stały klucz i nie ma sieci", () => {
  const harness = withoutComments(read("app/preview/recruitment-v3/page.tsx")).replace(/\s+/g, " ");
  // Wszystko, co harness montuje (bezpośrednio albo przez panel osoby),
  // plus `JobShortlist` — segment shortlisty produkcyjnie renderuje właśnie jego.
  const components = [
    "components/v2/recruitment/RecruitmentWorkspace.tsx",
    "components/v2/recruitment/StageStrip.tsx",
    "components/v2/recruitment/QuickChips.tsx",
    "components/v2/recruitment/PeopleTable.tsx",
    "components/v2/recruitment/BulkBar.tsx",
    "components/v2/recruitment/PersonPanel.tsx",
    "components/v2/recruitment/ProposalsSegment.tsx",
    "components/v2/recruitment/ProposalPanel.tsx",
    "components/v2/recruitment/useBulkCvHandoff.tsx",
    "components/v2/recruitment/BulkCvHandoffDialog.tsx",
    "components/v2/jobs/JobShortlist.tsx",
    "hooks/usePipelineMove.tsx",
    "hooks/useCandidateContactFeature.ts",
  ];

  it("nie zostawia stałego klucza bez zasiewu", () => {
    const missing: string[] = [];
    for (const file of components) {
      for (const key of literalQueryKeys(read(file))) {
        if (!harness.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("zasiewa też klucze z parametrem, o które pyta widok domyślny", () => {
    // Tych strażnik literałów nie widzi (zależą od `jobId`), a odpalają się
    // przy samym wejściu: dopasowania tabeli i flaga modułu kontaktu.
    expect(harness).toContain('["pipeline-scores", String(JOB_ID)]');
    expect(harness).toContain("candidateContactQueryKeys.status()");
    expect(harness).toContain("candidateQueryKeys.detail(item.candidate_id)");
    expect(harness).toContain("candidateQueryKeys.notes(item.candidate_id)");
    // Sekcja CV panelu pyta o „Pracę w tle" (powód pominięcia auto-CV).
    expect(harness).toContain("jobBackgroundEventsQueryKey(JOB_ID, BACKGROUND_EVENTS_STEP)");
  });

  it("odcina sieć na czas życia harnessu (warsztaty panelu pytają o klucze nie do zasiania)", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    // Zdjęcie blokady przy odmontowaniu — harness nie psuje reszty aplikacji.
    expect(harness).toContain("api.interceptors.request.eject(");
    // Segment propozycji dostaje stan wprost, bez `useJobProposals`.
    expect(harness).toContain("ProposalsSegmentView");
    expect(harness).not.toMatch(/<ProposalsSegment\b(?!View)/);
  });
});

describe("/preview/jobs-list-v3 zasiewa listę TYMI SAMYMI kluczami co komponent", () => {
  const harness = withoutComments(read("app/preview/jobs-list-v3/page.tsx"));
  const list = withoutComments(read("components/v2/pages/JobsListV2.tsx"));

  it("klucze listy i liczników pochodzą z funkcji komponentu, nie z kopii", () => {
    // Klucz listy ma 16 elementów zależnych od stanu — ręczna kopia rozjechałaby
    // się przy pierwszym dołożonym filtrze. Harness MUSI wołać te same funkcje.
    for (const fn of ["jobsListQueryKey", "jobsQuickCountsQueryKey"]) {
      expect(list).toMatch(new RegExp(`export function ${fn}\\(`));
      expect(list).toMatch(new RegExp(`queryKey: ${fn}\\(`));
      expect(harness).toMatch(new RegExp(`setQueryData\\(\\s*${fn}\\(`));
    }
    expect(harness).not.toContain('"jobs-v2"');
  });

  it("zasiewa stałe klucze rozwijanych filtrów kolumny", () => {
    const missing: string[] = [];
    for (const file of [
      "components/v2/filters/ClientMultiSelect.tsx",
      "components/v2/filters/UserMultiSelect.tsx",
      "components/v2/filters/CompetenceCategoryMultiSelect.tsx",
    ]) {
      const keys = literalQueryKeys(read(file));
      expect(keys.length, file).toBeGreaterThan(0);
      for (const key of keys) {
        if (!harness.replace(/\s+/g, " ").includes(key)) {
          missing.push(`${file}: ${key}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it("ma bezpiecznik sieci na zapytania doku, których nie zasiewa", () => {
    expect(harness).toContain("interceptors.request.use");
    expect(harness).toContain("interceptors.request.eject");
  });
});
