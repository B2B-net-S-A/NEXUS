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

import { existsSync, readFileSync } from "node:fs";
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
    "components/contracts/ContractSidePanel.tsx",
    "components/contracts/ContractStatusControl.tsx",
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

  it("zasiewa klucze bocznego panelu (z parametrem) i odcina sieć", () => {
    // Strażnik literałów ich nie widzi — zależą od id kontraktu, a `?contract=`
    // otwiera panel przy samym wejściu.
    const panel = withoutComments(read("components/contracts/ContractSidePanel.tsx"));
    const seeded = withoutComments(harness).replace(/\s+/g, " ");
    for (const key of ["contract", "contract-documents", "contract-activities"]) {
      expect(panel).toContain(`queryKey: ["${key}", contractId]`);
      expect(seeded).toContain(`qc.setQueryData(["${key}", m.id]`);
    }
    expect(seeded).toContain("api.interceptors.request.use(");
    expect(seeded).toContain("api.interceptors.request.eject(");
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
    "components/v2/person/PersonWorkbenchTabs.tsx",
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
    // „Użyj innego CV” (12.10.2026): karta pyta o gotowe CV osoby przez
    // `useReadyCvChoice` — klucze z parametrem, których strażnik literałów
    // nie widzi. Bez zasiewu pasek „Ta osoba ma już gotowe CV” szedłby w sieć.
    const choice = withoutComments(read("components/v2/recruitment/useReadyCvChoice.tsx"));
    expect(card).toContain("useReadyCvChoice(");
    expect(choice).toContain("queryKey: candidateQueryKeys.cvDocuments(candidateId)");
    expect(harness).toMatch(/setQueryData\(\s*stageCvSourcesQueryKey\(item\.id\)/);
    expect(harness).toContain("setQueryData(candidateQueryKeys.cvDocuments(item.candidate_id)");
    expect(harness).toContain('setQueryData(["candidate-generated-cvs", item.candidate_id]');
    expect(harness).toContain('setQueryData(["central-cv-policy", null, item.id, false]');
    // Jedna liczba rzeczy do sprawdzenia (13.10.2026): QC karty i uwagi edytora.
    const checks = withoutComments(read("components/v2/recruitment/CvToClientChecks.tsx"));
    for (const fn of ["cvToClientQcQueryKey", "cvToClientIssuesQueryKey"]) {
      expect(checks).toMatch(new RegExp(`queryKey: ${fn}\\(`));
      expect(harness).toMatch(new RegExp(`setQueryData\\(\\s*${fn}\\(`));
    }
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

  it("okienko kolumny „Rekruter” czyta zasiany katalog osób i obłożenie, nie sieć", () => {
    // Oglądający harnessu to admin, więc komórka otwiera okienko edycji. Ono
    // pyta o katalog osób (stały klucz) i o pulpit „Requesty i obłożenie”
    // (klucz ze stałej, której strażnik literałów nie widzi) — oba z własnym
    // `staleTime`, więc zasiew musi być „świeży” na dłużej niż oglądanie.
    const editor = withoutComments(read("components/v2/jobs/JobRecruiterEditor.tsx"));
    expect(literalQueryKeys(editor)).toEqual(['["users-directory"]']);
    expect(editor).toContain("useRequestBoard()");
    expect(harness).toMatch(
      /setQueryData\(\["users-directory"\], DIRECTORY, \{ updatedAt: SEED_FRESH_UNTIL \}\)/,
    );
    expect(harness).toMatch(
      /setQueryData<RequestBoard>\(REQUEST_BOARD_QUERY_KEY, REQUEST_BOARD, \{\s*updatedAt: SEED_FRESH_UNTIL,?\s*\}\)/,
    );
  });
});

describe("/preview/custom-dashboard zasiewa każdy stały klucz", () => {
  const harness = withoutComments(read("app/preview/custom-dashboard/page.tsx")).replace(
    /\s+/g,
    " ",
  );
  const components = [
    "components/v2/dashboard/custom/CustomDashboard.tsx",
    // Pas „Do wysłania do klienta” stoi nad panelem i czyta jego zapytanie.
    "components/v2/dashboard/DlSendQueueBand.tsx",
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

  it("zasiewa kafelki układów ról (04.10.2026) ich własnymi stałymi", () => {
    for (const key of [
      'interviewCycleQueryKey("mine")',
      'interviewCycleQueryKey("jobs")',
      "MY_WEEK_QUERY_KEY",
      "TEAM_SIGNALS_QUERY_KEY",
      "SYSTEM_STATUS_QUERY_KEY",
      "MY_RECRUITMENTS_QUERY_KEY",
      "MY_CLIENTS_CARDS_QUERY_KEY",
      "ORDER_CHANGES_SUMMARY_KEY",
    ]) {
      expect(harness).toContain(key);
    }
  });

  it("propozycje automatu: „Zmień” czyta zasiane obłożenie, nie sieć", () => {
    // Sekcja propozycji pyta o pulpit „Requesty i obłożenie” dopiero po
    // otwarciu listy „Zmień” — kluczem ze stałej, którego strażnik literałów
    // nie widzi. Harness pokazuje propozycje, więc musi zasiać też pulpit.
    const section = withoutComments(read("components/v2/dashboard/AllocationProposalsSection.tsx"));
    expect(literalQueryKeys(section)).toEqual([]);
    expect(section).toContain("useRequestBoard({ enabled: open })");
    expect(withoutComments(read("lib/api/requestAllocation.ts"))).toContain(
      "queryKey: REQUEST_BOARD_QUERY_KEY",
    );
    expect(harness).toContain("allocation_proposals: ALLOCATION_PROPOSALS");
    expect(harness).toMatch(/setQueryData<RequestBoard>\(REQUEST_BOARD_QUERY_KEY, REQUEST_BOARD, \{ updatedAt:/);
    // Trzy przypadki z opisu: osoba z 1. priorytetem, osoba bez requestów
    // i osoba na urlopie — plus baner o braku urlopów.
    expect(harness).toContain('fit: "first", load: 0, base_matches: 22');
    expect(harness).toContain('leave_until: "2026-10-09"');
    expect(harness).toContain("allocation_leave_known: false");
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/request-allocation renderuje pulpit z propsów", () => {
  const harness = withoutComments(read("app/preview/request-allocation/page.tsx")).replace(/\s+/g, " ");

  it("montuje widok, nie kontener z zapytaniem", () => {
    // `RequestBoard` pobiera pulpit i zapisuje decyzje — harness bierze widok.
    expect(harness).toContain("<RequestBoardView");
    expect(harness).not.toMatch(/<RequestBoard[\s>]/);
    for (const file of [
      "components/v2/request-board/RequestBoard.tsx",
      "components/v2/request-board/RequestBoardFilters.tsx",
      "components/v2/request-board/LoadPanel.tsx",
      "components/v2/jobs/RecruiterChips.tsx",
      "components/v2/jobs/RequestPriorityChip.tsx",
    ]) {
      expect(literalQueryKeys(read(file)), file).toEqual([]);
    }
  });

  it("pokazuje propozycję automatu, dwie pracujące osoby i request bez rekrutera — w trzech rolach", () => {
    expect(harness).toContain("proposed: true");
    expect(harness).toMatch(/job_id: 21,[^}]*people: \[\{[^\]]*proposed: false[^\]]*\}, \{[^\]]*proposed: false/);
    expect(harness).toMatch(/job_id: 41,[^}]*people: \[\]/);
    for (const persona of ["hor:", "dl:", "recruiter:"]) expect(harness).toContain(persona);
    expect(harness).toContain("canStaff={access.canStaff}");
    expect(harness).toContain("canDecide={access.canDecide}");
  });
});

describe("/preview/new-job zasiewa każdy stały klucz", () => {
  const harness = withoutComments(read("app/preview/new-job/page.tsx")).replace(/\s+/g, " ");

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const keys = [
      ...literalQueryKeys(read("components/v2/jobs/new/NewJobPage.tsx")),
      // `ClientSinglePicker` bierze klucz z propsa — ten sam literał co w pasku źródeł.
      '["clients-lookup-new-job"]',
    ];
    expect(keys.length).toBeGreaterThan(1);
    expect(keys.filter((key) => !harness.includes(key))).toEqual([]);
    expect(read("components/v2/jobs/new/NewJobSourceBar.tsx")).toContain(
      'queryKey="clients-lookup-new-job"',
    );
  });

  it("stan `champion` pokazuje tę samą notkę co prawdziwy odczyt pliku z dodatkowymi sekcjami", () => {
    // Formularz podglądu niesie `championExtras`; prawdziwy odczyt takiego pliku
    // ustawia `championSections: "taken"` i notka mówi, dokąd te sekcje trafią.
    expect(harness).toContain("championExtras: {");
    expect(harness).toContain('championForm: true, championSections: "taken"');
  });

  it("panel „Inna rekrutacja” nie pyta serwera — lista przychodzi w stanie podglądu", () => {
    // Klucz listy ma parametry, więc `literalQueryKeys` go nie widzi: zapytanie
    // wyłącza gotowa lista (`seed`), którą strona podaje w trybie podglądu.
    const picker = read("components/v2/jobs/new/TemplateJobPicker.tsx");
    expect(picker).toContain("enabled: seed == null");
    expect(read("components/v2/jobs/new/NewJobPage.tsx")).toContain(
      "seed={preview ? (preview.templateJobs ?? []) : undefined}",
    );
    expect(harness).toContain("templateJobs:");
  });

  it("zasiewa listę kontaktów pola „Hiring manager” (klucz z parametrem)", () => {
    // `literalQueryKeys` pomija klucze z parametrem — pilnujemy go jawnie.
    expect(read("lib/hiring-manager.ts")).toContain('["hiring-manager-options", clientId]');
    expect(harness).toContain('["hiring-manager-options", 1]');
    expect(harness).toContain("const CLIENT = { id: 1,");
  });
});

describe("/preview/job-team-panel zasiewa zakładkę „Zespół” i odcina sieć", () => {
  const harness = withoutComments(read("app/preview/job-team-panel/page.tsx")).replace(/\s+/g, " ");
  // Wszystko, co montuje zakładka „Zespół” doku (`JobTeamTab`): karta zespołu,
  // wiersze Rekruter i Kategoria, okno przypisania, hiring manager klienta
  // i kontekst Priority Work.
  const components = [
    "components/v2/jobs/JobSettingsPanel.tsx",
    "components/v2/jobs/JobOwnershipPanel.tsx",
    "components/v2/jobs/JobCategoryRow.tsx",
    "components/v2/CompetenceCategoryBadge.tsx",
    "components/v2/modals/ReassignOwnerV2.tsx",
    "components/jobs/HiringManagerPicker.tsx",
    "components/jobs/HiringManagerCombobox.tsx",
    "components/v2/priority-work/JobPriorityContext.tsx",
  ];

  it("nie zostawia stałego klucza bez zasiewu", () => {
    const missing: string[] = [];
    let found = 0;
    for (const file of components) {
      for (const key of literalQueryKeys(read(file))) {
        found += 1;
        if (!harness.includes(key)) missing.push(`${file}: ${key}`);
      }
    }
    // Lista osób, lista Delivery Leadów i katalog kategorii — co najmniej te trzy.
    expect(found).toBeGreaterThanOrEqual(3);
    expect(missing).toEqual([]);
  });

  it("zasiewa klucze z parametrem — TYMI SAMYMI funkcjami i literałami co komponenty", () => {
    // `literalQueryKeys` pomija klucze z parametrem, a zakładka pyta o nie przy
    // samym wejściu (Delivery Lead klienta, Priority Work) albo po kliknięciu.
    const settings = withoutComments(read("components/v2/jobs/JobSettingsPanel.tsx"));
    expect(settings).toContain('queryKey: ["client-team", clientId]');
    expect(harness).toContain('setQueryData( ["client-team", CLIENT_ID]');

    const allocation = withoutComments(read("lib/api/requestAllocation.ts"));
    expect(allocation).toContain("queryKey: categoryRecruitersQueryKey(");
    expect(harness).toContain("setQueryData(categoryRecruitersQueryKey(CATEGORY_ID)");

    const priority = withoutComments(read("components/v2/priority-work/JobPriorityContext.tsx"));
    expect(priority).toContain("queryKey: priorityWorkQueryKeys.job(jobId)");
    expect(harness).toContain("setQueryData( priorityWorkQueryKeys.job(job.id)");
    const summary = withoutComments(read("components/v2/priority-work/AllocationWorkloadBoard.tsx"));
    expect(summary).toContain('queryKey: ["job-allocation", jobId]');
    expect(harness).toContain('setQueryData(["job-allocation", job.id]');

    const combobox = withoutComments(read("components/jobs/HiringManagerCombobox.tsx"));
    expect(combobox).toContain("queryKey: hiringManagerOptionsKey(clientId)");
    expect(harness).toContain("setQueryData( hiringManagerOptionsKey(CLIENT_ID)");
  });

  it("zasiewa listę okna „Przypisz rekrutera” kluczem z domyślnych ról pola", () => {
    const field = withoutComments(read("components/v2/forms/fields/RecruiterPickerField.tsx"));
    expect(field.replace(/\s+/g, "")).toContain('queryKey:["users","directory",roles.join(",")]');
    const roles = [...(field.match(/DEFAULT_ROLES[^=]*=\s*\[([^\]]*)\]/)?.[1] ?? "").matchAll(/"([a-z_]+)"/g)].map(
      (match) => match[1],
    );
    expect(roles.length).toBeGreaterThan(0);
    expect(harness).toContain(`["users", "directory", "${roles.join(",")}"]`);
  });

  it("pokazuje propozycję, dwie pracujące osoby i rekrutację bez rekrutera — w trzech rolach", () => {
    expect(harness).toContain("<JobTeamTab");
    for (const persona of ["dl:", "hor:", "recruiter:"]) expect(harness).toContain(persona);
    expect(harness).toContain('via: "assignment", proposed: true');
    expect(harness).toContain('via: "owner", proposed: false');
    expect(harness).toContain('via: "collaborator", proposed: false');
    expect(harness).toContain("recruiters: []");
  });

  it("odcina sieć na czas życia harnessu — przyciski nie trafiają do API", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
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
    "components/v2/cv-generator/CvResult.tsx",
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

  it("montuje widoki, nie kontenery z zapytaniami", () => {
    // `CvResultLive`/`CvGenerator` pobierają dane — harness bierze ich widoki.
    expect(harness).toContain("<CvResultView");
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

describe("/preview/permissions zasiewa ekran „Osoby i role” i nie ma sieci", () => {
  const harness = withoutComments(read("app/preview/permissions/page.tsx")).replace(/\s+/g, " ");
  const components = [
    "components/settings/admin/AdminUsersTab.tsx",
    "components/settings/admin/PermissionsTab.tsx",
    "components/settings/admin/UserModal.tsx",
  ];

  it("nie zostawia klucza, który uruchomiłby zapytanie i przerzucił na /login", () => {
    const keys = components.flatMap((file) => literalQueryKeys(read(file)));
    // Lista osób, zasady ról (zakładka i okno osoby pytają tym samym kluczem).
    expect([...new Set(keys)].sort()).toEqual([
      '["admin-section-permissions"]',
      '["admin-users"]',
    ]);
    for (const key of keys) expect(harness).toContain(key);
  });

  it("zasiewa uprawnienia każdej osoby (klucz z parametrem) i odcina sieć", () => {
    // Ołówek w `?tab=users` otwiera okno dowolnej osoby — każda musi mieć
    // zasiany odczyt, inaczej sekcja pokazałaby błąd zamiast listy.
    expect(withoutComments(read("components/settings/admin/UserModal.tsx"))).toContain(
      'queryKey: ["admin-user-permissions", userId]',
    );
    expect(harness).toContain("for (const person of PEOPLE)");
    expect(harness).toContain('qc.setQueryData(["admin-user-permissions", person.id]');
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });

  it("montuje prawdziwy ekran i prawdziwe okno osoby", () => {
    expect(harness).toContain("<AdminUsersTab embedded");
    expect(harness).toContain("<UserModal");
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

  it("stan „To nieprawda” ma pominięte pozycje i uwagę wyciszoną w „Jakość QC”", () => {
    expect(harness).toContain('dismissed: { label: "To nieprawda", data: DISMISSED }');
    expect(harness).toContain("dismissed_items:");
    expect(harness).toContain("muted: true");
  });
});

describe("/preview/cv-editor (Edytor CV 2) — edytor z pamięci, źródła z zasiewu, bez sieci", () => {
  const harness = withoutComments(read("app/preview/cv-editor/page.tsx")).replace(/\s+/g, " ");

  it("stan, zapis i pliki CV idą propsami, nie przez API", () => {
    expect(harness).toContain("editorApi={backend.editorApi}");
    // Panel „Do poprawy”: QC, uwagi i poprawki też z pamięci.
    expect(harness).toContain("issuesApi={backend.issuesApi}");
    // Asystent (Edytor CV 3, PR 4): odpowiedzi z pamięci, bez modelu.
    expect(harness).toContain("commandApi={backend.commandApi}");
    // „Historia”: wersje i treść pliku Word z pamięci.
    expect(harness).toContain("historyApi={backend.historyApi}");
    expect(harness).toContain("editorFiles={MEMORY_FILES}");
    expect(harness).toContain("sourceLoaders={SOURCE_LOADERS}");
  });

  it("zasiewa klucze panelu źródeł tymi samymi funkcjami co komponenty", () => {
    const sources = withoutComments(read("components/v2/cv-editor/CvEditorSources.tsx"));
    expect(sources).toContain('queryKey: ["cv-original", stageId]');
    expect(harness).toContain('setQueryData(["cv-original", STAGE_ID]');
    const preview = withoutComments(read("components/v2/screening-form/CandidatePreviewPane.tsx"));
    expect(preview).toContain("queryKey: candidateQueryKeys.cvDocuments(candidateId)");
    expect(harness).toContain("setQueryData(candidateQueryKeys.cvDocuments(CANDIDATE_ID)");
    expect(harness).toContain('setQueryData(["champion-profile", JOB_ID]');
    expect(harness).toContain("setQueryData(plainBriefQueryKey(JOB_ID)");
    const notes = withoutComments(read("components/v2/jobs/workbench-chrome.tsx"));
    expect(notes).toContain("queryKey: jobNotesQueryKey(candidateId, jobId)");
    expect(harness).toContain("setQueryData(jobNotesQueryKey(CANDIDATE_ID, JOB_ID)");
  });

  it("części edytora nie mają własnych stałych kluczy", () => {
    for (const file of [
      "components/v2/modals/CVBrandedEditModal.tsx",
      "components/v2/cv-editor/CvEditorAssistant.tsx",
      "components/v2/cv-editor/useCvAssistant.ts",
      "components/v2/cv-editor/CvEditorIssues.tsx",
      "components/v2/cv-editor/CvEditorSources.tsx",
      "components/v2/cv-editor/CvEditorSourcesPane.tsx",
      "components/v2/cv-editor/CvEditorToolbar.tsx",
      "components/v2/cv-editor/CvEditorWordPreview.tsx",
    ]) {
      expect(literalQueryKeys(read(file)), file).toEqual([]);
    }
  });

  it("odcina sieć na czas życia harnessu", () => {
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
    // Panel ma też sekcję propozycji automatu; jej lista „Zmień” pyta o pulpit
    // „Requesty i obłożenie”. Ten harness propozycji nie zasiewa (sekcji nie
    // ma), więc pulpitu zasiewać nie musi — dołożenie propozycji bez pulpitu
    // otworzyłoby zapytanie.
    expect(harness).not.toContain("allocation_proposals");
  });

  it("odcina sieć", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/dl-send zasiewa pas „Do wysłania do klienta” i przegląd każdej osoby", () => {
  const harness = withoutComments(read("app/preview/dl-send/page.tsx")).replace(/\s+/g, " ");
  const band = withoutComments(read("components/v2/dashboard/DlSendQueueBand.tsx"));
  // Pas i wszystko, co z niego otwiera się w harnessie: przegląd osoby (CV,
  // wymagania, screening, decyzja) i porównanie osób jednej rekrutacji.
  const components = [
    "components/v2/dashboard/DlSendQueueBand.tsx",
    "components/v2/recruitment/DlReviewPanel.tsx",
    "components/v2/recruitment/dl-review/DlReviewQueueDialog.tsx",
    "components/v2/recruitment/dl-review/CvColumn.tsx",
    "components/v2/recruitment/dl-review/DecisionPanel.tsx",
    "components/v2/recruitment/dl-review/RequirementsColumn.tsx",
    "components/v2/person/StageCvPreview.tsx",
    "components/v2/screening-form/ScreeningSummaryView.tsx",
    "components/v2/screening-form/CandidatePreviewPane.tsx",
    "hooks/useReviewSequence.ts",
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

  it("pas czyta kolejkę pulpitu jej kluczem — bez własnego zapytania", () => {
    // Pas i panel „Czeka na Ciebie” dzielą `useBoardTasks`; drugi klucz albo
    // własne `useQuery` w pasie to drugie żądanie na każdym wejściu na pulpit.
    expect(band).toContain("useBoardTasks()");
    expect(band).not.toMatch(/useQuery\b/);
    expect(withoutComments(read("lib/api/boardTasks.ts"))).toContain("queryKey: BOARD_TASKS_QUERY_KEY");
    expect(harness).toMatch(/setQueryData<BoardTasksResponse>\( ?BOARD_TASKS_QUERY_KEY/);
  });

  it("zasiewa klucze z parametrem, o które pyta przegląd osoby i „porównaj”", () => {
    const panel = withoutComments(read("components/v2/recruitment/DlReviewPanel.tsx"));
    expect(panel).toContain("queryKey: candidateQueryKeys.quickView(candidateId)");
    expect(panel).toContain('queryKey: ["job-rejection-reasons", jobId]');
    expect(panel).toContain("useDlReviewContext(candidateId, jobId)");
    expect(panel).toContain("useScreeningFormState(candidateId, jobId");
    const reviewApi = withoutComments(read("lib/api/dlReview.ts"));
    expect(reviewApi).toContain("queryKey: dlReviewContextQueryKey(jobId, candidateId)");
    expect(reviewApi).toContain("queryKey: dlReviewQueueQueryKey(jobId ?? 0)");
    const stagePreview = withoutComments(read("components/v2/person/StageCvPreview.tsx"));
    expect(stagePreview).toContain('queryKey: ["cv-generated", "dl-review", candidateId, jobId]');
    const original = withoutComments(read("components/v2/screening-form/CandidatePreviewPane.tsx"));
    expect(original).toContain('queryKey: ["cv-original", stageId]');
    expect(original).toContain("queryKey: candidateQueryKeys.cvDocuments(candidateId)");
    // Zasiew idzie po wierszach kolejki — każda osoba pasa otwiera się bez sieci.
    expect(harness).toContain("for (const row of rows) {");
    for (const seed of [
      /setQueryData\( ?candidateQueryKeys\.quickView\(row\.candidate_id\)/,
      /setQueryData\( ?\["cv-generated", "dl-review", row\.candidate_id, row\.job_id\]/,
      /setQueryData\( ?\["cv-original", row\.stage_id\]/,
      /setQueryData\( ?candidateQueryKeys\.cvDocuments\(row\.candidate_id\)/,
      /setQueryData\( ?stageBrandedQueryKey\(row\.stage_id\)/,
      /setQueryData\( ?dlReviewContextQueryKey\(row\.job_id, row\.candidate_id\)/,
      /setQueryData\( ?screeningFormQueryKey\(row\.job_id, row\.candidate_id\)/,
      /setQueryData\( ?recommendationCardQueryKey\(row\.candidate_id, row\.job_id\)/,
      /setQueryData\( ?\["job-rejection-reasons", row\.job_id\]/,
      /setQueryData\( ?dlReviewQueueQueryKey\(row\.job_id\)/,
    ]) {
      expect(harness).toMatch(seed);
    }
  });

  it("odcina sieć i montuje prawdziwy pas", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
    expect(harness).toContain("<DlSendQueueBand previewLoaders={PREVIEW_LOADERS} />");
  });
});

describe("/preview/trainee i /preview/trainees (0374) nie mają sieci", () => {
  const today = withoutComments(read("app/preview/trainee/page.tsx"));
  const panel = withoutComments(read("app/preview/trainees/page.tsx"));

  it("zasiewają klucze tymi samymi funkcjami co ekrany", () => {
    expect(today).toContain("setQueryData(traineeKeys.today(), today)");
    expect(today).toContain("setQueryData(traineeKeys.openJobs(item.id)");
    expect(panel).toContain("setQueryData(traineeKeys.overview(), overview)");
    expect(panel).toContain("setQueryData(traineeKeys.qualitySample(row.user_id)");
    expect(panel).toContain("setQueryData(traineeKeys.rules(), PREVIEW_RULES)");
    expect(panel).toContain("setQueryData(traineeKeys.rulesPreview(PREVIEW_RULES)");
  });

  it("ekrany biorą klucze z `traineeKeys`, nie z literałów", () => {
    const api = withoutComments(read("lib/api/trainee.ts"));
    expect(literalQueryKeys(api)).toEqual([]);
    expect(api).toContain("queryKey: traineeKeys.today()");
  });

  it("odcinają sieć i przywracają warstwę API przy odmontowaniu", () => {
    for (const source of [today, panel]) {
      expect(source).toContain("api.interceptors.request.use(");
      expect(source).toContain("api.interceptors.request.eject(");
      expect(source).toContain("Object.assign(traineeApi, REAL_TRAINEE_API)");
    }
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
      "components/insights/views/my-month/MyPortfolioView.tsx",
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

describe("/preview/b2b-generator (ticket 8) zasiewa stałe klucze formularza i nie ma sieci", () => {
  const harness = withoutComments(read("app/preview/b2b-generator/page.tsx"));
  const form = read("components/v2/pages/B2BContractGeneratorV2.tsx");
  // Stałe klucze samego formularza (reszta pliku to rejestr i ustawienia ról).
  const start = form.indexOf("export function GeneratorForm(");
  // Koniec komponentu = następna deklaracja najwyższego poziomu.
  const rest = form.slice(start + 1);
  const next = rest.search(/\n(?:export )?(?:async )?(?:function|const|class) /);
  const formKeys = literalQueryKeys(
    next >= 0 ? form.slice(start, start + 1 + next) : form.slice(start),
  );

  it("formularz ma stałe klucze, a harness zasiewa każdy z nich", () => {
    expect(formKeys.length).toBeGreaterThan(0);
    const normalized = harness.replace(/\s+/g, " ");
    expect(formKeys.filter((key) => !normalized.includes(key))).toEqual([]);
  });

  it("odrzuca każde żądanie", () => {
    expect(harness).toContain("api.interceptors.request.use");
  });
});

describe("/preview/plain-brief zasiewa wyjaśnienie tymi samymi kluczami co komponenty", () => {
  const harness = withoutComments(read("app/preview/plain-brief/page.tsx"));
  const api = withoutComments(read("lib/api/plainKnowledge.ts"));

  it("hooki biorą klucze z funkcji, a harness zasiewa je tymi funkcjami", () => {
    // Stałych literałów nie ma — każdy klucz buduje eksportowana funkcja.
    expect(literalQueryKeys(api)).toEqual([]);
    expect(api).toContain("queryKey: plainBriefQueryKey(jobId)");
    expect(api).toContain("queryKey: roleProfilesQueryKey(q)");
    expect(harness).toMatch(/setQueryData\(\s*plainBriefQueryKey\(JOB_ID\)/);
    expect(harness).toMatch(/setQueryData\(\s*roleProfilesQueryKey\(""\)/);
  });

  it("komponenty nie mają własnych stałych kluczy", () => {
    for (const file of [
      "components/champion/plain/PlainBriefBlock.tsx",
      "components/v2/jobs/DockCallCheatsheet.tsx",
    ]) {
      expect(literalQueryKeys(read(file)), file).toEqual([]);
    }
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/screening-form (0424) zasiewa formularz tymi samymi kluczami co komponenty", () => {
  const harness = withoutComments(read("app/preview/screening-form/page.tsx")).replace(/\s+/g, " ");
  const formApi = withoutComments(read("lib/api/screeningForm.ts"));

  it("formularz i historia biorą klucze z funkcji, a harness zasiewa je tymi funkcjami", () => {
    expect(formApi).toContain("queryKey: screeningFormQueryKey(jobId, candidateId)");
    expect(formApi).toContain("queryKey: screeningFormVersionsQueryKey(jobId, candidateId)");
    expect(harness).toMatch(/setQueryData\( ?screeningFormQueryKey\(JOB_ID, CANDIDATE_ID\)/);
    expect(harness).toMatch(/setQueryData\( ?screeningFormVersionsQueryKey\(JOB_ID, CANDIDATE_ID\)/);
  });

  it("zasiewa klucze z parametrem, o które pytają gospodarz, profil przed telefonem i podgląd", () => {
    const host = withoutComments(read("components/v2/jobs/ScreeningWorkbench.tsx"));
    expect(host).toContain('queryKey: ["job-questions", jobId]');
    expect(harness).toContain('setQueryData(["job-questions", JOB_ID]');
    const beforeCall = withoutComments(read("components/v2/screening-form/BeforeCallProfile.tsx"));
    // 14.10.2026: „W innych rekrutacjach” bez bieżącej — klucz pod `quickView`.
    expect(beforeCall).toContain("queryKey: candidateQueryKeys.quickViewExcluding(candidateId, jobId)");
    expect(harness).toMatch(/setQueryData\(\s*candidateQueryKeys\.quickViewExcluding\(CANDIDATE_ID, JOB_ID\)/);
    // 12.10.2026: „co już wiemy” — warunki z profilu i ostatnio podana stawka.
    expect(beforeCall).toContain("queryKey: candidateQueryKeys.detail(candidateId)");
    expect(beforeCall).toContain("useRateOverview(candidateId");
    expect(harness).toContain("setQueryData(candidateQueryKeys.detail(CANDIDATE_ID)");
    expect(harness).toContain("setQueryData(candidateQueryKeys.rateOverview(CANDIDATE_ID)");
    const preview = withoutComments(read("components/v2/screening-form/CandidatePreviewPane.tsx"));
    expect(preview).toContain('queryKey: ["cv-original", stageId]');
    expect(preview).toContain("queryKey: candidateQueryKeys.cvDocuments(candidateId)");
    expect(harness).toContain('setQueryData(["cv-original", STAGE_ID]');
    expect(harness).toContain("setQueryData(candidateQueryKeys.cvDocuments(CANDIDATE_ID)");
    expect(harness).toContain("setQueryData(stageBrandedQueryKey(STAGE_ID)");
    expect(harness).toContain("setQueryData(plainBriefQueryKey(JOB_ID)");
    // 12.10.2026: „Historia osoby” w podglądzie — notatki osoby i wyniki jej
    // rekrutacji pod kluczami z funkcji; bez zasiewu przycisk znika po cichu.
    const notesQuery = withoutComments(read("components/v2/pages/candidate-notes-query.ts"));
    expect(notesQuery).toContain("queryKey: candidateQueryKeys.notes(candidateId)");
    expect(preview).toContain("useCandidateNotes(candidateId, showHistory)");
    expect(harness).toContain("setQueryData(candidateQueryKeys.notes(CANDIDATE_ID)");
    const outcomesQuery = withoutComments(read("components/v2/pages/candidate-outcomes-query.ts")).replace(/\s+/g, " ");
    expect(outcomesQuery).toContain("queryKey: candidateQueryKeys.recruitmentOutcomes(candidateId,");
    expect(harness).toMatch(/setQueryData\( ?candidateQueryKeys\.recruitmentOutcomes\(CANDIDATE_ID, PREVIEW_VIEWER_SCOPE\)/);
  });

  it("zasiewa klucze wyboru gotowego CV z profilu (09.10.2026)", () => {
    const picker = withoutComments(read("components/v2/screening-form/StageCvPicker.tsx"));
    expect(picker).toContain('queryKey: ["candidate-generated-cvs", candidateId]');
    expect(picker).toContain('queryKey: ["central-cv-policy", null, stageId, false]');
    expect(harness).toContain('setQueryData(["candidate-generated-cvs", CANDIDATE_ID]');
    expect(harness).toContain('setQueryData(["central-cv-policy", null, STAGE_ID, false]');
    // 12.10.2026: CV etapu z innych rekrutacji — klucz z funkcji, nie literał.
    expect(picker).toContain("queryKey: stageCvSourcesQueryKey(stageId)");
    expect(harness).toContain("setQueryData(stageCvSourcesQueryKey(STAGE_ID)");
    const stagePreview = withoutComments(read("components/v2/person/StageCvPreview.tsx"));
    expect(stagePreview).toContain('queryKey: ["cv-generated", "dl-review", candidateId, jobId]');
    expect(harness).toContain('setQueryData(["cv-generated", "dl-review", CANDIDATE_ID, JOB_ID]');
  });

  it("komponenty formularza nie mają własnych stałych kluczy", () => {
    for (const file of [
      "components/v2/screening-form/ScreeningFullForm.tsx",
      "components/v2/screening-form/ScreeningFormHistory.tsx",
      "components/v2/screening-form/NoteFillBar.tsx",
      "components/v2/screening-form/CandidatePreviewPane.tsx",
      "components/v2/screening-form/BeforeCallProfile.tsx",
    ]) {
      expect(literalQueryKeys(read(file)), file).toEqual([]);
    }
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/client-orders zasiewa klucze zakładki „Zamówienia” i odcina sieć", () => {
  const harness = withoutComments(read("app/preview/client-orders/page.tsx")).replace(/\s+/g, " ");
  const shared = withoutComments(read("app/preview/order-groups-harness.tsx")).replace(/\s+/g, " ");
  const components = [
    "components/client-profile/orders/MultiConsultantOrdersTab.tsx",
    "components/client-profile/orders/OrdersTable.tsx",
    "components/client-profile/orders/OrderGroupPanel.tsx",
    "components/client-profile/orders/OrderLinePanel.tsx",
    "components/client-profile/orders/ContractorOrderPanel.tsx",
    "components/client-profile/orders/OrderListControls.tsx",
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

  it("zasiewa klucze z id klienta, o które zakładka pyta przy wejściu", () => {
    const tab = withoutComments(read("components/client-profile/orders/MultiConsultantOrdersTab.tsx"));
    const rateUnit = withoutComments(read("hooks/useClientDefaultRateUnit.ts"));
    expect(tab).toContain('queryKey: ["client-order-groups", clientId]');
    expect(tab).toContain('queryKey: ["dl-orders-grouped", clientId]');
    expect(rateUnit).toContain('queryKey: ["client-default-rate-unit", clientId]');
    for (const key of ["client-order-groups", "dl-orders-grouped", "client-default-rate-unit"]) {
      expect(harness).toMatch(new RegExp(`setQueryData(<[^>]*>)?\\(\\["${key}", CLIENT_ID\\]`));
    }
    // Historia i zużycie MD paneli — TYMI SAMYMI funkcjami kluczy co panele.
    expect(harness).toContain("seedOrderGroupPanels(qc, CLIENT_ID, GROUPS");
    expect(shared).toContain("orderHistoryQueryKey(clientId, group.id)");
    expect(shared).toContain("lineConsumptionsQueryKey(clientId, group.id, line.id)");
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

/** Harness bez komentarzy i z jednym odstępem — do porównań literałów. */
function flat(relativePath: string): string {
  return withoutComments(read(relativePath)).replace(/\s+/g, " ");
}

function missingLiteralKeys(harness: string, components: string[]): string[] {
  const missing: string[] = [];
  for (const file of components) {
    for (const key of literalQueryKeys(read(file))) {
      if (!harness.includes(key)) missing.push(`${file}: ${key}`);
    }
  }
  return missing;
}

describe("/preview/clients-list zasiewa listę klientów i kluczowe relacje", () => {
  const harness = flat("app/preview/clients-list/page.tsx");

  it("nie zostawia stałego klucza bez zasiewu", () => {
    expect(
      missingLiteralKeys(harness, [
        "components/v2/pages/ClientsListV2.tsx",
        "components/clients/KeyRelationshipsPanel.tsx",
      ]),
    ).toEqual([]);
  });

  it("zasiewa pierwszą stronę każdej zakładki portfela i odcina sieć", () => {
    // Klucz listy ma parametry (zakładka, fraza, strona, „moi”) — strażnik
    // literałów go nie widzi, a zakładki przełącza się jednym kliknięciem.
    for (const category of ["active", "relationship", "inactive"]) {
      expect(harness).toContain(`["clients-directory", "${category}", "", 1, false]`);
    }
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/client-profile-tabs zasiewa zakładki profilu klienta", () => {
  const harness = flat("app/preview/client-profile-tabs/page.tsx");

  it("nie zostawia stałego klucza bez zasiewu", () => {
    expect(
      missingLiteralKeys(harness, [
        "app/clients/[id]/page.tsx",
        "app/clients/[id]/ProfileTab.tsx",
        "app/clients/[id]/ProjectsTab.tsx",
        "app/clients/[id]/OwnersTab.tsx",
        "app/clients/[id]/MaterialsTab.tsx",
        "components/FrameworkContractsTab.tsx",
        "components/RateCardsTab.tsx",
        "components/AnalyticsTab.tsx",
        "components/client-profile/orders/ClientMdImportsTab.tsx",
      ]),
    ).toEqual([]);
  });

  it("zasiewa klucze z id klienta, o które pytają zakładki, i odcina sieć", () => {
    for (const key of [
      "client-team",
      "client-profile",
      "client-contacts",
      "client-knowledge",
      "framework-contracts",
      "rate-cards",
      "client-playbook",
      "client-order-groups",
      "dl-orders-grouped",
    ]) {
      expect(harness).toContain(`["${key}", CLIENT_ID]`);
    }
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/finance-results zasiewa Wyniki, Archiwum i Import MD", () => {
  const harness = flat("app/preview/finance-results/page.tsx");

  it("nie zostawia stałego klucza bez zasiewu", () => {
    expect(
      missingLiteralKeys(harness, [
        "components/finance/FinanceResultsTab.tsx",
        "components/finance/FinanceArchiveTab.tsx",
        "components/finance/MdImportWorkspace.tsx",
        "components/finance/OrderPdfsTab.tsx",
      ]),
    ).toEqual([]);
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });
});

describe("/preview/notification-settings zasiewa cztery zakładki Powiadomień i nie ma sieci", () => {
  const harness = flat("app/preview/notification-settings/page.tsx");
  // Wszystko, co montuje `NotificationsSettings`, i hooki, którymi te ekrany pytają.
  const sources = [
    "components/settings/NotificationsSettings.tsx",
    "components/settings/NotificationPreferencesPanel.tsx",
    "components/settings/MyEmailNotificationsCard.tsx",
    "components/settings/NotificationRoleMatrix.tsx",
    "components/settings/NotificationDeliverySettings.tsx",
    "lib/api/notificationPreferences.ts",
    "lib/api/notificationRoles.ts",
    "lib/api/userPreferences.ts",
    "lib/api/emailNotifications.ts",
  ];

  it("ekrany pytają wyłącznie nazwanymi kluczami — żaden literał nie umknie zasiewowi", () => {
    expect(missingLiteralKeys(harness, sources)).toEqual([]);
    // Każde `useQuery` tych ekranów bierze klucz ze stałej; nowy klucz
    // dopisany literałem wywróci asercję wyżej, nowa stała — tę niżej.
    const named = sources.flatMap((file) =>
      [...withoutComments(read(file)).matchAll(/useQuery(?:<[^>]*>)?\(\{\s*queryKey:\s*([A-Za-z_]+)/g)].map(
        (match) => match[1],
      ),
    );
    expect([...new Set(named)].sort()).toEqual([
      "MY_EMAIL_NOTIFICATIONS_QUERY_KEY",
      "NOTIFICATION_DELIVERY_QUERY_KEY",
      "USER_PREFERENCES_QUERY_KEY",
      "notificationPreferencesQueryKey",
      "notificationRolesQueryKey",
    ]);
    for (const key of named) expect(harness).toContain(`qc.setQueryData(${key},`);
  });

  it("odcina sieć i montuje prawdziwy ekran", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
    expect(harness).toContain("<NotificationsSettings defaultTab={defaultTab} />");
  });
});

describe("/preview/cv-to-client zasiewa kartę, „Z czego powstało” i liczbę rzeczy do sprawdzenia", () => {
  const harness = withoutComments(read("app/preview/cv-to-client/page.tsx"));
  const checks = withoutComments(read("components/v2/recruitment/CvToClientChecks.tsx"));
  const generator = withoutComments(read("components/v2/cv-generator/useCvGenerator.ts"));
  const choice = withoutComments(read("components/v2/recruitment/useReadyCvChoice.tsx"));

  it("klucze pochodzą z funkcji komponentów, nie z kopii", () => {
    for (const fn of ["cvToClientQcQueryKey", "cvToClientIssuesQueryKey"]) {
      expect(checks).toMatch(new RegExp(`queryKey: ${fn}\\(`));
      expect(harness).toMatch(new RegExp(`setQueryData\\(\\s*${fn}\\(`));
    }
    expect(generator).toMatch(/queryKey: cvAiSourcesQueryKey\(/);
    expect(harness).toMatch(/setQueryData\(\s*cvAiSourcesQueryKey\(/);
    for (const fn of ["cvToClientRowsQueryKey", "stageBrandedQueryKey", "stageCvSourcesQueryKey"]) {
      expect(harness).toMatch(new RegExp(`setQueryData\\(\\s*${fn}\\(`));
    }
    expect(choice).toContain("queryKey: candidateQueryKeys.cvDocuments(candidateId)");
    expect(harness).toContain("setQueryData(candidateQueryKeys.cvDocuments(person.candidateId)");
  });

  it("zasiewa klucze generatora z parametrem (proces, pliki, reguły klienta)", () => {
    // Zmiana trybu obróbki zmienia klucz procesów — oba tryby muszą być zasiane.
    expect(generator).toContain('queryKey: ["cv-gen-recruitments", candidateId, contentMode]');
    expect(harness).toContain('["cv-gen-recruitments", person.candidateId, mode]');
    expect(harness).toContain('for (const mode of ["polished", "tailored"])');
    expect(generator).toContain('queryKey: ["cv-gen-sources", candidateId]');
    expect(harness.replace(/\s+/g, " ")).toContain('setQueryData( ["cv-gen-sources", person.candidateId]');
    expect(harness).toContain('setQueryData(["central-cv-policy", CLIENT_ID, person.stageId, false]');
    expect(harness).toContain('setQueryData(["client-cv-rule", CLIENT_ID]');
  });

  it("odcina sieć na czas życia harnessu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });

  it("miniatura, okno stron i „Pobierz PDF” biorą przykładowe pliki z public/, nie API", () => {
    // Bez `loadStageCvPdf` karta woła `fetchStageCvPdf` (odczyt CV etapu i POST
    // `…/preview-pdf`) — w harnessie zablokowane, a miniatura byłaby samą ikoną.
    const card = withoutComments(read("components/v2/recruitment/CvToClientCard.tsx"));
    expect(card).toContain("<CvFirstPageThumb");
    expect(card).toContain("loadStageCvPdf(cvStageId)");
    expect(card).toContain('loadStageCvPdf(cvStageId, { download: "card" })');
    expect(harness).toContain("loadStageCvPdf={loadPreviewPages}");
    expect(harness).toContain("loadStageCvFile={loadPreviewFile}");
    expect(harness).toContain('"/preview/cv-to-client/cv-firmowe-przyklad.pdf"');
    expect(existsSync(join(process.cwd(), "public/preview/cv-to-client/cv-firmowe-przyklad.pdf"))).toBe(true);
  });
});
