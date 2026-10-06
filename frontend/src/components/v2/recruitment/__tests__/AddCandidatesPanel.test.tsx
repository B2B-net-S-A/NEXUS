import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateSourceTab } from "@/components/v2/recruitment/types";

const addToJob = vi.fn();
const dismiss = vi.fn();
const startRun = vi.fn();
const bulkAdd = vi.fn();
const factsApi = vi.fn();
const countsApi = vi.fn();
const openedApi = vi.fn();
const matchScores = vi.fn();
const championGet = vi.fn();
const classifyRows = vi.fn();
const listPage = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
let similarPayload: unknown = undefined;

function entry(id: number, name: string, origins: string[], extra: Record<string, unknown> = {}) {
  const { postingRecent = false, sources, ...row } = extra as {
    postingRecent?: boolean;
    sources?: string[];
  } & Record<string, unknown>;
  return {
    row: {
      kind: "proposal",
      key: `proposal:${id}`,
      candidateId: id,
      fullName: name,
      rateLabel: "150 zł/h",
      availabilityLabel: "od zaraz",
      fitScore: 82,
      warnings: [],
      sources: sources ?? (origins.includes("run") ? ["full_base"] : ["similar_projects"]),
      reason: null,
      isNew: false,
      previouslyDismissed: false,
      runId: null,
      ...row,
    },
    detail: {
      origins,
      title: "Java Developer",
      eligibility: null,
      firstSeenAt: null,
      postingRecent,
      postingSeenAt: null,
    },
  };
}

const proposalsState = {
  entries: [] as ReturnType<typeof entry>[],
  adding: false,
  addToJob: (...a: unknown[]) => addToJob(...a),
  dismiss: (...a: unknown[]) => dismiss(...a),
  dismissing: false,
  status: {
    run: {
      data: undefined as unknown,
      runId: null as string | null,
      starting: false,
      running: false,
      error: null,
      offset: 0,
      setOffset: vi.fn(),
      fetching: false,
    },
    startRun: () => startRun(),
    retryRun: vi.fn(),
    latestRun: null,
    engineDegraded: false,
    settled: true,
    inbox: { isError: false, error: null, hasMore: false, loadingMore: false, loadMore: vi.fn() },
    retryEngine: vi.fn(),
  },
};

vi.mock("@/components/v2/recruitment/useJobProposals", () => ({
  useJobProposals: () => proposalsState,
}));
vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...a: unknown[]) => bulkAdd(...a) },
  candidateSearchApi: { matchScores: (...a: unknown[]) => matchScores(...a) },
}));
vi.mock("@/lib/job-proposals-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: {
      ...actual.jobProposalsApi,
      facts: (...a: unknown[]) => factsApi(...a),
      counts: (...a: unknown[]) => countsApi(...a),
      opened: (...a: unknown[]) => openedApi(...a),
    },
  };
});
vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: () => Promise.resolve({ all_of: [] }) },
  requirementLabels: () => [],
}));
vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
  api: { get: vi.fn() },
  championApi: { get: (...a: unknown[]) => championGet(...a) },
}));
vi.mock("@/lib/requirement-row-kinds", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/requirement-row-kinds")>();
  return { ...actual, classifyRequirementRows: (...a: unknown[]) => classifyRows(...a) };
});
vi.mock("@/components/v2/pages/candidate-list-query", () => ({
  fetchCandidateListPage: (...a: unknown[]) => listPage(...a),
}));
vi.mock("@/lib/similar-jobs-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/similar-jobs-api")>();
  return { ...actual, useSimilarJobs: () => ({ data: similarPayload }) };
});
vi.mock("@/components/v2/jobs/SimilarJobsPanel", () => ({
  SIMILAR_TAB_DESCRIPTION: "Opis podobnych rekrutacji.",
  useSimilarJobsTab: (_jobId: number, opts: { enabled: boolean }) => ({
    toolbar: <div data-testid="similar-toolbar" />,
    body: <div data-testid="similar-body" data-enabled={String(opts.enabled)} />,
    footer: <div data-testid="similar-footer" />,
    sidePane: undefined,
    onEscapeKeyDown: () => {},
  }),
}));
vi.mock("@/components/v2/jobs/ScreenedOutSection", () => ({
  ScreenedOutSection: () => <div data-testid="screened-out" />,
}));
vi.mock("@/components/v2/recruitment/PersonPreview", () => ({
  PersonPreview: (props: {
    name: string;
    source?: { line: string; subline?: string | null } | null;
    position: { index: number; total: number };
    selection: { label: string; onToggle: () => void; checked: boolean };
    extra?: { title: string } | null;
  }) => (
    <div data-testid="person-preview">
      <span data-testid="preview-name">{props.name}</span>
      <span data-testid="preview-source">{props.source?.line}</span>
      <span data-testid="preview-position">
        {props.position.index + 1} z {props.position.total}
      </span>
      {props.extra ? <span data-testid="preview-extra">{props.extra.title}</span> : null}
      <button type="button" onClick={props.selection.onToggle} aria-pressed={props.selection.checked}>
        {props.selection.label}
      </button>
    </div>
  ),
}));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError, showSuccess, showActionToast: vi.fn() }),
}));
vi.mock("@/components/talent-radar/FullCandidateSearchStatus", () => ({
  FullCandidateSearchStatus: () => <div data-testid="run-status" />,
}));

