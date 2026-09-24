import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const addToJob = vi.fn();
const startRun = vi.fn();
const bulkAdd = vi.fn();
const forJob = vi.fn();
const toast = vi.fn();
const factsApi = vi.fn();
const matchScores = vi.fn();

function entry(id: number, name: string, origins: string[], extra: Record<string, unknown> = {}) {
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
      sources: origins.includes("run") ? ["full_base"] : ["similar_projects"],
      reason: null,
      isNew: false,
      previouslyDismissed: false,
      runId: null,
      ...extra,
    },
    detail: { origins, title: "Java Developer", eligibility: null },
  };
}

const proposalsState = {
  entries: [] as ReturnType<typeof entry>[],
  adding: false,
  addToJob: (...a: unknown[]) => addToJob(...a),
  status: {
    run: { data: undefined, runId: null, starting: false, running: false, error: null, offset: 0, setOffset: vi.fn(), fetching: false },
    startRun: () => startRun(),
    retryRun: vi.fn(),
    latestRun: null,
    engineDegraded: false,
    settled: true,
    inbox: { isError: false, error: null },
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
    jobProposalsApi: { ...actual.jobProposalsApi, facts: (...a: unknown[]) => factsApi(...a) },
  };
});
vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: {
    get: () =>
      Promise.resolve({
        all_of: [
          { level: "must", any_of: ["java"] },
          { level: "nice", any_of: ["kubernetes"] },
        ],
      }),
  },
  requirementLabels: (c: { all_of?: Array<{ level: string; any_of: string[] }> } | undefined, level: string) =>
    (c?.all_of ?? []).filter((g) => g.level === level).map((g) => g.any_of.join(" lub ")),
}));
vi.mock("@/lib/api/myPeople", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    MY_PEOPLE_QUERY_PREFIX: ["my-people"],
    useMyPeopleForJob: (jobId: number, enabled: boolean) =>
      useQuery({ queryKey: ["my-people", "for-job", jobId], queryFn: () => forJob(jobId), enabled }),
  };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: toast, showError: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("@/components/talent-radar/FullCandidateSearchStatus", () => ({
  FullCandidateSearchStatus: () => <div data-testid="run-status" />,
}));

import { AddCandidatesPanel } from "@/components/v2/recruitment/AddCandidatesPanel";

function renderPanel(overrides: Record<string, unknown> = {}) {
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    jobId: 5,
    budgetHourly: 160,
    location: "Warszawa",
    pipelineCandidateIds: [99],
    onOpenManualSearch: vi.fn(),
    onOpenQuickAdd: vi.fn(),
    onOpenFromCv: vi.fn(),
    ...overrides,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AddCandidatesPanel {...props} />
    </QueryClientProvider>,
  );
  return props;
}

