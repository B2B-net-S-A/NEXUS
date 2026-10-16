import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  jobsList: vi.fn(),
  forCandidate: vi.fn(),
  assignToJob: vi.fn(),
  send: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  jobsApi: { list: (...args: unknown[]) => mocks.jobsList(...args) },
  recommendationsApi: {
    forCandidate: (...args: unknown[]) => mocks.forCandidate(...args),
    assignToJob: (...args: unknown[]) => mocks.assignToJob(...args),
  },
}));

vi.mock("@/components/v2/RiskBadge", () => ({ RiskBadge: () => null }));

// Ruch karty ma własne testy; tu liczy się ładunek, z którym okno go woła.
vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({
    send: (...args: unknown[]) => mocks.send(...args),
    dialogs: null,
  }),
}));

import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { useTabsStore } from "@/store/tabs";

function renderSheet() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <QuickAssignV2 open onOpenChange={vi.fn()} candidateId={5} candidateName="Anna Nowak" />
    </QueryClientProvider>,
  );
}

describe("QuickAssignV2 (C5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTabsStore.setState({
      tabs: [{ id: "job-9", type: "job", entityId: 9, title: "Ostatnia rekrutacja", url: "/jobs/9" }],
      activeTabId: null,
    });
    mocks.apiGet.mockImplementation((url: string) =>
      url === "/api/jobs"
        ? Promise.resolve({ data: { items: [{ id: 3, title: "Rekrutacja z listy" }] } })
        : Promise.resolve({ data: null }),
    );
    mocks.jobsList.mockResolvedValue({ data: { items: [{ id: 1, title: "Moja rekrutacja" }] } });
    mocks.forCandidate.mockResolvedValue({
      data: { matches: [{ job: { id: 4, title: "Sugestia" }, total_score: null }], meta: { mode: "bm25", degraded: true, reason: null } },
    });
    mocks.assignToJob.mockResolvedValue({ data: {} });
  });

  it("otwiera się na „Wszystkie” z sekcjami „Moje otwarte” i „Ostatnio otwierane” nad listą", async () => {
    renderSheet();
    expect(screen.getByRole("tab", { name: /Wszystkie/ })).toHaveAttribute("aria-selected", "true");
    const mine = await screen.findByRole("region", { name: "Moje otwarte" });
    expect(await within(mine).findByText("Moja rekrutacja")).toBeInTheDocument();
    expect(mocks.jobsList).toHaveBeenCalledWith({ mine: true, open_only: true, page_size: 20 });
    expect(within(screen.getByRole("region", { name: "Ostatnio otwierane" })).getByText("Ostatnia rekrutacja")).toBeInTheDocument();
    expect(await screen.findByText("Rekrutacja z listy")).toBeInTheDocument();

    fireEvent.click(within(mine).getByRole("button", { name: "Przypisz" }));
    await waitFor(() => expect(mocks.assignToJob).toHaveBeenCalledWith(5, 1));
  });

  it("mówi, że osoba u nas pracuje, i oznacza rekrutację u tego samego klienta", async () => {
    mocks.jobsList.mockResolvedValue({
      data: {
        items: [
          { id: 1, title: "U obecnego klienta", client_id: 4 },
          { id: 2, title: "U innego klienta", client_id: 9 },
        ],
      },
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <QuickAssignV2
          open
          onOpenChange={vi.fn()}
          candidateId={5}
          candidateName="Anna Nowak"
          employment={{
            phase: "working",
            source: "contract",
            clients: [
              {
                client_id: 4,
                client_name: "Bank Przykładowy",
                contract_id: 40,
                phase: "working",
                order_end_date: "2026-12-31",
                delivery_lead_name: "Karol Wzorcowy",
              },
            ],
          }}
        />
      </QueryClientProvider>,
    );

    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Pracuje u nas · Bank Przykładowy");
    expect(notice).toHaveTextContent("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy");

    const mine = await screen.findByRole("region", { name: "Moje otwarte" });
    await within(mine).findByText("U obecnego klienta");
    expect(within(mine).getAllByText("Ten sam klient, u którego pracuje")).toHaveLength(1);
    // Znacznik nie blokuje: przypisanie do obu rekrutacji działa jak dotąd.
    expect(within(mine).getAllByRole("button", { name: "Przypisz" })).toHaveLength(2);
  });

  it("zamknięta karta: zamiast „Przypisano” okno mówi skąd i od kiedy i przywraca kartę", async () => {
    // Do 13.10.2026 serwer odpowiadał 200 „już w procesie” także przy
    // odrzuconej osobie, a wiersz pokazywał zielone „Przypisano”.
    mocks.assignToJob.mockRejectedValue(
      Object.assign(new Error("HTTP 409"), {
        response: {
          status: 409,
          data: {
            detail: {
              code: "closed_in_job",
              message: "Zamknięta karta w tej rekrutacji: Odrzucony 08.10.2026 (Jan Testowy)",
              closed: { candidate_name: "Anna Nowak", state_version: 2, restore_stage: "new", restore_stage_def_id: null },
            },
          },
        },
      }),
    );
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const onAssigned = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <QuickAssignV2 open onOpenChange={vi.fn()} candidateId={5} candidateName="Anna Nowak" onAssigned={onAssigned} />
      </QueryClientProvider>,
    );
    const mine = await screen.findByRole("region", { name: "Moje otwarte" });
    fireEvent.click(await within(mine).findByRole("button", { name: "Przypisz" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie przypisano do „Moja rekrutacja”.");
    expect(alert).toHaveTextContent("Odrzucony 08.10.2026 (Jan Testowy)");
    expect(within(mine).queryByText("Przypisano")).not.toBeInTheDocument();
    expect(onAssigned).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Przywróć do „Nowych”" }));
    await waitFor(() => expect(onAssigned).toHaveBeenCalledWith(1));
    expect(mocks.send).toHaveBeenCalledWith(
      { candidate_id: 5, job_id: 1, stage: "new", expected_state_version: 2 },
      expect.objectContaining({ candidateName: "Anna Nowak" }),
    );
    expect(within(mine).getByText("Przywrócono")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nazywa rekrutację jak jej nagłówek: numer u klienta i tytuł dla rekrutera, klient w drugiej linii", async () => {
    // Zgłoszenie 16.10.2026: okno pokazywało „AI Engineer (ZOB-2984)” (nazwa od
    // klienta), a rekrutacja nazywa się „Senior AI Engineer · Java, LLM · 5+ lat”.
    const names = {
      title: "AI Engineer (ZOB-2984)",
      working_title: "Senior AI Engineer · Java, LLM · 5+ lat",
      client_reference: "ZOB-2984",
      client_name: "Bank Przykładowy",
      location: "Warszawa",
    };
    mocks.jobsList.mockResolvedValue({ data: { items: [{ id: 1, ...names }] } });
    mocks.forCandidate.mockResolvedValue({
      data: { matches: [{ job: { id: 4, ...names }, total_score: 81 }], meta: { mode: "semantic", degraded: false, reason: null } },
    });
    useTabsStore.setState({
      tabs: [{ id: "job-9", type: "job", entityId: 9, title: "Ostatnia rekrutacja", reference: "42946", url: "/jobs/9" }],
      activeTabId: null,
    });
    mocks.assignToJob.mockRejectedValue(
      Object.assign(new Error("HTTP 409"), {
        response: {
          status: 409,
          data: {
            detail: {
              code: "closed_in_job",
              message: "Zamknięta karta w tej rekrutacji: Odrzucony 08.10.2026 (Jan Testowy)",
              closed: { candidate_name: "Anna Nowak", state_version: 2, restore_stage: "new", restore_stage_def_id: null },
            },
          },
        },
      }),
    );
    renderSheet();

    const mine = await screen.findByRole("region", { name: "Moje otwarte" });
    expect(await within(mine).findByText("Senior AI Engineer · Java, LLM · 5+ lat")).toBeInTheDocument();
    expect(within(mine).getByText("ZOB-2984")).toBeInTheDocument();
    expect(within(mine).getByText("Bank Przykładowy · Warszawa")).toBeInTheDocument();
    expect(within(mine).queryByText("AI Engineer (ZOB-2984)")).not.toBeInTheDocument();
    // Nazwa od klienta zostaje w dymku.
    expect(within(mine).getByTestId("job-pick-name")).toHaveAttribute(
      "title",
      expect.stringContaining("Nazwa u klienta: AI Engineer (ZOB-2984)"),
    );
    const recent = screen.getByRole("region", { name: "Ostatnio otwierane" });
    expect(within(recent).getByText("42946")).toBeInTheDocument();

    fireEvent.click(within(mine).getByRole("button", { name: "Przypisz" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie przypisano do „Senior AI Engineer · Java, LLM · 5+ lat”.",
    );

    fireEvent.mouseDown(screen.getByRole("tab", { name: /AI sugestie/ }));
    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Senior AI Engineer · Java, LLM · 5+ lat")).toBeInTheDocument();
    expect(within(panel).getByText("ZOB-2984")).toBeInTheDocument();
  });

  it("bez znacznika okno nie rysuje ramki", async () => {
    renderSheet();
    await screen.findByRole("region", { name: "Moje otwarte" });
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("po wpisaniu frazy skróty znikają", async () => {
    renderSheet();
    await screen.findByRole("region", { name: "Moje otwarte" });
    fireEvent.change(screen.getByPlaceholderText("Tytuł, klient albo numer…"), { target: { value: "java" } });
    expect(screen.queryByRole("region", { name: "Moje otwarte" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ostatnio otwierane" })).not.toBeInTheDocument();
  });

  it("ranking awaryjny opisany zwykłym językiem, bez „BM25”", async () => {
    renderSheet();
    fireEvent.mouseDown(screen.getByRole("tab", { name: /AI sugestie/ }));
    expect(await screen.findByText("Ranking uproszczony (bez AI).")).toBeInTheDocument();
    expect(screen.queryByText(/BM25/)).not.toBeInTheDocument();
  });
});
