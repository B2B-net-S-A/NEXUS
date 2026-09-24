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
  // Wszystko, co harness montuje, i to, co zasiew nadal obsługuje
  // (panel osoby otwierany teraz z Tablicy),
  // plus `JobShortlist` — segment shortlisty produkcyjnie renderuje właśnie jego.
  const components = [
    "components/v2/recruitment/PeopleTable.tsx",
    "components/v2/recruitment/PersonPanel.tsx",
    "components/v2/recruitment/CvToClientCard.tsx",
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
    // Karta „CV do klienta” pyta o „Pracę w tle" (powód pominięcia auto-CV).
    expect(harness).toContain("jobBackgroundEventsQueryKey(JOB_ID, BACKGROUND_EVENTS_STEP)");
    // …o CV etapu, listę wygenerowanych CV pary i plik źródłowy — TYMI SAMYMI
    // funkcjami kluczy co karta, nie kopią.
    const card = withoutComments(read("components/v2/recruitment/CvToClientCard.tsx"));
    for (const fn of ["cvToClientRowsQueryKey", "stageBrandedQueryKey"]) {
      expect(card).toMatch(new RegExp(`queryKey: ${fn}\\(`));
      expect(harness).toMatch(new RegExp(`setQueryData\\(\\s*${fn}\\(`));
    }
    expect(card).toContain('queryKey: ["cv-original", stageId]');
    expect(harness).toContain('setQueryData(["cv-original", item.id]');
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

describe("/preview/custom-dashboard zasiewa każdy stały klucz", () => {
  const harness = withoutComments(read("app/preview/custom-dashboard/page.tsx")).replace(
    /\s+/g,
    " ",
  );
  const components = [
    "components/v2/dashboard/custom/CustomDashboard.tsx",
    "components/v2/dashboard/custom/MetricBuilderForm.tsx",
    "components/v2/dashboard/custom/SmallTiles.tsx",
    "components/v2/filters/CompetenceCategoryMultiSelect.tsx",
  ];

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const missing: string[] = [];
    for (const file of components) {
      for (const key of literalQueryKeys(read(file))) {
        if (!harness.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("zasiewa klucze budowane funkcjami tymi samymi funkcjami", () => {
    for (const fn of ["USER_DASHBOARD_QUERY_KEY", "METRIC_CATALOG_QUERY_KEY", "metricQueryKey(", "myPeopleSummaryQueryKey"]) {
      expect(harness).toContain(fn);
    }
  });
});

describe("/preview/new-job zasiewa każdy stały klucz", () => {
  const harness = withoutComments(read("app/preview/new-job/page.tsx")).replace(/\s+/g, " ");

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const keys = [
      ...literalQueryKeys(read("components/v2/jobs/new/NewJobPage.tsx")),
      // `ClientSinglePicker` bierze klucz z propsa — ten sam literał co w kroku 1.
      '["clients-lookup-new-job"]',
    ];
    expect(keys.length).toBeGreaterThan(1);
    expect(keys.filter((key) => !harness.includes(key))).toEqual([]);
    expect(read("components/v2/jobs/new/NewJobRequestStep.tsx")).toContain(
      'queryKey="clients-lookup-new-job"',
    );
  });
});

describe("/preview/cv-generator renderuje z propsów i nie ma sieci", () => {
  const harness = withoutComments(read("app/preview/cv-generator/page.tsx")).replace(/\s+/g, " ");
  // Komponenty prezentacyjne, które harness montuje. Żaden nie może mieć
  // stałego klucza zapytania bez zasiewu.
  const components = [
    "components/v2/cv-generator/PersonStep.tsx",
    "components/v2/cv-generator/ProcessStep.tsx",
    "components/v2/cv-generator/SourcesPanel.tsx",
    "components/v2/cv-generator/ProcessingTiles.tsx",
    "components/v2/cv-generator/LanguageChoice.tsx",
    "components/v2/cv-generator/AdvancedOptions.tsx",
    "components/v2/cv-generator/GenerateBar.tsx",
    "components/v2/cv-generator/UploadIdentityStep.tsx",
    "components/v2/cv-generator/CvResult.tsx",
    "components/v2/cv-generator/MyCvList.tsx",
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

  it("zasiewa listę klientów tym samym kluczem, którego używa picker kroku 2", () => {
    expect(read("components/v2/cv-generator/ProcessStep.tsx")).toContain(
      'CV_GENERATOR_CLIENTS_QUERY_KEY = "clients-lookup-cv-generator"',
    );
    expect(harness).toContain("qc.setQueryData([CV_GENERATOR_CLIENTS_QUERY_KEY]");
  });

  it("montuje widoki, nie kontenery z zapytaniami", () => {
    // `MyCvList`/`CvResultLive`/`CvGenerator` pobierają dane — harness bierze ich widoki.
    expect(harness).toContain("<MyCvListView");
    expect(harness).toContain("<CvResultView");
    expect(harness).not.toMatch(/<MyCvList[\s>]/);
    expect(harness).not.toMatch(/<CvResultLive[\s>]/);
    expect(harness).not.toMatch(/<CvGenerator[\s>]/);
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/kpi-targets zasiewa każdy stały klucz", () => {
  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const harness = withoutComments(read("app/preview/kpi-targets/page.tsx")).replace(/\s+/g, " ");
    const keys = literalQueryKeys(read("lib/api/kpiTargets.ts"));
    expect(keys).toEqual(['["kpi-targets"]', '["kpi-targets", "history"]']);
    for (const key of keys) expect(harness).toContain(key);
  });
});

describe("/preview/cv-qc — okno QC CV bez sieci", () => {
  const harness = withoutComments(read("app/preview/cv-qc/page.tsx")).replace(/\s+/g, " ");

  it("wynik QC idzie propsem, propozycje AI zasiane kluczem komponentu", () => {
    // `CvQcDialog` sam pyta o wynik (staleTime 0) — harness renderuje widok.
    expect(harness).toContain("CvQcDialogView");
    expect(harness).not.toMatch(/<CvQcDialog\b(?!View)/);
    expect(harness).toContain("setQueryData<QcFixesResponse>(cvQcFixesQueryKey(STAGE_ID)");
    expect(read("lib/api/cvQc.ts")).toContain("queryKey: cvQcFixesQueryKey(");
  });

  it("odcina sieć — przyciski poprawek nie trafiają do API", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/cpro-queue zasiewa każdy stały klucz", () => {
  const harness = withoutComments(read("app/preview/cpro-queue/page.tsx")).replace(/\s+/g, " ");

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const missing: string[] = [];
    for (const file of [
      "lib/api/boardTasks.ts",
      "components/v2/dashboard/BoardTasksPanel.tsx",
      "components/v2/dashboard/CproQueueDialog.tsx",
    ]) {
      for (const key of literalQueryKeys(read(file))) {
        if (!harness.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
    for (const constant of ["BOARD_TASKS_QUERY_KEY", "CPRO_QUEUE_QUERY_KEY", "CPRO_SENDER_QUERY_KEY"]) {
      expect(harness).toMatch(new RegExp(`setQueryData<\\w+>\\(${constant}`));
    }
  });

  it("odcina sieć", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/insights zasiewa każdy stały klucz widoków", () => {
  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const harness = withoutComments(read("app/preview/insights/page.tsx")).replace(
      /\s+/g,
      " ",
    );
    const missing: string[] = [];
    for (const file of [
      "components/insights/views/RywalizacjaView.tsx",
      "components/insights/views/MojMiesiacView.tsx",
      "components/insights/views/ZespolView.tsx",
      "components/insights/views/FirmaView.tsx",
      "components/insights/sections/InsightsRaces.tsx",
      "components/insights/sections/InsightsSeniority.tsx",
    ]) {
      for (const key of literalQueryKeys(read(file))) {
        if (!harness.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("odcina sieć interceptorem", () => {
    expect(read("app/preview/insights/page.tsx")).toContain(
      "api.interceptors.request.use",
    );
  });
});
