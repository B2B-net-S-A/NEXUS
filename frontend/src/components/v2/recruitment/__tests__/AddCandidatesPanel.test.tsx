import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateWindowTab } from "@/components/v2/recruitment/types";

const addToJob = vi.fn();
const undoAdd = vi.fn();
const removeFromRecruitment = vi.fn();
const manualPanel = vi.fn();
const dismiss = vi.fn();
const startRun = vi.fn();
const bulkAdd = vi.fn();
const factsApi = vi.fn();
const countsApi = vi.fn();
const openedApi = vi.fn();
const matchScores = vi.fn();
const championGet = vi.fn();
const hiddenApi = vi.fn();
const apiGet = vi.fn();
const apiPut = vi.fn();
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
      requirements: [],
    },
  };
}

const proposalsState = {
  entries: [] as ReturnType<typeof entry>[],
  adding: false,
  addToJob: (...a: unknown[]) => addToJob(...a),
  undoAdd: (...a: unknown[]) => undoAdd(...a),
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
  proposalsBulkApi: {
    add: (...a: unknown[]) => bulkAdd(...a),
    addInChunks: (...a: unknown[]) => bulkAdd(...a),
  },
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
      hiddenByCritical: (...a: unknown[]) => hiddenApi(...a),
    },
  };
});
vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: () => Promise.resolve({ all_of: [] }) },
  requirementLabels: () => [],
}));
vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
  api: { get: (...a: unknown[]) => apiGet(...a), put: (...a: unknown[]) => apiPut(...a) },
  championApi: { get: (...a: unknown[]) => championGet(...a) },
  candidatesApi: { removeFromRecruitment: (...a: unknown[]) => removeFromRecruitment(...a) },
}));
vi.mock("@/components/v2/recruitment/ManualSearchPanel", () => ({
  ManualSearchPanel: (props: Record<string, unknown>) => {
    manualPanel(props);
    return <div data-testid="manual-search-panel" />;
  },
}));
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
    talkChecks?: ReadonlyArray<{ label: string }>;
  }) => (
    <div data-testid="person-preview">
      <span data-testid="preview-name">{props.name}</span>
      <span data-testid="preview-source">{props.source?.line}</span>
      <span data-testid="preview-position">
        {props.position.index + 1} z {props.position.total}
      </span>
      {props.extra ? <span data-testid="preview-extra">{props.extra.title}</span> : null}
      <span data-testid="preview-talk">{(props.talkChecks ?? []).map((c) => c.label).join(" | ")}</span>
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

/** Odpowiedź `…/hidden-by-critical` (fikcyjne osoby, krytyczna „SailPoint IIQ”). */
function hiddenPayload(
  ids: number[],
  { canAddVariant = true, inRow = false }: { canAddVariant?: boolean; inRow?: boolean } = {},
) {
  return {
    job_id: 5,
    run_id: ids.length ? "run-1" : null,
    total: ids.length,
    truncated: false,
    can_add_variant: canAddVariant,
    searched: ids.length ? [{ critical: "sailpoint iiq", row: "SailPoint IIQ", words: ["sailpoint"] }] : [],
    variants: ids.length
      ? [{ critical: "sailpoint iiq", row: "SailPoint IIQ", word: "SailPoint", people: ids.length, in_row: inRow }]
      : [],
    items: ids.map((id) => ({
      candidate: {
        id,
        name: "Ukryta",
        lastname: `Osoba ${id}`,
        title: "IAM Engineer",
        city: "Łódź",
        availability_status: null,
        availability_date: null,
        expected_rate_hourly: null,
        expected_rate_redacted: false,
      },
      critical: "sailpoint iiq",
      row: "SailPoint IIQ",
      word: "Sailpoint",
      snippet: "…applications to Sailpoint IdentityIQ…",
      source: "cv",
      eligibility: null,
    })),
  };
}

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
    tab: "base" as CandidateWindowTab,
    onTabChange: vi.fn(),
    budgetHourly: 160,
    pipelineCandidateIds: [99],
    onManualAdded: vi.fn(),
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
    // D1 (14.10.2026): wynik liczy się sam dla widocznych wierszy — każdy test
    // z wierszami pyta o dopasowanie, więc atrapa zawsze odpowiada obietnicą.
    matchScores.mockResolvedValue({ scores: {}, breakdowns: {}, profile_key: "p:1" });
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
    hiddenApi.mockResolvedValue(hiddenPayload([]));
    listPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  });

  it("zamknięte okno nie montuje treści ani zapytań", () => {
    renderPanel({ open: false });
    expect(screen.queryByTestId("add-candidates-panel")).toBeNull();
    expect(countsApi).not.toHaveBeenCalled();
  });

  it("zakładki źródeł z liczbami (ręczne szukanie bez liczby); klik zmienia zakładkę przez stronę", async () => {
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
      "Szukaj ręcznie· —",
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

  it("propozycja ze stawką: plakietka względem budżetu zamiast „Ponad budżet” i gołej kwoty (D3)", async () => {
    const withRate = (id: number, name: string, rateHourly: number, warnings: string[] = []) => {
      const e = entry(id, name, ["inbox"], { warnings, rateLabel: `${rateHourly} zł/h` });
      return { ...e, detail: { ...e.detail, rateHourly } };
    };
    proposalsState.entries = [
      withRate(1, "Anna Wbudżecie", 160),
      withRate(2, "Piotr Ponad", 184, ["over_budget"]),
      withRate(3, "Ola Daleko", 200, ["over_budget"]),
    ] as never;
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    const item = (name: string) => within(list).getByText(name).closest("li") as HTMLElement;
    const rate = (name: string) => within(item(name)).getByTestId("pick-row-rate");
    expect(rate("Anna Wbudżecie")).toHaveTextContent("w budżecie · 160 zł/h");
    expect(rate("Anna Wbudżecie")).toHaveAttribute("data-tone", "rate-in");
    expect(rate("Piotr Ponad")).toHaveTextContent("+15% ponad budżet · 184 zł/h");
    expect(rate("Piotr Ponad")).toHaveAttribute("data-tone", "rate-over");
    expect(rate("Ola Daleko")).toHaveTextContent("+25% ponad budżet · 200 zł/h");
    expect(rate("Ola Daleko")).toHaveAttribute("data-tone", "rate-far");
    // Kwota raz — w plakietce; bez drugiej plakietki „Oczekuje +…% ponad budżet”.
    expect(within(list).queryByText(/Oczekuje/)).toBeNull();
    expect(within(list).queryByText("Ponad budżet")).toBeNull();
    expect(within(item("Piotr Ponad")).queryByText(/184 zł\/h · /)).toBeNull();
    expect(within(item("Piotr Ponad")).getByText("od zaraz")).toBeTruthy();
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
    expect(addToJob).toHaveBeenCalledWith([1], { unlistedSource: "proposal_inbox" }, expect.anything());
    expect(bulkAdd).not.toHaveBeenCalled();
  });

  it("każda zakładka ma swoje zaznaczenie — „Dodaj N” nie bierze osób z niewidocznej (U7)", async () => {
    proposalsState.entries = [
      entry(1, "Anna Baza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Piotr Ogłoszenie", ["inbox"], { sources: ["job_board"], postingRecent: true }),
    ];
    const { rerender } = renderPanel();
    const base = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await userEvent.click(within(base).getByRole("checkbox", { name: "Zaznacz Anna Baza" }));
    expect(screen.getByTestId("add-candidates-submit")).toHaveTextContent("Dodaj 1 do Nowych");

    rerender({ tab: "postings" });
    const postings = await screen.findByRole("list", { name: "Nowi z ogłoszeń" });
    expect(screen.getByTestId("add-candidates-submit")).toHaveTextContent("Dodaj 0 do Nowych");
    await userEvent.click(within(postings).getByRole("checkbox", { name: "Zaznacz Piotr Ogłoszenie" }));
    await userEvent.click(screen.getByTestId("add-candidates-submit"));
    expect(addToJob).toHaveBeenCalledWith([2], { unlistedSource: "proposal_inbox" }, expect.anything());

    // Zaznaczenie z drugiej zakładki czeka tam, gdzie je zostawiono.
    rerender({ tab: "base" });
    expect(screen.getByTestId("add-candidates-submit")).toHaveTextContent("Dodaj 1 do Nowych");
  });

  it("strzałki przechodzą między zakładkami źródeł (U7)", async () => {
    const { props } = renderPanel();
    const current = await screen.findByRole("tab", { name: /Propozycje z bazy/ });
    current.focus();
    fireEvent.keyDown(current, { key: "ArrowRight" });
    expect(props.onTabChange).toHaveBeenCalledWith("search");
    fireEvent.keyDown(current, { key: "ArrowLeft" });
    expect(props.onTabChange).toHaveBeenCalledWith("postings");
    expect(current).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: /Nowi z ogłoszeń/ })).toHaveAttribute("tabindex", "-1");
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
          requirements: [],
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

  it("„Pomiń zaznaczone (N)”: jeden powód dla wszystkich, zaznaczenie znika", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Bartek Drugi", ["inbox"], { sources: ["full_base"] }),
      entry(3, "Celina Trzecia", ["inbox"], { sources: ["full_base"] }),
    ];
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    const skip = screen.getByTestId("add-candidates-dismiss");
    expect(skip).toBeDisabled();
    expect(skip).toHaveTextContent("Pomiń zaznaczone (0)");

    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Anna Pierwsza" }));
    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Celina Trzecia" }));
    expect(skip).toHaveTextContent("Pomiń zaznaczone (2)");
    await userEvent.click(skip);
    const dialog = await screen.findByRole("dialog", { name: "Pomiń 2 osoby — dlaczego?" });
    await userEvent.click(within(dialog).getByLabelText("Nieaktualne CV"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(dismiss).toHaveBeenCalledWith([1, 3], { reason: "outdated_cv" });
    expect(within(list).getByRole("checkbox", { name: "Zaznacz Anna Pierwsza" })).not.toBeChecked();
    expect(screen.getByTestId("add-candidates-submit")).toHaveTextContent("Dodaj 0 do Nowych");
  });

  it("anulowane okno powodu nie pomija nikogo i nie zdejmuje zaznaczenia", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] }),
      entry(2, "Bartek Drugi", ["inbox"], { sources: ["full_base"] }),
    ];
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Anna Pierwsza" }));
    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Bartek Drugi" }));
    await userEvent.click(screen.getByTestId("add-candidates-dismiss"));
    const dialog = await screen.findByRole("dialog", { name: "Pomiń 2 osoby — dlaczego?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(dismiss).not.toHaveBeenCalled();
    expect(within(list).getByRole("checkbox", { name: "Zaznacz Bartek Drugi" })).toBeChecked();
  });

  it("bez prawa zapisu okno jest do odczytu: bez dodawania i bez „Pomiń”", async () => {
    proposalsState.entries = [entry(1, "Anna Pierwsza", ["inbox"])];
    renderPanel({ readOnly: true });
    await screen.findByRole("list", { name: "Propozycje z bazy" });
    expect(screen.queryByTestId("add-candidates-submit")).toBeNull();
    expect(screen.queryByRole("button", { name: /Pomiń:/ })).toBeNull();
    expect(screen.queryByTestId("add-candidates-dismiss")).toBeNull();
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
    // D3 (19.10.2026): stawka nie stoi w linii faktów — jest plakietką względem budżetu (160).
    await within(list).findByText("Java Developer @ Firma · 8 lat dośw. · Gdańsk · tylko zdalnie");
    expect(within(list).getByText("Tester · 3 lata dośw. · Łódź")).toBeTruthy();
    const bartek = within(list).getByText("Bartek Drugi").closest("li") as HTMLElement;
    expect(within(bartek).getByTestId("pick-row-rate")).toHaveTextContent("+6% ponad budżet · 170 zł/h");
    const anna = within(list).getByText("Anna Pierwsza").closest("li") as HTMLElement;
    expect(within(anna).queryByTestId("pick-row-rate")).toBeNull();
    expect(
      within(list).getByText("Był(a) u tego klienta: Senior Java — doszedł(a) do etapu „CV Wysłane” (odrzucony/a)"),
    ).toBeTruthy();
    const cvBadges = within(list).getAllByTestId("cv-year-badge");
    expect(cvBadges).toHaveLength(1);
    expect(cvBadges[0]).toHaveTextContent("CV z 2019");
    // Domyślnie „Dopasowanie” (19.10.2026) — bez wyników zostaje kolejność wejścia;
    // „Najpierw byli u tego klienta” wynosi osobę z historią u klienta.
    const names = () => within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(screen.getByRole("button", { name: "Dopasowanie" })).toHaveAttribute("aria-pressed", "true");
    expect(names()).toEqual(["Zaznacz Anna Pierwsza", "Zaznacz Bartek Drugi"]);
    await userEvent.click(screen.getByRole("button", { name: "Najpierw byli u tego klienta" }));
    expect(names()).toEqual(["Zaznacz Bartek Drugi", "Zaznacz Anna Pierwsza"]);
    expect(factsApi).toHaveBeenCalledWith(5, [1, 2], expect.anything());
  });

  it("dopasowanie liczy się samo dla wierszy na ekranie — bez przycisku (D1); niezmierzony = „Ocena niepełna”", async () => {
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
    expect(screen.queryByRole("button", { name: /Policz dopasowanie/ })).toBeNull();
    await within(list).findByText("71%");
    expect(within(list).getByText("Ocena niepełna")).toBeTruthy();
    expect(within(list).getByText("64%")).toBeTruthy();
    expect(within(list).queryByText("nie policzono")).toBeNull();
    // Jedno zapytanie (paczka do 20) i tylko o osoby bez wyniku.
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect([...matchScores.mock.calls[0][1]].sort()).toEqual([1, 2]);
  });

  it("domyślnie „Dopasowanie”: najwyższy % na górze, także policzony na ekranie; bez wyniku na końcu (19.10.2026)", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["inbox"], { fitScore: 70 }),
      entry(2, "Bartek Drugi", ["similar"], { fitScore: null }),
      entry(3, "Cezary Trzeci", ["inbox"], { fitScore: 81 }),
      entry(4, "Dorota Czwarta", ["similar"], { fitScore: null }),
    ];
    matchScores.mockResolvedValue({
      scores: { "2": 88 },
      breakdowns: { "4": { total: null, measurement: "missing_index" } },
      profile_key: "p:1",
    });
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await within(list).findByText("88%");
    const names = within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual([
      "Zaznacz Bartek Drugi",
      "Zaznacz Cezary Trzeci",
      "Zaznacz Anna Pierwsza",
      "Zaznacz Dorota Czwarta",
    ]);
  });

  it("inna rola niż rekrutacja: plakietka, przekreślony % i miejsce pod osobami z tej roli; „musi mieć X/Y” przy procencie (27.10.2026)", async () => {
    const withMust = (e: ReturnType<typeof entry>, met: number, total: number) =>
      ({
        ...e,
        detail: {
          ...e.detail,
          requirements: Array.from({ length: total }, (_, i) => ({
            label: `Skill ${i}`,
            level: "must",
            status: i < met ? "met" : "unknown",
            verified: false,
          })),
        },
      }) as never;
    proposalsState.entries = [
      withMust(entry(1, "Mateusz Tester", ["inbox"], { fitScore: 77 }), 5, 10),
      withMust(entry(2, "Paweł Programista", ["inbox"], { fitScore: 72 }), 9, 10),
    ];
    factsApi.mockResolvedValue({
      job_id: 5,
      items: [
        {
          candidate_id: 1, title: "Senior QA Automation Engineer", company: null, years_experience: 7, city: null,
          max_onsite_days_per_week: null, remote_modes: [], availability_status: null, availability_date: null,
          expected_rate_hourly: null, expected_rate_currency: null, expected_rate_redacted: false, client_history: null,
          role_mismatch: { family: "qa", label: "tester", detail: "obecnie Senior QA Automation Engineer" },
        },
        {
          candidate_id: 2, title: "Java Developer", company: null, years_experience: 7, city: null,
          max_onsite_days_per_week: null, remote_modes: [], availability_status: null, availability_date: null,
          expected_rate_hourly: null, expected_rate_currency: null, expected_rate_redacted: false, client_history: null,
          role_mismatch: null,
        },
      ],
    });
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    await within(list).findByText("Inna rola: tester");
    const names = within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual(["Zaznacz Paweł Programista", "Zaznacz Mateusz Tester"]);
    const tester = within(list).getByText("Mateusz Tester").closest("li") as HTMLElement;
    expect(within(tester).getByText("obecnie Senior QA Automation Engineer")).toBeTruthy();
    expect(within(tester).getByTestId("pick-row-score-off-role")).toHaveTextContent("77% (inna rola)");
    expect(within(tester).getByTestId("pick-row-must-coverage")).toHaveTextContent("musi mieć 5/10");
    const developer = within(list).getByText("Paweł Programista").closest("li") as HTMLElement;
    expect(within(developer).queryByTestId("pick-row-role-mismatch")).toBeNull();
    expect(within(developer).getByText("72%")).toBeTruthy();
    expect(within(developer).getByTestId("pick-row-must-coverage")).toHaveTextContent("musi mieć 9/10");
  });

  it("osoba tylko z portalu ogłoszeń: procent NEXUSA z `/scores`, wynik scrapera w dymku; kolejność po procencie NEXUSA (27.10.2026)", async () => {
    proposalsState.entries = [
      // Scraper dał 77%, NEXUS po przeliczeniu 64% — na liście ma być 64%.
      entry(1, "Mateusz Tester", ["inbox"], {
        fitScore: null, boardScore: 77, sources: ["job_board"], postingRecent: true,
      }),
      entry(2, "Paweł Programista", ["inbox"], {
        fitScore: 72, boardScore: 70, sources: ["full_base", "job_board"], postingRecent: true,
      }),
      entry(3, "Celina Nowa", ["inbox"], { fitScore: 68, sources: ["new_cv"], postingRecent: true }),
    ];
    matchScores.mockResolvedValue({ scores: { "1": 64 }, breakdowns: {}, profile_key: "p:1" });
    renderPanel({ tab: "postings" });
    const list = await screen.findByRole("list", { name: "Nowi z ogłoszeń" });
    // Liczymy tylko osobę bez kanonicznego wyniku.
    await waitFor(() => expect(matchScores).toHaveBeenCalled());
    expect([...matchScores.mock.calls[0][1]]).toEqual([1]);
    const tester = within(list).getByText("Mateusz Tester").closest("li") as HTMLElement;
    const shown = await within(tester).findByText("64%");
    expect(within(tester).queryByText("77%")).toBeNull();
    expect(shown.getAttribute("title")).toContain("portal ogłoszeń ocenił na 77%");
    const developer = within(list).getByText("Paweł Programista").closest("li") as HTMLElement;
    expect(within(developer).getByText("72%").getAttribute("title")).toContain("ocenił na 70%");
    const names = within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual([
      "Zaznacz Paweł Programista",
      "Zaznacz Celina Nowa",
      "Zaznacz Mateusz Tester",
    ]);
  });

  it("inna rola przy osobie tylko z portalu: przekreślony procent NEXUSA, nie „—” ani wynik scrapera", async () => {
    proposalsState.entries = [
      entry(1, "Mateusz Tester", ["inbox"], {
        fitScore: null, boardScore: 77, sources: ["job_board"], postingRecent: true,
      }),
    ];
    matchScores.mockResolvedValue({ scores: { "1": 64 }, breakdowns: {}, profile_key: "p:1" });
    factsApi.mockResolvedValue({
      job_id: 5,
      items: [
        {
          candidate_id: 1, title: "Senior QA Automation Engineer", company: null, years_experience: 7, city: null,
          max_onsite_days_per_week: null, remote_modes: [], availability_status: null, availability_date: null,
          expected_rate_hourly: null, expected_rate_currency: null, expected_rate_redacted: false, client_history: null,
          role_mismatch: { family: "qa", label: "tester", detail: "obecnie Senior QA Automation Engineer" },
        },
      ],
    });
    renderPanel({ tab: "postings" });
    const list = await screen.findByRole("list", { name: "Nowi z ogłoszeń" });
    await within(list).findByText("Inna rola: tester");
    await waitFor(() =>
      expect(within(list).getByTestId("pick-row-score-off-role")).toHaveTextContent("64% (inna rola)"),
    );
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
    const retry = await screen.findByRole("button", { name: "nie policzono — ponów" });
    expect(screen.queryByText("0%")).toBeNull();
    matchScores.mockResolvedValueOnce({ scores: { "1": 55 }, breakdowns: {}, profile_key: "p:1" });
    await userEvent.click(retry);
    await screen.findByText("55%");
  });

  describe("„+ Dodaj” w wierszu i „Cofnij” (P1, 14.10.2026)", () => {
    const succeed = (added: number[]) =>
      addToJob.mockImplementation(
        (_ids: number[], _opts: unknown, callbacks?: { onSuccess?: (r: unknown) => void; onSettled?: () => void }) => {
          // Hook chowa dodanych w źródłach — tu: znikają z `entries`.
          proposalsState.entries = proposalsState.entries.filter((e) => !added.includes(e.row.candidateId));
          callbacks?.onSuccess?.({ added, skipped: [], warnings: [], total_added: added.length, total_skipped: 0 });
          callbacks?.onSettled?.();
        },
      );

    it("jedno kliknięcie dodaje osobę; wiersz zostaje z „Dodano do „Nowych” · rezerwacja 12 h · Cofnij”", async () => {
      proposalsState.entries = [
        entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] }),
        entry(2, "Bartek Drugi", ["inbox"], { sources: ["full_base"] }),
      ];
      succeed([1]);
      const { rerender } = renderPanel();
      const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
      await userEvent.click(within(list).getByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" }));
      expect(addToJob).toHaveBeenCalledWith([1], { unlistedSource: "proposal_inbox" }, expect.anything());
      rerender();

      const row = within(screen.getByRole("list", { name: "Propozycje z bazy" }))
        .getByText("Anna Pierwsza")
        .closest("li") as HTMLElement;
      expect(within(row).getByTestId("pick-row-added")).toHaveTextContent("Dodano do „Nowych” · rezerwacja 12 h");
      expect(within(row).getByRole("checkbox")).toBeDisabled();
      expect(within(row).queryByRole("button", { name: /Dodaj do „Nowych”/ })).toBeNull();
      expect(within(row).queryByRole("button", { name: /Pomiń:/ })).toBeNull();
      // Kolejność się nie zmienia — dodana osoba stoi tam, gdzie stała.
      const names = within(screen.getByRole("list", { name: "Propozycje z bazy" }))
        .getAllByRole("checkbox")
        .map((c) => c.getAttribute("aria-label"));
      expect(names).toEqual(["Zaznacz Anna Pierwsza", "Zaznacz Bartek Drugi"]);
    });

    it("„Cofnij” usuwa osobę z rekrutacji i wiersz wraca do zwykłego stanu", async () => {
      const anna = entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] });
      proposalsState.entries = [anna];
      succeed([1]);
      undoAdd.mockImplementation(async () => {
        // Serwer oddał propozycję — źródła znów zwracają osobę.
        proposalsState.entries = [anna];
        return true;
      });
      const { rerender } = renderPanel();
      const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
      await userEvent.click(within(list).getByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" }));
      rerender();
      await userEvent.click(screen.getByRole("button", { name: "Cofnij dodanie: Anna Pierwsza" }));
      expect(undoAdd).toHaveBeenCalledWith(1);
      await waitFor(() => expect(screen.queryByTestId("pick-row-added")).toBeNull());
      const row = within(screen.getByRole("list", { name: "Propozycje z bazy" }))
        .getByText("Anna Pierwsza")
        .closest("li") as HTMLElement;
      expect(within(row).getByRole("checkbox")).toBeEnabled();
      expect(within(row).getByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" })).toBeTruthy();
    });

    it("nieudane „Cofnij” zostawia wiersz jako dodany", async () => {
      proposalsState.entries = [entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] })];
      succeed([1]);
      undoAdd.mockResolvedValue(false);
      const { rerender } = renderPanel();
      await userEvent.click(
        await screen.findByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" }),
      );
      rerender();
      await userEvent.click(screen.getByRole("button", { name: "Cofnij dodanie: Anna Pierwsza" }));
      await waitFor(() => expect(undoAdd).toHaveBeenCalled());
      expect(screen.getByTestId("pick-row-added")).toBeTruthy();
    });

    it("odmowa serwera (np. zamknięta karta) nie udaje dodania — wiersz zostaje zwykły", async () => {
      proposalsState.entries = [entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"] })];
      addToJob.mockImplementation(
        (_ids: number[], _opts: unknown, callbacks?: { onSuccess?: (r: unknown) => void }) =>
          callbacks?.onSuccess?.({
            added: [],
            skipped: [{ candidate_id: 1, reason: "closed_in_job" }],
            warnings: [],
            total_added: 0,
            total_skipped: 1,
          }),
      );
      renderPanel();
      await userEvent.click(
        await screen.findByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" }),
      );
      expect(screen.queryByTestId("pick-row-added")).toBeNull();
      expect(screen.getByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" })).toBeTruthy();
    });

    it("weto HM blokuje też „+ Dodaj”; do odczytu nie ma przycisku", async () => {
      const jan = entry(4, "Jan Weto", ["inbox"]);
      proposalsState.entries = [
        entry(1, "Anna Pierwsza", ["inbox"]),
        {
          ...jan,
          detail: {
            ...jan.detail,
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
      const { rerender } = renderPanel({ readOnly: true });
      await screen.findByRole("list", { name: "Propozycje z bazy" });
      expect(screen.queryByRole("button", { name: /Dodaj do „Nowych”/ })).toBeNull();
      rerender({ readOnly: false });
      expect(screen.getByRole("button", { name: "Dodaj do „Nowych”: Anna Pierwsza" })).toBeEnabled();
      const veto = screen.getByRole("button", { name: "Dodaj do „Nowych”: Jan Weto" });
      expect(veto).toBeDisabled();
      expect(veto).toHaveAttribute("title", "Weto HM: Brak bankowości");
    });
  });

  it("powód w wierszu: do trzech chipów z wymagań propozycji i „zapytaj” z must-have zdaniem", async () => {
    countsApi.mockResolvedValue({
      job_id: 5, days: 7, postings_recent: 0, base: 1, screened_out: 0,
      not_searchable_must: ["5 lat w bankowości"],
    });
    const anna = entry(1, "Anna Pierwsza", ["inbox"], { sources: ["full_base"], reason: "Spełnia: Java" });
    proposalsState.entries = [
      {
        ...anna,
        detail: {
          ...anna.detail,
          requirements: [
            { label: "Java", level: "must", status: "met", verified: false },
            { label: "Kafka", level: "must", status: "not_met", verified: false },
            { label: "Spring", level: "must", status: "met", verified: false },
          ],
        },
      } as never,
    ];
    renderPanel();
    const list = await screen.findByRole("list", { name: "Propozycje z bazy" });
    // Jednolinijkowy powód zostaje.
    expect(within(list).getByText("Spełnia: Java")).toBeTruthy();
    const chips = await within(list).findByRole("group", { name: "Dlaczego ta osoba" });
    await waitFor(() =>
      expect([...chips.children].map((c) => [c.getAttribute("data-tone"), c.textContent])).toEqual([
        ["met", "✓Spełnia: Java"],
        ["gap", "✕Brakuje: Kafka"],
        ["ask", "?Nie wiemy — zapytaj w rozmowie: 5 lat w bankowości"],
        ["more", "+1I jeszcze: Spełnia: Spring"],
      ]),
    );
  });

  describe("„Szukaj ręcznie” jako zakładka okna (14.10.2026)", () => {
    it("zakładka montuje wyszukiwarkę w szerokim oknie, bez podglądu osoby i bez stopki", async () => {
      renderPanel({ tab: "manual" });
      const panel = await screen.findByTestId("add-candidates-panel");
      expect(panel.className).toContain("sm:max-w-[min(1100px,92vw)]");
      expect(screen.getByTestId("manual-search-panel")).toBeTruthy();
      expect(manualPanel).toHaveBeenLastCalledWith(
        expect.objectContaining({ jobId: 5, job: JOB, readOnly: false }),
      );
      expect(screen.getByText(/Filtry wypełnione z rekrutacji „Analityk KYC”/)).toBeTruthy();
      expect(screen.queryByTestId("add-candidates-submit")).toBeNull();
    });

    it("przełączanie zakładek nie odmontowuje wyszukiwarki (filtry i zaznaczenia zostają)", async () => {
      const { rerender } = renderPanel({ tab: "manual" });
      await screen.findByTestId("manual-search-panel");
      const mounts = manualPanel.mock.calls.length;
      rerender({ tab: "base" });
      const hidden = screen.getByTestId("manual-search-tab");
      expect(hidden).not.toBeVisible();
      expect((await screen.findByTestId("add-candidates-panel")).className).toContain("sm:max-w-[540px]");
      rerender({ tab: "manual" });
      expect(screen.getByTestId("manual-search-tab")).toBeVisible();
      // Ten sam egzemplarz — nowe rendery, nie nowy montaż z czystym stanem.
      expect(manualPanel.mock.calls.length).toBeGreaterThanOrEqual(mounts);
      expect(screen.getAllByTestId("manual-search-panel")).toHaveLength(1);
    });

    it("strzałka w prawo z „Szukaj w bazie” prowadzi do „Szukaj ręcznie”", async () => {
      const { props } = renderPanel({ tab: "search" });
      const current = await screen.findByRole("tab", { name: /Szukaj w bazie/ });
      fireEvent.keyDown(current, { key: "ArrowRight" });
      expect(props.onTabChange).toHaveBeenCalledWith("manual");
    });
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
          // Krytyczne liczy serwer (06.10.2026) — klasyfikacja wierszy nie
          // decyduje już o obowiązkowości.
          critical_resolution: {
            stored: ["KYC"],
            decided: true,
            effective: ["KYC"],
            source: "dl",
            suggested: [],
            search_rows: [["KYC"]],
          },
        },
      });
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
            years_it_experience: 8, city: "Warszawa", expected_rate_hourly: 140, expected_rate_currency: "PLN",
            // „Stawka od” — tę czyta plakietka (filtr i bramka też), nie stawkę profilu.
            rate_from_hourly: "90.00",
            match_snippets: [{ field: "Treść CV", text: "projekt KYC dla banku", highlights: [[8, 11]] }],
          },
        ],
        total: 86, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: { "31": 84 }, breakdowns: {} });
      renderPanel({ tab: "search" });

      const words = await screen.findByRole("list", { name: "Wymagania do wyszukiwania" }, SLOW);
      expect(screen.getByTestId("search-base-source")).toHaveTextContent(
        "wybrane przez Delivery Leada: KYC",
      );
      // Wariant A: każda linia mówi, co robi z listą.
      const lineOf = (label: string) => within(words).getByText(label).closest("li") as HTMLElement;
      const required = lineOf("Wymagane (krytyczne)");
      expect(required).toHaveTextContent("bez tego słowa osoba nie pojawi się na liście");
      expect(within(required).getByText("KYC")).toBeTruthy();
      expect(within(required).getByText("AML")).toBeTruthy();
      const must = lineOf("Musi mieć (Delivery Lead)");
      expect(must).toHaveTextContent("podnosi w kolejności, nie wycina");
      expect(within(must).getByText("bankow*")).toBeTruthy();
      expect(within(words).queryByText("Mile widziane")).toBeNull();
      expect(within(lineOf("Wyklucz")).getByText("junior")).toBeTruthy();
      // Rekrutacja zdalna — bez linii lokalizacji.
      expect(within(words).queryByText("Lokalizacja kandydata")).toBeNull();
      // Starszy serwer bez `talk_checks`: w rozmowie zostają must-have zdaniem.
      const talk = lineOf("Rekruter sprawdza w rozmowie");
      expect(talk).toHaveTextContent("tego nie szukamy — zapytaj w rozmowie");
      expect(within(talk).getByText("Minimum 5 lat doświadczenia w analizie biznesowej")).toBeTruthy();
      expect(screen.queryByText(/Po tym nie szukamy/)).toBeNull();

      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      expect(within(results).getByText("Marta Wilczek")).toBeTruthy();
      expect(within(results).getByText("Analityk KYC · 8 lat dośw. · Warszawa")).toBeTruthy();
      expect(within(results).getByTestId("pick-row-rate")).toHaveTextContent("w budżecie · 90 zł/h");
      expect(within(results).getByText("KYC", { selector: "strong" })).toBeTruthy();
      await within(results).findByText("84%");
      expect(screen.getByTestId("search-base-summary")).toHaveTextContent("Znaleziono osób: 86");
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

    it("linie „Mile widziane”, „Lokalizacja kandydata” i rozmowa z `talk_checks`; filtry zapytania bez zmian", async () => {
      championGet.mockResolvedValue({
        data: {
          champion_profile: {
            search: { requirements: [["KYC"]] },
            stack: { rows: [{ words: ["Scala"], level: "nice" }] },
          },
          critical_resolution: {
            stored: [],
            decided: true,
            effective: [],
            source: "dl",
            suggested: [],
            search_rows: [],
          },
        },
      });
      countsApi.mockResolvedValue({
        job_id: 5, days: 7, postings_recent: 0, base: 0, screened_out: 0,
        not_searchable_must: [],
        talk_checks: [
          { label: "bankowość", kind: "domains" },
          { label: "angielski B2", kind: "language" },
        ],
      });
      listPage.mockResolvedValue({
        items: [{ id: 41, name: "Ola", lastname: "Przykładowa", match_snippets: [] }],
        total: 1, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
      renderPanel({ tab: "search", job: { ...JOB, remote_policy: "hybrid", location: "Warszawa" } });

      const words = await screen.findByRole("list", { name: "Wymagania do wyszukiwania" }, SLOW);
      const lineOf = (label: string) => within(words).getByText(label).closest("li") as HTMLElement;
      expect(within(words).queryByText("Wymagane (krytyczne)")).toBeNull();
      expect(within(lineOf("Musi mieć (Delivery Lead)")).getByText("KYC")).toBeTruthy();
      expect(within(lineOf("Mile widziane")).getByText("Scala")).toBeTruthy();
      expect(within(lineOf("Mile widziane")).queryByText("KYC")).toBeNull();
      const place = lineOf("Lokalizacja kandydata");
      expect(place).toHaveTextContent("miasto w profilu kandydata, nie słowo w CV · podnosi w kolejności");
      expect(within(place).getByText("📍 Warszawa")).toBeTruthy();
      const talk = await waitFor(() => lineOf("Rekruter sprawdza w rozmowie"));
      expect(
        within(within(talk).getByRole("list", { name: "Rekruter sprawdza w rozmowie" }))
          .getAllByRole("listitem")
          .map((li) => li.textContent),
      ).toEqual(["bankowość", "Język: angielski B2"]);

      // Linie są opisem — zapytanie zostaje takie jak dotąd.
      await waitFor(() => expect(listPage).toHaveBeenCalled(), SLOW);
      const params = listPage.mock.calls[0][0] as Record<string, unknown>;
      expect(params.q_any_group ?? []).toEqual([]);
      expect(params.q_preferred_group).toEqual(["KYC", "Scala"]);

      // Podgląd osoby niesie tę samą listę do rozmowy.
      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      await userEvent.click(within(results).getByRole("button", { name: "Ola Przykładowa" }));
      expect(await screen.findByTestId("preview-talk")).toHaveTextContent("bankowość | angielski B2");
    });

    it("awaria odczytu listy do rozmowy to komunikat, nie brak linii", async () => {
      withRows();
      countsApi.mockRejectedValue({ response: { status: 500, data: {} } });
      renderPanel({ tab: "search" });
      const words = await screen.findByRole("list", { name: "Wymagania do wyszukiwania" }, SLOW);
      const alert = await within(words).findByRole("alert", undefined, SLOW);
      expect(alert).toHaveTextContent("Nie wczytano listy do rozmowy");
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
      // Dodana osoba zostaje na liście z „Cofnij” i nie da się jej zaznaczyć drugi raz.
      const row = within(results).getByText("Hanna Pietrzyk").closest("li") as HTMLElement;
      expect(within(row).getByTestId("pick-row-added")).toHaveTextContent("Dodano do „Nowych” · rezerwacja 12 h");
      expect(within(results).getByRole("checkbox", { name: "Zaznacz Hanna Pietrzyk" })).toBeDisabled();
      expect(screen.getByTestId("search-base-submit")).toHaveTextContent("Dodaj 0 do Nowych");
    });

    it("„+ Dodaj” w wierszu: jedna osoba, ta sama droga; po odświeżeniu wiersz zostaje; „Cofnij” go oddaje", async () => {
      withRows();
      const marta = { id: 31, name: "Marta", lastname: "Wilczek", match_snippets: [] };
      const hanna = { id: 32, name: "Hanna", lastname: "Pietrzyk", match_snippets: [] };
      listPage.mockResolvedValue({ items: [marta, hanna], total: 2, page: 1, page_size: 20 });
      matchScores.mockResolvedValue({
        scores: { "31": 84 },
        breakdowns: { "31": { total: 84, measurement: "measured", matching_must: ["KYC"], gap_must: ["AML"] } },
      });
      bulkAdd.mockResolvedValue({ added: [31], skipped: [], warnings: [], total_added: 1, total_skipped: 0 });
      renderPanel({ tab: "search" });
      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      // Chipy powodu z rozbicia dopasowania.
      const reasons = await within(results).findByRole("group", { name: "Dlaczego ta osoba" });
      expect(reasons).toHaveTextContent("KYC");
      expect(reasons).toHaveTextContent("AML");

      // Odświeżenie wyników już Marty nie zwraca (jest w rekrutacji).
      listPage.mockResolvedValue({ items: [hanna], total: 1, page: 1, page_size: 20 });
      await userEvent.click(within(results).getByRole("button", { name: "Dodaj do „Nowych”: Marta Wilczek" }));
      await waitFor(() =>
        expect(bulkAdd).toHaveBeenCalledWith(5, {
          candidate_ids: [31],
          initial_stage_legacy: "new",
          source: "manual_search",
        }),
      );
      await waitFor(() => expect(listPage).toHaveBeenCalledTimes(2));
      const row = (await screen.findByTestId("pick-row-added")).closest("li") as HTMLElement;
      expect(row).toHaveTextContent("Marta Wilczek");
      expect(row).toHaveTextContent("84%");

      // „Cofnij” = usunięcie z rekrutacji; osoba wraca do wyników jako zwykły wiersz.
      removeFromRecruitment.mockResolvedValue({ data: {} });
      listPage.mockResolvedValue({ items: [marta, hanna], total: 2, page: 1, page_size: 20 });
      await userEvent.click(within(row).getByRole("button", { name: "Cofnij dodanie: Marta Wilczek" }));
      expect(removeFromRecruitment).toHaveBeenCalledWith(31, 5, { quickUndo: true });
      await waitFor(() => expect(screen.queryByTestId("pick-row-added")).toBeNull());
      expect(
        within(screen.getByRole("list", { name: "Wyniki wyszukiwania" })).getByRole("button", {
          name: "Dodaj do „Nowych”: Marta Wilczek",
        }),
      ).toBeTruthy();
    });

    it("nieudane „Cofnij” w wyszukiwaniu mówi dlaczego i zostawia wiersz dodany", async () => {
      withRows();
      listPage.mockResolvedValue({
        items: [{ id: 31, name: "Marta", lastname: "Wilczek", match_snippets: [] }],
        total: 1, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
      bulkAdd.mockResolvedValue({ added: [31], skipped: [], warnings: [], total_added: 1, total_skipped: 0 });
      removeFromRecruitment.mockRejectedValue({ response: { status: 409, data: { detail: "Blokada 12 h innej osoby." } } });
      renderPanel({ tab: "search" });
      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      await userEvent.click(within(results).getByRole("button", { name: "Dodaj do „Nowych”: Marta Wilczek" }));
      await userEvent.click(await screen.findByRole("button", { name: "Cofnij dodanie: Marta Wilczek" }));
      await waitFor(() => expect(showError).toHaveBeenCalledWith("Blokada 12 h innej osoby."));
      expect(screen.getByTestId("pick-row-added")).toBeTruthy();
    });

    it("„Zmień słowa i filtry” przełącza na zakładkę „Szukaj ręcznie” — okno zostaje otwarte", async () => {
      withRows();
      listPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
      const { props } = renderPanel({ tab: "search" });
      await userEvent.click(await screen.findByRole("button", { name: "Zmień słowa i filtry" }, SLOW));
      expect(props.onTabChange).toHaveBeenCalledWith("manual");
      expect(props.onOpenChange).not.toHaveBeenCalled();
    });

    it("osoba, która już jest w rekrutacji, schodzi z zaznaczenia (U4)", async () => {
      withRows();
      listPage.mockResolvedValue({
        items: [{ id: 33, name: "Jan", lastname: "Kos", match_snippets: [] }],
        total: 1, page: 1, page_size: 20,
      });
      matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
      bulkAdd.mockResolvedValue({
        added: [],
        skipped: [{ candidate_id: 33, reason: "already_in_job" }],
        warnings: [],
        total_added: 0,
        total_skipped: 1,
      });
      renderPanel({ tab: "search" });
      const results = await screen.findByRole("list", { name: "Wyniki wyszukiwania" }, SLOW);
      await userEvent.click(within(results).getByRole("checkbox", { name: "Zaznacz Jan Kos" }));
      await userEvent.click(screen.getByTestId("search-base-submit"));
      await waitFor(() =>
        expect(screen.getByTestId("search-base-submit")).toHaveTextContent("Dodaj 0 do Nowych"),
      );
    });

    it("profil bez wymagań do wyszukiwania, ale z krytyczną z serwera — szuka tak samo jak okno ręczne", async () => {
      // Przegląd PR #2056: zakładka i kafel liczyły „są wiersze” tylko
      // z `search.requirements`, okno ręczne — też z krytycznych.
      championGet.mockResolvedValue({
        data: {
          champion_profile: { stack: { must: [{ name: "Kafka" }] } },
          critical_resolution: {
            stored: ["Kafka"],
            decided: true,
            effective: ["Kafka"],
            source: "dl",
            suggested: [],
            search_rows: [["Kafka", "Apache Kafka"]],
          },
        },
      });
      listPage.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
      renderPanel({ tab: "search" });
      await waitFor(() => expect(listPage).toHaveBeenCalled(), SLOW);
      const params = listPage.mock.calls[0][0] as Record<string, unknown>;
      expect(params.q_any_group).toEqual(["Kafka|Apache Kafka"]);
      expect(screen.queryByTestId("search-base-empty")).toBeNull();
    });

    it("bez słów w Championie nie udaje wyników całej bazy — odsyła do Championa i ręcznego szukania", async () => {
      const { props } = renderPanel({ tab: "search" });
      const empty = await screen.findByTestId("search-base-empty", undefined, SLOW);
      expect(listPage).not.toHaveBeenCalled();
      await userEvent.click(within(empty).getByRole("button", { name: "Otwórz Championa" }));
      expect(props.onOpenChampionSearch).toHaveBeenCalled();
      await userEvent.click(within(empty).getByRole("button", { name: "Szukaj ręcznie" }));
      expect(props.onTabChange).toHaveBeenCalledWith("manual");
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

  describe("najlepsze 40 i ukryci przez „musi mieć” (28.10.2026)", () => {
    const below = (id: number, name: string, fitScore: number) => {
      const e = entry(id, name, ["inbox"], { sources: ["full_base"], fitScore });
      Object.assign(e.detail, { belowThreshold: true });
      return e;
    };

    it("osoby spod progu stoją pod separatorem „Poniżej 70%” i nie liczą się do zakładki", async () => {
      proposalsState.entries = [
        below(2, "Bartek Spod", 65),
        entry(1, "Anna Nad", ["inbox"], { sources: ["full_base"], fitScore: 81 }),
        below(3, "Celina Spod", 61),
      ];
      renderPanel();
      const above = await screen.findByRole("list", { name: "Propozycje z bazy" });
      expect(within(above).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"))).toEqual([
        "Zaznacz Anna Nad",
      ]);
      expect(screen.getByTestId("proposals-below-threshold")).toHaveTextContent("Poniżej 70% · 2 osób");
      const under = screen.getByRole("list", { name: "Propozycje z bazy poniżej 70%" });
      expect(within(under).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"))).toEqual([
        "Zaznacz Bartek Spod",
        "Zaznacz Celina Spod",
      ]);
      expect(screen.getByRole("tab", { name: /Propozycje z bazy/ })).toHaveTextContent("Propozycje z bazy· 1");
    });

    it("bez nikogo od progu lista mówi to wprost, a najlepsi spod progu dalej są", async () => {
      proposalsState.entries = [below(2, "Bartek Spod", 65)];
      renderPanel();
      await screen.findByRole("list", { name: "Propozycje z bazy poniżej 70%" });
      expect(screen.getByText("Nikt nie ma 70% lub więcej — poniżej najlepsi spod progu.")).toBeInTheDocument();
      expect(screen.queryByText("Nikt nie czeka w propozycjach z bazy.")).toBeNull();
    });

    it("sekcja ukrytych: cytat z CV, wynik „?”, zwinięta do 3 i „Dodaj” jak propozycja", async () => {
      hiddenApi.mockResolvedValue(hiddenPayload([101, 102, 103, 104, 105]));
      renderPanel();
      const section = await screen.findByTestId("hidden-by-critical");
      expect(within(section).getByRole("heading")).toHaveTextContent(
        "Ukryci przez „musi mieć”, choć w CV jest coś bliskiego · 5",
      );
      expect(section).toHaveTextContent("Bramka szukała „SailPoint IIQ”");
      const list = within(section).getByRole("list", { name: "Ukryci przez „musi mieć”" });
      expect(within(list).getAllByRole("checkbox")).toHaveLength(3);
      expect(within(list).getAllByTestId("hidden-trace")[0]).toHaveTextContent(
        "≈ SailPoint IIQ · w CV: „…applications to Sailpoint IdentityIQ…”",
      );
      expect(within(list).getAllByText("?")).toHaveLength(3);
      await userEvent.click(within(section).getByTestId("hidden-show-all"));
      expect(within(list).getAllByRole("checkbox")).toHaveLength(5);

      await userEvent.click(within(list).getByRole("button", { name: "Dodaj do „Nowych”: Ukryta Osoba 101" }));
      expect(addToJob).toHaveBeenCalledWith([101], { unlistedSource: "proposal_inbox" }, expect.anything());
    });

    it("„„SailPoint” = SailPoint IIQ” dopisuje wariant do wiersza zapisem Championa", async () => {
      hiddenApi.mockResolvedValue(hiddenPayload([101]));
      apiGet.mockResolvedValue({
        data: {
          job_id: 5,
          profile_hash: "hash-1",
          champion_profile: {
            stack: {
              must: [],
              nice: [],
              notes: "",
              critical: ["SailPoint IIQ"],
              rows: [
                { level: "must", words: ["SailPoint IIQ"] },
                { level: "must", words: ["Python"] },
              ],
            },
          },
        },
      });
      apiPut.mockResolvedValue({ data: {} });
      renderPanel();
      await userEvent.click(await screen.findByTestId("hidden-variant-add"));
      await userEvent.click(await screen.findByRole("button", { name: "Dopisz wariant" }));
      await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
      expect(apiGet).toHaveBeenCalledWith("/api/jobs/5/champion-profile", { params: { mark_read: false } });
      const [url, body] = apiPut.mock.calls[0] as [string, { stack: { rows: unknown[] }; expected_profile_hash: string }];
      expect(url).toBe("/api/jobs/5/champion-profile");
      expect(body.expected_profile_hash).toBe("hash-1");
      expect(body.stack.rows).toEqual([
        { level: "must", words: ["SailPoint IIQ", "SailPoint"] },
        { level: "must", words: ["Python"] },
      ]);
      await waitFor(() => expect(showSuccess).toHaveBeenCalled());
    });

    it("bez prawa zapisu Championa nie ma przycisku; dopisany wariant mówi „od następnej nocy”", async () => {
      hiddenApi.mockResolvedValue(hiddenPayload([101], { canAddVariant: false }));
      const { rerender } = renderPanel();
      await screen.findByTestId("hidden-by-critical");
      expect(screen.queryByTestId("hidden-variant-add")).toBeNull();
      hiddenApi.mockResolvedValue(hiddenPayload([101], { inRow: true }));
      rerender({ jobId: 6 });
      expect(await screen.findByTestId("hidden-variant-done")).toHaveTextContent(
        "„SailPoint” = SailPoint IIQ · od następnej nocy",
      );
    });

    it("awaria sekcji to komunikat z „Ponów”, nie pusta lista; pusta odpowiedź = brak sekcji", async () => {
      hiddenApi.mockRejectedValueOnce({ response: { status: 500 } });
      renderPanel();
      const alert = await screen.findByTestId("hidden-by-critical-error");
      expect(alert).toHaveTextContent("Ponów");
      hiddenApi.mockResolvedValue(hiddenPayload([]));
      await userEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
      await waitFor(() => expect(screen.queryByTestId("hidden-by-critical-error")).toBeNull());
      expect(screen.queryByTestId("hidden-by-critical")).toBeNull();
    });
  });
});