describe("AddCandidatesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    proposalsState.entries = [];
    (proposalsState.status.run as { data: unknown }).data = undefined;
    proposalsState.status.latestRun = null;
    factsApi.mockResolvedValue({ job_id: 5, items: [] });
  });

  it("zamknięty panel nie montuje treści ani zapytań", () => {
    renderPanel({ open: false });
    expect(screen.queryByTestId("add-candidates-panel")).toBeNull();
    expect(forJob).not.toHaveBeenCalled();
  });

  it("„Szukaj w bazie (AI)”: kryteria z Championa, start przeglądu kliknięciem, „Zmień kryteria”", async () => {
    const props = renderPanel();
    const panel = await screen.findByTestId("add-candidates-panel");
    expect(within(panel).getByRole("tab", { name: "Szukaj w bazie (AI)" })).toHaveAttribute("aria-selected", "true");
    const criteria = await within(panel).findByRole("list", { name: "Kryteria wyszukiwania" });
    await within(criteria).findByText("java");
    expect(within(criteria).getByText("kubernetes")).toBeTruthy();
    expect(within(criteria).getByText(/Warszawa/)).toBeTruthy();
    expect(within(criteria).getByText("do 160 zł/h")).toBeTruthy();

    await userEvent.click(within(panel).getByRole("button", { name: /Przeszukaj całą bazę/ }));
    expect(startRun).toHaveBeenCalledTimes(1);

    await userEvent.click(within(panel).getByRole("button", { name: "Zmień kryteria" }));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onOpenManualSearch).toHaveBeenCalled();
  });

  it("zakładka „Propozycje” liczy osoby, zaznaczenie aktualizuje stopkę, dodanie idzie przez propozycje", async () => {
    proposalsState.entries = [
      entry(1, "Anna Kowalczyk", ["inbox"]),
      entry(2, "Piotr Nowak", ["similar"], { warnings: ["over_budget"] }),
      entry(3, "Ola Wynik", ["run"]),
    ];
    renderPanel();
    const tab = await screen.findByRole("tab", { name: "Propozycje · 2" });
    await userEvent.click(tab);
    const list = screen.getByRole("list", { name: "Propozycje" });
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
    renderPanel({ initialTab: "proposals" });
    expect(await screen.findByText("Weto HM: Brak bankowości")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Jan Weto" })).toBeDisabled();
  });

  it("„Moi ludzie”: bez osób już w rekrutacji, dodanie ze źródłem my_people", async () => {
    forJob.mockResolvedValue({
      job_id: 5,
      job_title: "Java",
      in_job_count: 1,
      degraded: false,
      rows: [
        { candidate_id: 99, full_name: "Już W Rekrutacji", score: 90, measurement: "ok", eligibility: null, sent_to_client_at: null, last_sent_client_name: null, days_since_last_send: null, expected_rate_hourly: null, active_processes: 0 },
        { candidate_id: 42, full_name: "Ewa Moja", score: null, measurement: "unavailable", eligibility: null, sent_to_client_at: null, last_sent_client_name: "PKO BP", days_since_last_send: 12, expected_rate_hourly: 140, active_processes: 1 },
      ],
    });
    bulkAdd.mockResolvedValue({ added: [42], skipped: [], warnings: [], total_added: 1, total_skipped: 0 });
    renderPanel({ initialTab: "my_people" });
    const list = await screen.findByRole("list", { name: "Moi ludzie" });
    expect(within(list).queryByText("Już W Rekrutacji")).toBeNull();
    expect(within(list).getByText("nie policzono")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Moi ludzie · 1" })).toBeTruthy();
    await userEvent.click(within(list).getByRole("checkbox", { name: "Zaznacz Ewa Moja" }));
    await userEvent.click(screen.getByTestId("add-candidates-submit"));
    await waitFor(() =>
      expect(bulkAdd).toHaveBeenCalledWith(5, { candidate_ids: [42], source: "my_people" }),
    );
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Dodano z Moich ludzi: 1", "success"));
    expect(addToJob).not.toHaveBeenCalled();
  });

  it("„Po nazwisku / z pliku CV” otwiera dotychczasowe okna", async () => {
    const props = renderPanel({ initialTab: "by_name" });
    await userEvent.click(await screen.findByRole("button", { name: /Po nazwisku/ }));
    expect(props.onOpenQuickAdd).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Z pliku CV/ }));
    expect(props.onOpenFromCv).toHaveBeenCalled();
  });

  it("Propozycje: fakty zamiast pustych pól, historia u klienta i sortowanie „najpierw byli u tego klienta”", async () => {
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
          client_history: { job_id: 77, title: "Senior Java", furthest_stage: "cv_sent", furthest_stage_label: "CV Wysłane", outcome: "rejected", last_moved_at: null },
        },
      ],
    });
    renderPanel({ initialTab: "proposals" });
    const list = await screen.findByRole("list", { name: "Propozycje" });
    await within(list).findByText("Java Developer @ Firma · 8 lat dośw. · Gdańsk · tylko zdalnie · 170 zł/h");
    expect(within(list).getByText("Tester · 3 lata dośw. · Łódź")).toBeTruthy();
    expect(
      within(list).getByText("Był(a) u tego klienta: Senior Java — doszedł(a) do etapu „CV Wysłane” (odrzucony/a)"),
    ).toBeTruthy();
    expect(within(list).queryByText(/stawka —/)).toBeNull();
    // Domyślnie na górze osoba z historią u klienta.
    const names = within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual(["Zaznacz Bartek Drugi", "Zaznacz Anna Pierwsza"]);
    await userEvent.click(screen.getByRole("button", { name: "Kolejność propozycji" }));
    expect(within(list).getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"))).toEqual([
      "Zaznacz Anna Pierwsza",
      "Zaznacz Bartek Drugi",
    ]);
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
    renderPanel({ initialTab: "proposals" });
    const list = await screen.findByRole("list", { name: "Propozycje" });
    expect(within(list).getAllByText("nie policzono")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 2/ }));
    await within(list).findByText("71%");
    expect(within(list).getByText("Ocena niepełna")).toBeTruthy();
    expect(within(list).getByText("64%")).toBeTruthy();
    expect(matchScores).toHaveBeenCalledTimes(1);
    expect(matchScores.mock.calls[0][0]).toBe(5);
    expect([...matchScores.mock.calls[0][1]].sort()).toEqual([1, 2]);
    expect(screen.queryByRole("button", { name: /Policz dopasowanie/ })).toBeNull();
  });

  it("po dodaniu osoby z listy policzone wyniki pozostałych zostają (nie wracają do „liczę…”)", async () => {
    proposalsState.entries = [
      entry(1, "Anna Pierwsza", ["similar"], { fitScore: null }),
      entry(2, "Bartek Drugi", ["similar"], { fitScore: null }),
      entry(3, "Cezary Trzeci", ["similar"], { fitScore: null }),
    ];
    matchScores.mockResolvedValue({
      scores: { "1": 81, "2": 72, "3": 63 },
      breakdowns: {},
      profile_key: "p:1",
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      jobId: 5,
      budgetHourly: 160,
      location: "Warszawa",
      pipelineCandidateIds: [99],
      onOpenManualSearch: vi.fn(),
      onOpenQuickAdd: vi.fn(),
      onOpenFromCv: vi.fn(),
      initialTab: "proposals" as const,
    };
    const tree = () => (
      <QueryClientProvider client={qc}>
        <AddCandidatesPanel {...props} />
      </QueryClientProvider>
    );
    const { rerender } = render(tree());
    const list = await screen.findByRole("list", { name: "Propozycje" });
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 3/ }));
    await within(list).findByText("81%");

    // Osoba 1 dodana do rekrutacji — znika z propozycji, panel zostaje otwarty.
    proposalsState.entries = proposalsState.entries.filter((e) => e.row.candidateId !== 1);
    rerender(tree());

    const after = screen.getByRole("list", { name: "Propozycje" });
    expect(within(after).getByText("72%")).toBeTruthy();
    expect(within(after).getByText("63%")).toBeTruthy();
    expect(within(after).queryByText("liczę…")).toBeNull();
    expect(matchScores).toHaveBeenCalledTimes(1);
  });

  it("błąd liczenia to „nie policzono — ponów”, nigdy 0", async () => {
    proposalsState.entries = [entry(1, "Anna Pierwsza", ["similar"], { fitScore: null })];
    matchScores.mockRejectedValueOnce({ response: { status: 500 } });
    renderPanel({ initialTab: "proposals" });
    await screen.findByRole("list", { name: "Propozycje" });
    await userEvent.click(screen.getByRole("button", { name: /Policz dopasowanie dla 1/ }));
    const retry = await screen.findByRole("button", { name: "nie policzono — ponów" });
    expect(screen.queryByText("0%")).toBeNull();
    matchScores.mockResolvedValueOnce({ scores: { "1": 55 }, breakdowns: {}, profile_key: "p:1" });
    await userEvent.click(retry);
    await screen.findByText("55%");
  });
});
