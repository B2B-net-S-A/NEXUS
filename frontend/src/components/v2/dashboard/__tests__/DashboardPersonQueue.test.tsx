import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PanelOnlyQueue } from "@/components/v2/pages/KanbanBoardV2";

const get = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api", () => {
  const client = { get: (...a: unknown[]) => get(...a) };
  return {
    __esModule: true,
    default: client,
    matchingApi: { pipelineScores: () => Promise.resolve({ data: { scores: {} } }) },
  };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError: vi.fn(), showInfo: vi.fn(), showActionToast: vi.fn() }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// Panel Tablicy ma własne testy (`KanbanBoardV2.test.tsx`, „Pracuj po kolei”);
// tu sprawdzamy, co pulpit mu podaje i jak reaguje na jego zdarzenia.
let lastPanel: PanelOnlyQueue | null = null;
vi.mock("@/components/v2/pages/KanbanBoardV2", () => ({
  KanbanBoardV2: ({ jobId, panelOnly }: { jobId: number; panelOnly: PanelOnlyQueue }) => {
    lastPanel = panelOnly;
    return (
      <div data-testid="panel-stub">
        {panelOnly.banner}
        <p>
          rekrutacja {jobId} · osoba {panelOnly.candidateId} · {panelOnly.label}{" "}
          {panelOnly.position ?? "–"} z {panelOnly.total}
        </p>
        {panelOnly.closedNotice ? (
          <p>
            {panelOnly.closedNotice.verb}: {panelOnly.closedNotice.name}
          </p>
        ) : null}
        <button type="button" onClick={panelOnly.onNext}>
          ›
        </button>
        <button type="button" onClick={panelOnly.onClose}>
          zamknij
        </button>
      </div>
    );
  },
}));

import { useDashboardPersonQueue } from "@/components/v2/dashboard/DashboardPersonQueue";
import type { PersonQueueEntry } from "@/lib/dashboard-person-queue";
import { useAuthStore } from "@/store/auth";

function entry(jobId: number, candidateId: number, list: PersonQueueEntry["list"] = "screening"): PersonQueueEntry {
  return {
    key: `${jobId}:${candidateId}`,
    list,
    jobId,
    candidateId,
    candidateName: `Osoba ${candidateId}`,
    jobLabel: `Rekrutacja ${jobId}`,
    clientName: null,
    waiting: "od 3 dni",
  };
}

const ENTRIES = [entry(1, 11), entry(2, 21, "verified"), entry(3, 31, "autofill")];

function Harness({ entries }: { entries: PersonQueueEntry[] }) {
  const queue = useDashboardPersonQueue(entries);
  return (
    <main id="main">
      <button type="button" onClick={() => queue.open()}>
        Pracuj po kolei
      </button>
      {queue.element}
    </main>
  );
}

function renderQueue(entries: PersonQueueEntry[] = ENTRIES) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Harness entries={entries} />
    </QueryClientProvider>,
  );
}

function kanbanOk() {
  get.mockImplementation((url: string) => {
    if (url.startsWith("/api/pipeline/kanban/")) return Promise.resolve({ data: { columns: [] } });
    if (url.startsWith("/api/jobs/")) return Promise.resolve({ data: { id: 1, title: "Rekrutacja", client_id: 5 } });
    return Promise.reject(new Error(`nieoczekiwane ${url}`));
  });
}