import { AddCandidatesPanel } from "@/components/v2/recruitment/AddCandidatesPanel";

const JOB = { id: 5, title: "Analityk KYC", remote_policy: "remote", champion_profile: null };
// „Szukaj w bazie” to trzy zapytania po kolei (Champion → rodzaje wierszy →
// lista) — domyślna sekunda `findBy` bywa za krótka na obciążonym runnerze.
const SLOW = { timeout: 5000 };

function panelProps(overrides: Record<string, unknown> = {}) {
  return {
    open: true,
    onOpenChange: vi.fn(),
    jobId: 5,
    job: JOB,
    tab: "base" as CandidateSourceTab,
    onTabChange: vi.fn(),
    budgetHourly: 160,
    pipelineCandidateIds: [99],
    onOpenManualSearch: vi.fn(),
    onOpenChampionSearch: vi.fn(),
    onOpenFullList: vi.fn(),
    ...overrides,
  };
}

function renderPanel(overrides: Record<string, unknown> = {}) {
  const props = panelProps(overrides);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (next: Record<string, unknown> = {}) => (
    <QueryClientProvider client={qc}>
      <AddCandidatesPanel {...props} {...next} />
    </QueryClientProvider>
  );
  const utils = render(tree());
  return { props, rerender: (next: Record<string, unknown> = {}) => utils.rerender(tree(next)) };
}

