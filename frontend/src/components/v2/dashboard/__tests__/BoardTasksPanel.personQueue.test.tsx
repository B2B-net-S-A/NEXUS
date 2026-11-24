import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonPair, PersonQueueEntry } from "@/lib/dashboard-person-queue";

const get = vi.fn();
const open = vi.fn();
let seenEntries: readonly PersonQueueEntry[] = [];
// Panel osoby z kolejki: ile razy się zamontował (ma przeżyć opróżnienie list).
const panelMounts = vi.fn();
let queueOpen = false;

vi.mock("@/lib/api", () => {
  const client = { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn() };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}));
// Sam panel osoby na pulpicie ma własne testy (`DashboardPersonQueue.test.tsx`).
vi.mock("@/components/v2/dashboard/DashboardPersonQueue", () => ({
  useDashboardPersonQueue: (entries: readonly PersonQueueEntry[]) => {
    seenEntries = entries;
    return { open: (pair?: PersonPair) => open(pair), element: queueOpen ? <QueuePanelProbe /> : null };
  },
}));

import { useEffect } from "react";

import { BoardTasksPanel } from "@/components/v2/dashboard/BoardTasksPanel";
import { useAuthStore } from "@/store/auth";

const since = "2026-11-01T10:00:00Z";

function QueuePanelProbe() {
  useEffect(() => panelMounts(), []);
  return <div data-testid="queue-panel-probe" />;
}

function flowPair(over: Record<string, unknown>) {
  return {
    candidate_id: 21,
    candidate_name: "Anna Nowak",
    job_id: 31,
    job_title: "Java Developer",
    job_working_title: null,
    client_name: "Bank Kappa",
    since,
    claimed_until: null,
    missing: ["sheet"],
    qc_status: null,
    ...over,
  };
}

function mockFlow(flow: Record<string, unknown>) {
  get.mockImplementation((url: string) => {
    if (url === "/api/board-tasks")
      return Promise.resolve({
        data: {
          window_days: 14,
          cpro_to_send: [],
          cpro_sent: [],
          flow: {
            applies: true,
            postings: [],
            postings_total: 0,
            claimed: [],
            screening: [],
            verified: [],
            waiting_client: [],
            waiting_client_days: 7,
            unsigned_contracts: [],
            order_mail_review: 0,
            ...flow,
          },
        },
      });
    return Promise.resolve({ data: [] });
  });
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BoardTasksPanel />
    </QueryClientProvider>,
  );
}

describe("„Czeka na Ciebie” — „Pracuj po kolei” (23.11.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seenEntries = [];
    queueOpen = false;
    useAuthStore.setState({ user: { id: 241, role: "recruiter" }, realUser: null } as never);
  });

  it("przycisk w nagłówku liczy osoby z trzech list i otwiera kolejkę od pierwszej", async () => {
    mockFlow({
      screening: [flowPair({ candidate_id: 22, candidate_name: "Jan Lis", since: "2026-10-19T08:00:00Z" })],
      verified: [flowPair({ candidate_id: 23, candidate_name: "Ewa Dąb", job_id: 32, missing: [] })],
      autofill_decisions: [
        {
          job_id: 41,
          job_title: "Senior Java",
          job_working_title: null,
          client_name: null,
          candidate_id: 61,
          candidate_name: "Ola Lis",
          score: 80,
          waiting_days: 3,
        },
      ],
      autofill_decisions_total: 1,
    });
    renderPanel();
    const region = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    const start = within(region).getByTestId("person-queue-start");
    expect(start).toHaveTextContent("Pracuj po kolei · 3");
    expect(seenEntries.map((e) => e.key)).toEqual(["31:22", "32:23", "41:61"]);
    await userEvent.click(start);
    expect(open).toHaveBeenCalledWith(undefined);
  });

  it("klik w osobę z listy otwiera ją na pulpicie; ⌘-klik zostaje linkiem do Tablicy", async () => {
    mockFlow({ verified: [flowPair({ candidate_id: 23, candidate_name: "Ewa Dąb", job_id: 32, missing: [] })] });
    renderPanel();
    const link = await screen.findByRole("link", { name: "Ewa Dąb" });
    expect(link).toHaveAttribute("href", "/jobs/32?candidate=23");
    await userEvent.click(link);
    expect(open).toHaveBeenCalledWith({ jobId: 32, candidateId: 23 });
    open.mockClear();
    fireEvent.click(link, { metaKey: true });
    expect(open).not.toHaveBeenCalled();
  });

  it("„Otwórz” przy osobie od systemu otwiera panel na pulpicie", async () => {
    mockFlow({
      autofill_decisions: [
        {
          job_id: 41,
          job_title: "Senior Java",
          job_working_title: null,
          client_name: null,
          candidate_id: 61,
          candidate_name: "Ola Lis",
          score: 80,
          waiting_days: 3,
        },
      ],
      autofill_decisions_total: 1,
    });
    renderPanel();
    await userEvent.click(await screen.findByRole("link", { name: "Otwórz Ola Lis w panelu osoby" }));
    expect(open).toHaveBeenCalledWith({ jobId: 41, candidateId: 61 });
  });

  it("bez osób w trzech listach przycisku nie ma", async () => {
    mockFlow({ postings: [{ job_id: 31, job_title: "Java", client_name: null, count: 4, oldest_at: since }], postings_total: 4 });
    renderPanel();
    await screen.findByRole("region", { name: "Czeka na Ciebie" });
    expect(screen.queryByTestId("person-queue-start")).toBeNull();
  });

  it("otwarty panel przeżywa opróżnienie list (ostatnia osoba przeszła dalej) — bez ponownego montowania", async () => {
    queueOpen = true;
    mockFlow({ verified: [flowPair({ candidate_id: 23, candidate_name: "Ewa Dąb", job_id: 32, missing: [] })] });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <BoardTasksPanel />
      </QueryClientProvider>,
    );
    await screen.findByRole("region", { name: "Czeka na Ciebie" });
    expect(screen.getByTestId("queue-panel-probe")).toBeTruthy();
    mockFlow({});
    await qc.invalidateQueries();
    await screen.findByText("Nic na Ciebie teraz nie czeka.");
    expect(screen.getByTestId("queue-panel-probe")).toBeTruthy();
    expect(panelMounts).toHaveBeenCalledTimes(1);
  });
});