describe("Pracuj po kolei — panel osoby na pulpicie (23.11.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastPanel = null;
    useAuthStore.setState({ user: { id: 241, role: "recruiter" }, realUser: null } as never);
  });

  it("start od pierwszej osoby: pasek z listą, rekrutacją i „Dalej”, licznik 1 z 3", async () => {
    kanbanOk();
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    expect(await screen.findByText(/rekrutacja 1 · osoba 11 · Czeka na Ciebie 1 z 3/)).toBeTruthy();
    const bar = screen.getByTestId("person-queue-bar");
    expect(within(bar).getByTestId("person-queue-list")).toHaveTextContent("Screening bez arkusza");
    expect(within(bar).getByText(/Rekrutacja 1/)).toBeTruthy();
    expect(within(bar).getByTestId("person-queue-next")).toHaveTextContent("Dalej: Osoba 21 · Rekrutacja 2");
    expect(within(bar).getByRole("link", { name: /Otwórz Tablicę/ })).toHaveAttribute(
      "href",
      "/jobs/1?candidate=11",
    );
  });

  it("„›” i „Dalej” przechodzą do osoby w innej rekrutacji", async () => {
    kanbanOk();
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    await userEvent.click(await screen.findByRole("button", { name: "›" }));
    expect(await screen.findByText(/rekrutacja 2 · osoba 21 · Czeka na Ciebie 2 z 3/)).toBeTruthy();
    expect(screen.getByTestId("person-queue-list")).toHaveTextContent("Przygotowanie CV — czekają na CV");
    await userEvent.click(screen.getByTestId("person-queue-next"));
    expect(await screen.findByText(/rekrutacja 3 · osoba 31 · Czeka na Ciebie 3 z 3/)).toBeTruthy();
    expect(screen.getByTestId("person-queue-list")).toHaveTextContent("Od systemu czeka na decyzję");
    expect(screen.getByTestId("person-queue-bar")).toHaveTextContent("To ostatnia osoba w kolejce.");
    expect(get).toHaveBeenCalledWith("/api/pipeline/kanban/3");
  });

  it("po odrzuceniu z panelu osoba znika z kolejki, panel pokazuje następną z paskiem „Odrzucono”", async () => {
    kanbanOk();
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    await screen.findByText(/osoba 11/);
    lastPanel!.onClosedFromPanel({ candidateId: 11, name: "Osoba 11", verb: "Odrzucono", reasonLabel: "Stawka" });
    expect(await screen.findByText(/rekrutacja 2 · osoba 21 · Czeka na Ciebie 1 z 2/)).toBeTruthy();
    expect(screen.getByText("Odrzucono: Osoba 11")).toBeTruthy();
  });

  it("odrzucenie, gdy rekruter przeszedł już do innej osoby, niczego nie przestawia", async () => {
    kanbanOk();
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    await screen.findByText(/osoba 11/);
    const stale = lastPanel!;
    await userEvent.click(screen.getByRole("button", { name: "›" }));
    await screen.findByText(/osoba 21/);
    stale.onClosedFromPanel({ candidateId: 11, name: "Osoba 11", verb: "Odrzucono", reasonLabel: null });
    await waitFor(() => expect(screen.getByText(/osoba 21 · Czeka na Ciebie 2 z 3/)).toBeTruthy());
  });

  it("po ostatniej osobie panel się zamyka z komunikatem", async () => {
    kanbanOk();
    renderQueue([entry(1, 11)]);
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    await screen.findByText(/osoba 11/);
    lastPanel!.onClosedFromPanel({ candidateId: 11, name: "Osoba 11", verb: "Rezygnacja", reasonLabel: null });
    await waitFor(() => expect(screen.queryByTestId("panel-stub")).toBeNull());
    expect(showSuccess).toHaveBeenCalledWith(
      "Rezygnacja: Osoba 11. To była ostatnia osoba w kolejce „Czeka na Ciebie”.",
    );
  });

  it("inna osoba tej rekrutacji w panelu → „Poza kolejką” i powrót do kolejki", async () => {
    kanbanOk();
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    await screen.findByText(/osoba 11/);
    lastPanel!.onPersonChange(77);
    expect(await screen.findByText(/rekrutacja 1 · osoba 77 · Czeka na Ciebie – z 3/)).toBeTruthy();
    expect(screen.getByTestId("person-queue-list")).toHaveTextContent("Poza kolejką");
    expect(lastPanel!.onReturnToQueue).toBeTypeOf("function");
  });

  it("awaria wczytania Tablicy nie wygląda jak pusty panel — komunikat i „Spróbuj ponownie”", async () => {
    get.mockRejectedValue(Object.assign(new Error("boom"), { response: { status: 500 } }));
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    expect(await screen.findByText("Nie udało się wczytać Tablicy tej rekrutacji.")).toBeTruthy();
    expect(screen.getByTestId("person-queue-bar")).toBeTruthy();
    expect(screen.queryByTestId("panel-stub")).toBeNull();
  });

  it("w trakcie wczytywania pasek kolejki już stoi, panel mówi, że się wczytuje", async () => {
    get.mockImplementation(() => new Promise(() => undefined));
    renderQueue();
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    expect(await screen.findByText("Wczytuję panel osoby…")).toBeTruthy();
    expect(screen.getByTestId("person-queue-list")).toHaveTextContent("Screening bez arkusza");
  });

  it("pusta kolejka — „Pracuj po kolei” niczego nie otwiera", async () => {
    kanbanOk();
    renderQueue([]);
    await userEvent.click(screen.getByRole("button", { name: "Pracuj po kolei" }));
    expect(screen.queryByTestId("person-queue-bar")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});