describe("AddCandidatesPanel — okno „Kandydaci do dodania”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    proposalsState.entries = [];
    proposalsState.status.run.data = undefined;
    proposalsState.status.run.runId = null;
    proposalsState.status.run.running = false;
    proposalsState.status.settled = true;
    similarPayload = undefined;
    factsApi.mockResolvedValue({ job_id: 5, items: [] });
    openedApi.mockResolvedValue({ job_id: 5, recorded: true });
    proposalsState.status.inbox.hasMore = false;
    countsApi.mockResolvedValue({
      job_id: 5,
      days: 7,
      postings_recent: 0,
      base: 0,
      screened_out: 0,
      not_searchable_must: [],
    });
    championGet.mockResolvedValue({ data: { champion_profile: null } });
    classifyRows.mockResolvedValue([]);
    listPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  });

  it("zamknięte okno nie montuje treści ani zapytań", () => {
    renderPanel({ open: false });
    expect(screen.queryByTestId("add-candidates-panel")).toBeNull();
    expect(countsApi).not.toHaveBeenCalled();
  });

  it("cztery zakładki źródeł z liczbami; klik zmienia zakładkę przez stronę", async () => {
    similarPayload = { reassignable_people: 19, other_people: 6 };
    proposalsState.entries = [
      entry(1, "Anna Baza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Piotr Ogłoszenie", ["inbox"], { sources: ["job_board"], postingRecent: true }),
      entry(3, "Ola Ogłoszenie", ["inbox"], { sources: ["new_cv"], postingRecent: true }),
    ];
    const { props } = renderPanel();
    const tabs = within(await screen.findByRole("tablist", { name: "Źródło kandydatów" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Podobne rekrutacje· 25",
      "Nowi z ogłoszeń· 2",
      "Propozycje z bazy· 1",
      "Szukaj w bazie",
    ]);
    expect(screen.getByRole("tab", { name: /Propozycje z bazy/ })).toHaveAttribute("aria-selected", "true");

    await userEvent.click(screen.getByRole("tab", { name: /Nowi z ogłoszeń/ }));
    expect(props.onTabChange).toHaveBeenCalledWith("postings");
  });

  it("wejście w „Propozycje z bazy” zapisuje otwarcie raz, inne zakładki nie", async () => {
    const { rerender } = renderPanel({ tab: "postings" });
    await screen.findByRole("tablist", { name: "Źródło kandydatów" });
    expect(openedApi).not.toHaveBeenCalled();
    rerender({ tab: "base" });
    await waitFor(() => expect(openedApi).toHaveBeenCalledWith(5));
    rerender({ tab: "postings" });
    rerender({ tab: "base" });
    expect(openedApi).toHaveBeenCalledTimes(1);
  });

  it("tylko do odczytu nie zapisuje otwarcia", async () => {
    renderPanel({ readOnly: true });
    await screen.findByRole("tablist", { name: "Źródło kandydatów" });
    await new Promise((r) => setTimeout(r, 0));
    expect(openedApi).not.toHaveBeenCalled();
  });

  it("skrzynka z kolejnymi stronami: zakładka mówi liczbę z serwera, nie wczytaną część", async () => {
    proposalsState.status.inbox.hasMore = true;
    countsApi.mockResolvedValue({
      job_id: 5,
      days: 7,
      postings_recent: 0,
      base: 240,
      screened_out: 0,
      not_searchable_must: [],
    });
    proposalsState.entries = [entry(1, "Anna Baza", ["inbox"], { sources: ["full_base"] })];
    renderPanel();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /Propozycje z bazy/ })).toHaveTextContent("240"),
    );
  });

  it("„Propozycje z bazy” i „Nowi z ogłoszeń” dzielą listę — nikt nie wypada i nikt się nie dubluje", async () => {
    proposalsState.entries = [
      entry(1, "Anna Baza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Piotr Ogłoszenie", ["inbox"], { sources: ["job_board"], postingRecent: true }),
      entry(3, "Ola Przegląd", ["run"]),
    ];
    const { rerender } = renderPanel();
    const base = await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(within(base).getByText("Anna Baza")).toBeTruthy();
    expect(within(base).getByText("Ola Przegląd")).toBeTruthy();
    expect(within(base).queryByText("Piotr Ogłoszenie")).toBeNull();

    rerender({ tab: "postings" });
    const postings = await screen.findByRole("list", { name: "Nowi z ogłoszeń" });
    expect(within(postings).getByText("Piotr Ogłoszenie")).toBeTruthy();
    expect(within(postings).queryByText("Anna Baza")).toBeNull();
    // Zgłoszenia odłożone przez przegląd AI stoją pod listą z ogłoszeń.
    expect(screen.getByTestId("screened-out")).toBeTruthy();
  });

  it("zaznaczenie aktualizuje stopkę, dodanie idzie przez propozycje", async () => {
    proposalsState.entries = [
      entry(1, "Anna Kowalczyk", ["inbox"]),
      entry(2, "Piotr Nowak", ["similar"], { warnings: ["over_budget"] }),
    ];
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(within(list).getByText("Ponad budżet")).toBeTruthy();
    const submit = screen.getByTestId("add-candidates-submit");
    expect(submit).toBeDisabled();

    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Anna Kowalczyk" }));
    expect(screen.getByTestId("add-candidates-summary")).toHaveTextContent(
      "1 zaznaczonych trafi do »Nowych«, zarezerwowanych dla Ciebie na 12 h.",
    );
    expect(submit).toHaveTextContent("Dodaj 1 do Nowych");
    await userEvent.click(submit);
    expect(addToJob).toHaveBeenCalledWith([1]);
    expect(bulkAdd).not.toHaveBeenCalled();
  });

  it("weto HM blokuje zaznaczenie, ostrzeżenie zostaje widoczne", async () => {
    proposalsState.entries = [
      {
        ...entry(4, "Jan Weto", ["inbox"]),
        detail: {
          origins: ["inbox"],
          title: null,
          firstSeenAt: null,
          postingRecent: false,
          postingSeenAt: null,
          eligibility: {
            reason_code: "hm_veto",
            reason: "Brak bankowości",
            assignment_allowed: false,
            visibility: "warn",
            severity: "hard",
            secondary: [],
          },
        },
      } as never,
    ];
    renderPanel();
    expect(await screen.findByText("Weto HM: Brak bankowości")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Jan Weto" })).toBeDisabled();
  });

  it("klik w nazwisko otwiera podgląd osoby obok okna — tak samo jak w podobnych rekrutacjach", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Bartek Drugi", ["inbox"], { sources: ["full_base"], reason: "Spełnia: Java, SQL" }),
    ];
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(screen.queryByTestId("person-preview")).toBeNull();

    await userEvent.click(within(list).getByRole("button", { name: "Bartek Drugi" }));
    const preview = await screen.findByTestId("person-preview");
    expect(within(preview).getByTestId("preview-name")).toHaveTextContent("Bartek Drugi");
    expect(within(preview).getByTestId("preview-source")).toHaveTextContent("Cała baza");
    expect(within(preview).getByTestId("preview-position")).toHaveTextContent("2 z 2");

    // Zaznaczenie z karty i z listy to to samo zaznaczenie.
    await userEvent.click(within(preview).getByRole("button", { name: "Dodaj tę osobę do „Nowych”" }));
    expect(within(list).getByRole("checkbox", { name: "Zaznacz Bartek Drugi" })).toBeChecked();
    expect(screen.getByTestId("add-candidates-submit")).toHaveTextContent("Dodaj 1 do Nowych");

    // Ten sam przycisk przy wierszu zamyka kartę.
    await userEvent.click(within(list).getByRole("button", { name: "Podgląd: Bartek Drugi" }));
    expect(screen.queryByTestId("person-preview")).toBeNull();
  });

  it("„Pomiń” przy osobie pyta o powód i pomija ją tą samą drogą co ekran propozycji", async () => {
    proposalsState.entries = [entry(7, "Zenon Pominięty", ["inbox"], { sources: ["full_base"] })];
    renderPanel();
    await screen.findByRole("list", { name: "Propozycje z bazy" });
    await userEvent.click(screen.getByRole("button", { name: "Pomiń: Zenon Pominięty" }));
    const dialog = await screen.findByRole("dialog", { name: "Dlaczego pomijasz tę osobę?" });
    await userEvent.click(within(dialog).getByLabelText("Za drogi"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(dismiss).toHaveBeenCalledWith([7], { reason: "too_expensive" });
  });

  it("bez prawa zapisu okno jest do odczytu: bez dodawania i bez „Pomiń”", async () => {
    proposalsState.entries = [entry(1, "Anna Pierwsza", ["inbox"])];
    renderPanel({ readOnly: true });
    await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(screen.queryByTestId("add-candidates-submit")).toBeNull();
    expect(screen.queryByRole("button", { name: /Pomiń:/ })).toBeNull();
    expect(screen.getByTestId("add-candidates-summary")).toHaveTextContent("Masz tu tylko podgląd");
    expect(screen.getByRole("checkbox", { name: "Zaznacz Anna Pierwsza" })).toBeDisabled();
  });

  it("fakty zamiast pustych pól, historia u klienta i sortowanie „najpierw byli u tego klienta”", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["similar"], { rateLabel: null, availabilityLabel: null, fitScore: null, reason: "Był(a) w podobnym projekcie: X" }),
      entry(2, "Bartek Drugi", ["similar"], { rateLabel: null, availabilityLabel: null, fitScore: null, reason: "Był(a) w podobnym projekcie: Y" }),
    ];
    factsApi.mockResolvedValue({
      job_id: 5,
      items: [
        {
          candidate_id: 1, title: "Tester", company: null, years_experience: 3, city: "Łódź",
          max_onsite_days_per_week: null, remote_modes: [], availability_status: null, availability_date: null,
          expected_rate_hourly: null, expected_rate_currency: null, expected_rate_redacted: false, client_history: null,
        },
        {
          candidate_id: 2, title: "Java Developer", company: "Firma", years_experience: 8, city: "Gdańsk",
          max_onsite_days_per_week: 0, remote_modes: [], availability_status: null, availability_date: null,
          expected_rate_hourly: 170, expected_rate_currency: "PLN", expected_rate_redacted: false,
          cv_uploaded_on: "2019-04-02",
          client_history: { job_id: 77, title: "Senior Java", furthest_stage: "cv_sent", furthest_stage_label: "CV Wysłane", outcome: "rejected", last_moved_at: null },
        },
      ],
    });
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await within(list).findByText("Java Developer @ Firma · 8 lat dośw. · Gdańsk · tylko zdalnie · 170 zł/h");
    expect(within(list).getByText("Tester · 3 lata dośw. · Łódź")).toBeTruthy();
    expect(
      within(list).getByText("Był(a) u tego klienta: Senior Java — doszedł(a) do etapu „CV Wysłane” (odrzucony/a)"),
    ).toBeTruthy();
    const cvBadges = within(list).getAllByTestId("cv-year-badge");
    expect(cvBadges).toHaveLength(1);
    expect(cvBadges[0]).toHaveTextContent("CV z 2019");
    // Domyślnie na górze osoba z historią u klienta.
    const names = () => within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names()).toEqual(["Zaznacz Bartek Drugi", "Zaznacz Anna Pierwsza"]);
    await userEvent.click(screen.getByRole("button", { name: "Kolejność propozycji" }));
    expect(names()).toEqual(["Zaznacz Anna Pierwsza", "Zaznacz Bartek Drugi"]);
    expect(factsApi).toHaveBeenCalledWith(5, [1, 2], expect.anything());
  });

  it("„Policz dopasowanie dla N”: wynik w miejscu „nie policzono”, niezmierzony = „Ocena niepełna”", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["similar"], { fitScore: null }),
      entry(2, "Bartek Drugi", ["similar"], { fitScore: null }),
      entry(3, "Cezary Trzeci", ["inbox"], { fitScore: 64 }),
    ];
    matchScores.mockResolvedValue({
      scores: { "1": 71.4 },
      breakdowns: { "2": { total: null, measurement: "missing_index" } },
      profile_key: "p:1",
    });
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(within(list).getAllByText("nie policzono")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 2/ }));
    await within(list).findByText("71%");
    expect(within(list).getByText("Ocena niepełna")).toBeTruthy();
    expect(within(list).getByText("64%")).toBeTruthy();
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect([...matchScores.mock.calls[0][1]].sort()).toEqual([1, 2]);
    expect(screen.queryByRole("button", { name: /Policz dopasowanie/ })).toBeNull();
  });

  it("po dodaniu osoby policzone wyniki pozostałych zostają (nie wracają do „liczę…”)", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["similar"], { fitScore: null }),
      entry(2, "Bartek Drugi", ["similar"], { fitScore: null }),
      entry(3, "Cezary Trzeci", ["similar"], { fitScore: null }),
    ];
    matchScores.mockResolvedValue({ scores: { "1": 81, "2": 72, "3": 63 }, breakdowns: {}, profile_key: "p:1" });
    const { rerender } = renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 3/ }));
    await within(list).findByText("81%");

    proposalsState.entries = proposalsState.entries.filter((e) => e.row.candidateId !== 1);
    rerender();

    const after = screen.getByRole("list", { name: "Propozycje z bazy" });
    expect(within(after).getByText("72%")).toBeTruthy();
    expect(within(after).getByText("63%")).toBeTruthy();
    expect(within(after).queryByText("liczę…")).toBeNull();
    expect(matchScores).toHaveBeenCalledTimes(1);
  });

  it("błąd liczenia to „nie policzono — ponów”, nigdy 0", async () => {
    proposalsState.entries = [entry(1, "Anna Pierwsza", ["similar"], { fitScore: null })];
    matchScores.mockRejectedValueOnce({ response: { status: 500 } });
    renderPanel();
    await screen.findByRole("list", { name: "Propozycje z bazy" });
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 1/ }));
    const retry = await screen.findByRole("button", { name: "nie policzono — ponów" });
    expect(screen.queryByText("0%")).toBeNull();
    matchScores.mockResolvedValueOnce({ scores: { "1": 55 }, breakdowns: {}, profile_key: "p:1" });
    await userEvent.click(retry);
    await screen.findByText("55%");
  });

  it("„Przeszukaj całą bazę (AI)” z menu startuje przegląd raz na żądanie i nigdy przy otwarciu", async () => {
    const { rerender } = renderPanel();
    await screen.findByTestId("add-candidates-panel");
    expect(startRun).not.toHaveBeenCalled();

    rerender({ fullReviewRequest: 1 });
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1));
    rerender({ fullReviewRequest: 1 });
    expect(startRun).toHaveBeenCalledTimes(1);
    rerender({ fullReviewRequest: 2 });
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(2));
  });

  it("żądanie przeglądu nie dubluje skanu, który już trwa — i jest oddawane stronie", async () => {
    proposalsState.status.run.running = true;
    const onFullReviewHandled = vi.fn();
    renderPanel({ fullReviewRequest: 1, onFullReviewHandled });
    await screen.findByTestId("add-candidates-panel");
    await waitFor(() => expect(onFullReviewHandled).toHaveBeenCalledTimes(1));
    expect(startRun).not.toHaveBeenCalled();
  });

  it("czeka z decyzją, aż stan zapamiętanego przeglądu będzie znany", async () => {
    // Przegląd przywrócony z pamięci przeglądarki: jest id, danych jeszcze nie ma.
    proposalsState.status.run.runId = "run-7";
    const onFullReviewHandled = vi.fn();
    const { rerender } = renderPanel({ fullReviewRequest: 1, onFullReviewHandled });
    await screen.findByTestId("add-candidates-panel");
    expect(startRun).not.toHaveBeenCalled();
    expect(onFullReviewHandled).not.toHaveBeenCalled();

    // Dane doszły: przegląd trwa — nowego nie startujemy.
    proposalsState.status.run.data = { run_id: "run-7", state: "running", results: [] };
    rerender({ fullReviewRequest: 1, onFullReviewHandled });
    await waitFor(() => expect(onFullReviewHandled).toHaveBeenCalledTimes(1));
    expect(startRun).not.toHaveBeenCalled();
  });

  it("ponowne otwarcie okna nie startuje przeglądu drugi raz (strona zeruje żądanie)", async () => {
    const onFullReviewHandled = vi.fn();
    const { rerender } = renderPanel({ fullReviewRequest: 1, onFullReviewHandled });
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1));
    expect(onFullReviewHandled).toHaveBeenCalledTimes(1);
    // Strona wyzerowała żądanie; okno zamknięte i otwarte ponownie (nowy montaż).
    rerender({ open: false, fullReviewRequest: null });
    rerender({ open: true, fullReviewRequest: null });
    await screen.findByTestId("add-candidates-panel");
    expect(startRun).toHaveBeenCalledTimes(1);
  });

  it("„Pełna lista z filtrami i shortlista” zamyka okno i otwiera ekran „Do przejrzenia”", async () => {
    const { props } = renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Pełna lista z filtrami i shortlista" }));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onOpenFullList).toHaveBeenCalled();
  });

  it("„Podobne rekrutacje” pytają o swoje dane dopiero po wejściu w zakładkę", async () => {
    const { rerender } = renderPanel();
    await screen.findByTestId("add-candidates-panel");
    expect(screen.queryByTestId("similar-body")).toBeNull();
    rerender({ tab: "similar" });
    const body = await screen.findByTestId("similar-body");
    await waitFor(() => expect(body).toHaveAttribute("data-enabled", "true"));
    expect(screen.getByTestId("similar-toolbar")).toBeTruthy();
    expect(screen.getByTestId("similar-footer")).toBeTruthy();
  });

  describe("„Szukaj w bazie” — po słowach z Championa", () => {
    const withRows = () => {
      championGet.mockResolvedValue({
        data: {
          champion_profile: {
            search: { requirements: [["KYC", "AML"], ["bankow*"]], exclude: ["junior"] },
          },
        },
      });
      classifyRows.mockResolvedValue([true, false]);
    };

    it("szuka samo, pokazuje słowa, wyniki z trafieniami i to, po czym nie szukamy", async () => {
      withRows();
      countsApi.mockResolvedValue({
        job_id: 5, days: 7, postings_recent: 0, base: 0, screened_out: 0,
        not_searchable_must: ["Minimum 5 lat doświadczenia w analizie biznesowej"],
      });
      listPage.mockResolvedValue({
        items: [
          {
            id: 31, name: "Marta", lastname: "Wilczek", linkedin_current_title: "Analityk KYC",
            years_it_experience: 8, city: "Warszawa", expected_rate_hourly: 90, expected_rate_currency: "PLN",
            match_snippets: [{ field: "Treść CV", text: "projekt KYC dla banku", highlights: [[8, 11]] }],
          },
        ],
        total: 86, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: { "31": 84 }, breakdowns: {} });
      renderPanel({ tab: "search" });

      const words = await screen.findByRole("list", { name: "Wymagania do wyszukiwania" }, SLOW);
      expect(within(words).getByText("Musi mieć")).toBeTruthy();
      expect(within(words).getByText("KYC")).toBeTruthy();
      expect(within(words).getByText("AML")).toBeTruthy();
      expect(within(words).getByText("Mile widziane")).toBeTruthy();
      expect(within(words).getByText("bankow*")).toBeTruthy();
      expect(within(words).getByText("junior")).toBeTruthy();

      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      expect(within(results).getByText("Marta Wilczek")).toBeTruthy();
      expect(within(results).getByText("Analityk KYC · 8 lat dośw. · Warszawa · 90 zł/h")).toBeTruthy();
      expect(within(results).getByText("KYC", { selector: "strong" })).toBeTruthy();
      await within(results).findByText("84%");
      expect(screen.getByTestId("search-base-summary")).toHaveTextContent("Znaleziono osób: 86");
      expect(screen.getByText("Minimum 5 lat doświadczenia w analizie biznesowej")).toBeTruthy();
      expect(screen.getByRole("tab", { name: /Szukaj w bazie/ })).toHaveTextContent("86");

      // Zapytanie: wiersz technologii obowiązkowy, reszta tylko podnosi; bez osób z rekrutacji.
      const params = listPage.mock.calls[0][0] as Record<string, unknown>;
      expect(params.q_any_group).toEqual(["KYC|AML"]);
      expect(params.q_preferred_group).toEqual(["bankow*"]);
      expect(params.q_none).toEqual(["junior"]);
      expect(params.recruitment_id).toEqual([5]);
      expect(params.recruitment_match).toBe("not_assigned");
      expect(params.sort).toBe("match");
      expect(params.page_size).toBe(20);
    });

    it("dodanie idzie do „Nowych” ze źródłem wyszukiwania; podgląd pokazuje trafienia", async () => {
      withRows();
      listPage.mockResolvedValue({
        items: [
          { id: 31, name: "Marta", lastname: "Wilczek", match_snippets: [{ field: "Treść CV", text: "KYC", highlights: [[0, 3]] }] },
          { id: 32, name: "Hanna", lastname: "Pietrzyk", match_snippets: [] },
        ],
        total: 2, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
      bulkAdd.mockResolvedValue({ added: [32], skipped: [], warnings: [], total_added: 1, total_skipped: 0 });
      renderPanel({ tab: "search" });
      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);

      await userEvent.click(within(results).getByRole("button", { name: "Marta Wilczek" }));
      const preview = await screen.findByTestId("person-preview");
      expect(within(preview).getByTestId("preview-extra")).toHaveTextContent("Trafienia słów");
      expect(within(preview).getByTestId("preview-source")).toHaveTextContent("po słowach z Championa");

      await userEvent.click(within(results).getByRole("checkbox", { name: "Zaznacz Hanna Pietrzyk" }));
      await userEvent.click(screen.getByTestId("search-base-submit"));
      await waitFor(() =>
        expect(bulkAdd).toHaveBeenCalledWith(5, {
          candidate_ids: [32],
          initial_stage_legacy: "new",
          source: "manual_search",
        }),
      );
      await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Dodano do Nowych: 1."));
    });

    it("bez słów w Championie nie udaje wyników całej bazy — odsyła do Championa i ręcznego szukania", async () => {
      const { props } = renderPanel({ tab: "search" });
      const empty = await screen.findByTestId("search-base-empty", undefined, SLOW);
      expect(listPage).not.toHaveBeenCalled();
      await userEvent.click(within(empty).getByRole("button", { name: "Otwórz Championa" }));
      expect(props.onOpenChampionSearch).toHaveBeenCalled();
      await userEvent.click(within(empty).getByRole("button", { name: "Szukaj ręcznie" }));
      expect(props.onOpenManualSearch).toHaveBeenCalled();
      expect(props.onOpenChange).toHaveBeenCalledWith(false);
    });

    it("awaria wyszukiwania to błąd z „Ponów”, nie pusta lista", async () => {
      withRows();
      listPage.mockRejectedValue({ response: { status: 500, data: {} } });
      renderPanel({ tab: "search" });
      const alert = await screen.findByRole("alert", undefined, SLOW);
      expect(alert).toHaveTextContent("Nie udało się wyszukać w bazie.");
      expect(screen.queryByRole("list", { name: "Wyniki wyszukiwania" })).toBeNull();
    });
  });
});
