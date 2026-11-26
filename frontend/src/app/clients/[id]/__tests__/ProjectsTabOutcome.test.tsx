import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Wynik zamkniętych projektów (prośba DL 26.11.2026, wariant „B + chipy”):
// wygrana = cały wiersz na zielono z imieniem zatrudnionego, chipy z licznikami
// z serwera, „Uzupełnij wynik” przy projekcie bez powodu — tylko z uprawnieniem.

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  canCloseLost: true,
  dialogProps: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));

vi.mock("@/components/client-profile/permissions", () => ({
  canCloseJobAsLost: () => mocks.canCloseLost,
  canMoveInPipeline: () => false,
}));

vi.mock("@/components/v2/jobs/JobCloseWithReasonDialog", () => ({
  JobCloseWithReasonDialog: (props: { jobTitle: string; mode: string }) => {
    mocks.dialogProps(props);
    return <div role="dialog">{`${props.mode}: ${props.jobTitle}`}</div>;
  },
}));

import { ProjectsTab } from "@/app/clients/[id]/ProjectsTab";
import {
  closedOutcomeNote,
  hiredLine,
  outcomeTotal,
} from "@/app/clients/[id]/projectOutcome";

const CLOSED = [
  {
    id: 11,
    title: "Tester PKN 177",
    location: "Warszawa",
    status: "closed",
    outcome: "won",
    hired_names: ["Filip K."],
    close_reason: "filled_by_us",
  },
  {
    id: 12,
    title: "Analityk IT 161",
    location: "Warszawa",
    status: "closed",
    outcome: "unreviewed",
    hired_names: [],
    close_reason: null,
  },
  {
    id: 13,
    title: "Konsultant GCP 251",
    location: "Płock",
    status: "closed",
    outcome: "neutral",
    hired_names: [],
    close_reason: "paused",
  },
];
const COUNTS = { won: 1, lost: 0, neutral: 1, unreviewed: 1 };

function fakeServer(_url: string, config?: { params?: Record<string, unknown> }) {
  const params = config?.params ?? {};
  if (params.status !== "closed") {
    return Promise.resolve({ data: { items: [], total: 0 } });
  }
  const pool = params.outcome ? CLOSED.filter((j) => j.outcome === params.outcome) : CLOSED;
  return Promise.resolve({
    data: { items: pool, total: pool.length, outcome_counts: COUNTS },
  });
}

function renderTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectsTab clientId={35} />
    </QueryClientProvider>,
  );
}

async function openClosed() {
  const user = userEvent.setup({ delay: null });
  renderTab();
  await user.click(await screen.findByRole("tab", { name: /Zamknięte projekty/ }));
  await screen.findByText("Tester PKN 177");
  return user;
}

function rowOf(title: string): HTMLElement {
  return screen.getByText(title).closest("tr") as HTMLElement;
}

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiGet.mockImplementation(fakeServer);
  mocks.canCloseLost = true;
  mocks.dialogProps.mockReset();
});

describe("projectOutcome — słowa do wiersza", () => {
  it("opisuje zatrudnionych i powód, a „bez wyniku” zostawia przyciskowi", () => {
    expect(hiredLine(["Piotr K."])).toBe("Zatrudniony: Piotr K.");
    expect(hiredLine(["Michał P.", "Paweł S."])).toBe("Zatrudnieni: Michał P., Paweł S.");
    expect(hiredLine([])).toBeNull();
    expect(closedOutcomeNote({ outcome: "neutral", close_reason: "paused" })).toMatch(
      /^Nie liczy się: /,
    );
    expect(closedOutcomeNote({ outcome: "lost", close_reason: "competitor" })).toMatch(
      /^Przegrana: /,
    );
    // Powód „obsadzone” bez osoby na „Zatrudniony” to w hit ratio przegrana.
    expect(closedOutcomeNote({ outcome: "lost", close_reason: "filled_by_us" })).toContain(
      "nikt nie jest na „Zatrudniony”",
    );
    expect(closedOutcomeNote({ outcome: "unreviewed", close_reason: null })).toBeNull();
    expect(outcomeTotal(COUNTS)).toBe(3);
  });
});

describe("ProjectsTab — wynik zamkniętych projektów", () => {
  it("prosi serwer o liczniki wyniku tylko dla zamkniętych", async () => {
    await openClosed();
    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        params: expect.objectContaining({ status: "closed", outcome_counts: true }),
      }),
    );
    const activeCall = mocks.apiGet.mock.calls.find(
      ([, config]) => (config as { params?: Record<string, unknown> } | undefined)?.params?.open_only,
    );
    expect(activeCall?.[1]).not.toHaveProperty("params.outcome_counts");
  });

  it("wygrana to zielony wiersz z plakietką i imieniem, reszta szara „Zamknięta”", async () => {
    await openClosed();
    const won = rowOf("Tester PKN 177");
    expect(won).toHaveAttribute("data-outcome", "won");
    expect(won.className).toContain("bg-success-muted");
    expect(within(won).getByText("Wygrana")).toBeInTheDocument();
    expect(within(won).getByText("Zatrudniony: Filip K.")).toBeInTheDocument();

    const neutral = rowOf("Konsultant GCP 251");
    expect(neutral.className).not.toContain("bg-success-muted");
    expect(within(neutral).getByText("Zamknięta")).toBeInTheDocument();
    expect(within(neutral).getByText(/^Nie liczy się: /)).toBeInTheDocument();
    expect(within(neutral).queryByText("Wygrana")).not.toBeInTheDocument();
  });

  it("chipy pokazują liczniki z serwera, a wybór chipa filtruje na serwerze", async () => {
    const user = await openClosed();
    const chips = screen.getByRole("group", { name: "Wynik projektu" });
    const wonChip = within(chips).getByRole("button", { name: /Wygrane/ });
    expect(wonChip).toHaveTextContent("1");
    expect(within(chips).getByRole("button", { name: /Wszystkie/ })).toHaveTextContent("3");

    await user.click(wonChip);
    expect(wonChip).toHaveAttribute("aria-pressed", "true");
    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        params: expect.objectContaining({ status: "closed", outcome: "won" }),
      }),
    );
    await screen.findByText("Tester PKN 177");
    expect(screen.queryByText("Analityk IT 161")).not.toBeInTheDocument();
    // Licznik zakładki to wszystkie zamknięte, nie tylko wybrany chip.
    expect(screen.getByRole("tab", { name: /Zamknięte projekty/ })).toHaveTextContent("3");
  });

  it("„Uzupełnij wynik” otwiera zmianę powodu zamknięcia", async () => {
    const user = await openClosed();
    const row = rowOf("Analityk IT 161");
    await user.click(within(row).getByRole("button", { name: "Uzupełnij wynik" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("change: Analityk IT 161");
    expect(mocks.dialogProps).toHaveBeenCalledWith(
      expect.objectContaining({ jobId: 12, clientId: 35 }),
    );
  });

  it("bez uprawnienia do zamykania nie ma przycisku, jest tylko opis", async () => {
    mocks.canCloseLost = false;
    await openClosed();
    const row = rowOf("Analityk IT 161");
    expect(within(row).queryByRole("button", { name: "Uzupełnij wynik" })).toBeNull();
    expect(within(row).getByText("Bez powodu zamknięcia")).toBeInTheDocument();
  });
});
