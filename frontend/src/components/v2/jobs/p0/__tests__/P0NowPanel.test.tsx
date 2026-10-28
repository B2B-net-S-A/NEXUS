/**
 * Panel „P0 — ultrapilne teraz” (27.10.2026; propozycje Olafa 28.10.2026):
 * znika bez P0 i przy błędzie, wiersze z tablicy requestów (Daily), 3 od razu
 * i „Pokaż wszystkie”, prośby DL o P0 — HoR zatwierdza, DL wycofuje.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { P0NowPanel } from "@/components/v2/jobs/p0/P0NowPanel";

const state = vi.hoisted(() => ({
  value: {} as Record<string, unknown>,
  board: {} as Record<string, unknown>,
}));
const api = vi.hoisted(() => ({
  approve: vi.fn(async () => ({})),
  reject: vi.fn(async () => ({})),
  invalidate: vi.fn(),
}));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));

vi.mock("@/lib/api/jobP0", () => ({
  useP0Jobs: () => state.value,
  approveJobP0Request: api.approve,
  rejectJobP0Request: api.reject,
  invalidateP0: api.invalidate,
}));
vi.mock("@/lib/api/requestAllocation", () => ({ useRequestBoard: () => state.board }));
vi.mock("@/components/v2/request-board/RequestBoard", () => ({
  RequestBoard: ({ onlyJobIds }: { onlyJobIds: ReadonlySet<number> }) => (
    <div data-testid="p0-board">{[...onlyJobIds].join(",")}</div>
  ),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000 + 60_000).toISOString();

function item(job_id: number, hours: number) {
  return {
    job_id,
    title: `Rekrutacja testowa ${job_id}`,
    client_name: "Klient Fikcyjny",
    p0_until: inHours(hours),
    p0_reason: "Klient czeka na CV",
    p0_set_at: null,
    p0_set_by_name: "Anna Testowa",
    delivery_lead_name: "Ewa Przykładowa",
    recruiters: ["Jan Próbny"],
  };
}

const request = {
  job_id: 9,
  title: "Rekrutacja z prośbą",
  client_name: "Klient Fikcyjny",
  reason: "Klient zamyka listę w piątek",
  duration: "48h",
  requested_at: inHours(-1),
  requested_by_name: "Ewa Przykładowa",
};

function boardWith(...ids: number[]) {
  return { isSuccess: true, data: { requests: ids.map((job_id) => ({ job_id })) } };
}

describe("P0NowPanel", () => {
  beforeEach(() => {
    state.value = {};
    state.board = {};
    api.approve.mockClear();
    api.reject.mockClear();
  });

  it("bez P0 i bez próśb nic nie renderuje", () => {
    state.value = { isSuccess: true, data: { items: [], can_set: false, requests: [] } };
    const { container } = render(<P0NowPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("błąd zapytania nie udaje pustki — panel się chowa, P0 jest też na liście", () => {
    state.value = { isSuccess: false, isError: true };
    const { container } = render(<P0NowPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("bez tablicy requestów: zapasowe wiersze z powodem; wygasłe P0 pomija", () => {
    state.value = {
      isSuccess: true,
      data: { items: [item(1, 23), { ...item(2, 1), p0_until: inHours(-2) }], can_set: false },
    };
    state.board = { isSuccess: false, isError: true };
    render(<P0NowPanel />);
    expect(screen.getByRole("heading")).toHaveTextContent("P0 — ultrapilne teraz · 1");
    const rows = screen.getAllByTestId("p0-now-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("„Klient czeka na CV”");
    expect(screen.getByRole("link", { name: "Otwórz tablicę" })).toHaveAttribute("href", "/jobs/1");
    expect(screen.queryByTestId("p0-board")).toBeNull();
  });

  it("P0 z tablicy requestów idą wierszami Daily, reszta zapasowym wierszem", () => {
    state.value = {
      isSuccess: true,
      data: { items: [item(1, 5), item(2, 6)], can_set: false },
    };
    state.board = boardWith(1);
    render(<P0NowPanel />);
    expect(screen.getByTestId("p0-board")).toHaveTextContent("1");
    expect(screen.getAllByTestId("p0-now-row")).toHaveLength(1);
    expect(screen.getByText("P0 Twoich rekrutacji · ustawia Head of Recruitment")).toBeInTheDocument();
  });

  it("pokazuje 3 P0, „Pokaż wszystkie” rozwija resztę", async () => {
    state.value = {
      isSuccess: true,
      data: { items: [1, 2, 3, 4, 5].map((id) => item(id, 10 + id)), can_set: true },
    };
    state.board = boardWith(1, 2, 3, 4, 5);
    render(<P0NowPanel />);
    expect(screen.getByTestId("p0-board")).toHaveTextContent("1,2,3");
    await userEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie · jeszcze 2" }));
    expect(screen.getByTestId("p0-board")).toHaveTextContent("1,2,3,4,5");
    expect(screen.getByRole("button", { name: "Pokaż mniej" })).toBeInTheDocument();
  });

  it("Head of Recruitment: prośba DL z „Zatwierdź P0” i „Odrzuć”", async () => {
    state.value = { isSuccess: true, data: { items: [], can_set: true, requests: [request] } };
    render(<P0NowPanel />);
    const row = screen.getByTestId("p0-request-row");
    expect(row).toHaveTextContent("Ewa P. prosi o P0 na 48 h:");
    expect(row).toHaveTextContent("„Klient zamyka listę w piątek”");
    await userEvent.click(within(row).getByRole("button", { name: "Zatwierdź P0" }));
    expect(api.approve).toHaveBeenCalledWith(9);
    await userEvent.click(within(row).getByRole("button", { name: "Odrzuć" }));
    expect(api.reject).toHaveBeenCalledWith(9);
  });

  it("Delivery Lead widzi swoją prośbę i może ją wycofać, bez zatwierdzania", async () => {
    state.value = { isSuccess: true, data: { items: [], can_set: false, requests: [request] } };
    render(<P0NowPanel />);
    expect(screen.getByText("Twoja prośba o P0 czeka na Head of Recruitment")).toBeInTheDocument();
    const row = screen.getByTestId("p0-request-row");
    expect(within(row).queryByRole("button", { name: "Zatwierdź P0" })).toBeNull();
    await userEvent.click(within(row).getByRole("button", { name: "Wycofaj" }));
    expect(api.reject).toHaveBeenCalledWith(9);
  });
});
