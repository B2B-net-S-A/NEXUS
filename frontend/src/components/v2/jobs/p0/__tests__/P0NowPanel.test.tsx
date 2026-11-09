/**
 * Panel „Pilne u klientów” (27.10.2026; propozycje Olafa 28.10.2026):
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
  RequestBoard: ({
    onlyJobIds,
    recruitersAsCount,
  }: {
    onlyJobIds: ReadonlySet<number>;
    recruitersAsCount?: boolean;
  }) => (
    <div data-testid="p0-board" data-recruiters={recruitersAsCount ? "licznik" : "chipy"}>
      {[...onlyJobIds].join(",")}
    </div>
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

function boardRow(job_id: number, client_reference: string | null, title: string, sent: number) {
  return { job_id, client_reference, title, sent };
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

  it("bez tablicy requestów: zapasowe wiersze z powodem", () => {
    state.value = {
      isSuccess: true,
      data: { items: [item(1, 23)], can_set: false },
    };
    state.board = { isSuccess: false, isError: true };
    render(<P0NowPanel />);
    expect(screen.getByRole("heading")).toHaveTextContent("Pilne u klientów · 1");
    const rows = screen.getAllByTestId("p0-now-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("„Klient czeka na CV”");
    expect(screen.getByRole("link", { name: "Otwórz tablicę" })).toHaveAttribute("href", "/jobs/1");
    expect(screen.queryByTestId("p0-board")).toBeNull();
  });

  it("P0 po terminie zostaje (06.11.2026): HoR ma „Przedłuż” i „Zakończ”, reszta widzi, że czeka", () => {
    const overdue = { ...item(2, 1), p0_until: inHours(-3) };
    state.value = { isSuccess: true, data: { items: [item(1, 23), overdue], can_set: true } };
    state.board = { isSuccess: false, isError: true };
    const { unmount } = render(<P0NowPanel />);
    expect(screen.getByRole("heading")).toHaveTextContent("Pilne u klientów · 2");
    const rows = screen.getAllByTestId("p0-now-row");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("P0 · minęło 2 h");
    expect(screen.getByRole("button", { name: "Przedłuż o 24 h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zakończ P0" })).toBeInTheDocument();
    unmount();

    state.value = { isSuccess: true, data: { items: [overdue], can_set: false } };
    render(<P0NowPanel />);
    expect(screen.queryByRole("button", { name: "Zakończ P0" })).toBeNull();
    expect(screen.getByTestId("p0-overdue-waiting")).toHaveTextContent("dopóki Head of Recruitment");
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
    expect(screen.getByText("Twoje rekrutacje")).toBeInTheDocument();
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

// Audyt 2 (08.11.2026, wariant A Artura): na pulpicie P0 zostaje nad wszystkim,
// ale jako pasek jednej linii — pod nim od razu kolejka roli.
describe("P0NowPanel — pasek na pulpicie (compact)", () => {
  beforeEach(() => {
    state.value = {};
    state.board = {};
    api.approve.mockClear();
    api.reject.mockClear();
  });

  const overdue = (job_id: number, hours: number) => ({ ...item(job_id, 1), p0_until: inHours(-hours) });

  it("jedna linia: numer, tytuł, czas i wysłani — bez tabeli do kliknięcia", () => {
    state.value = { isSuccess: true, data: { items: [overdue(1, 35), item(2, 5)], can_set: false } };
    state.board = {
      isSuccess: true,
      data: { requests: [boardRow(1, "42511", "PL_KYC_3", 2), boardRow(2, null, "Senior PM", 8)] },
    };
    render(<P0NowPanel compact />);
    const line = screen.getByTestId("p0-now-line");
    expect(within(line).getByRole("heading")).toHaveTextContent("Pilne u klientów · 2");
    const first = within(line).getByRole("link", { name: /42511 PL_KYC_3/ });
    expect(first).toHaveAttribute("href", "/jobs/1");
    expect(first).toHaveTextContent("(minęło 34 h · wysłani 2)");
    expect(within(line).getByRole("link", { name: /Senior PM/ })).toHaveTextContent("(zostało 5 h · wysłani 8)");
    expect(screen.queryByTestId("p0-board")).toBeNull();
    expect(screen.queryByTestId("p0-now-row")).toBeNull();
  });

  it("bez tablicy requestów linia bierze tytuł rekrutacji i nie zmyśla „wysłani”", () => {
    state.value = { isSuccess: true, data: { items: [overdue(1, 35)], can_set: false } };
    state.board = { isSuccess: false, isError: true };
    render(<P0NowPanel compact />);
    const link = within(screen.getByTestId("p0-now-line")).getByRole("link", { name: /Rekrutacja testowa 1/ });
    expect(link).toHaveTextContent("(minęło 34 h)");
    expect(link).not.toHaveTextContent("wysłani");
  });

  it("w linii najwyżej 3 P0 i licznik reszty", () => {
    state.value = {
      isSuccess: true,
      data: { items: [1, 2, 3, 4, 5].map((id) => item(id, 10 + id)), can_set: true },
    };
    state.board = boardWith(1, 2, 3, 4, 5);
    render(<P0NowPanel compact />);
    const line = screen.getByTestId("p0-now-line");
    expect(within(line).getAllByRole("link")).toHaveLength(3);
    expect(line).toHaveTextContent("+2");
  });

  it("„Pokaż tabelę” rozwija wszystkie P0 z licznikiem osób, „Zwiń tabelę” wraca do linii", async () => {
    state.value = {
      isSuccess: true,
      data: { items: [1, 2, 3, 4, 5].map((id) => item(id, 10 + id)), can_set: true },
    };
    state.board = boardWith(1, 2, 3, 4, 5);
    render(<P0NowPanel compact />);
    await userEvent.click(screen.getByRole("button", { name: /Pokaż tabelę/ }));
    const board = screen.getByTestId("p0-board");
    expect(board).toHaveTextContent("1,2,3,4,5");
    expect(board).toHaveAttribute("data-recruiters", "licznik");
    expect(screen.queryByTestId("p0-now-toggle")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Zwiń tabelę/ }));
    expect(screen.queryByTestId("p0-board")).toBeNull();
  });

  it("P0 poza tablicą requestów też jest w rozwinięciu, z przyciskami HoR po terminie", async () => {
    state.value = { isSuccess: true, data: { items: [overdue(1, 3)], can_set: true } };
    state.board = { isSuccess: false, isError: true };
    render(<P0NowPanel compact />);
    expect(screen.queryByRole("button", { name: "Zakończ P0" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Pokaż tabelę/ }));
    expect(screen.getByTestId("p0-now-row")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zakończ P0" })).toBeInTheDocument();
  });

  it("brak P0 i próśb = brak linii i pustego pasa", () => {
    state.value = { isSuccess: true, data: { items: [], can_set: true, requests: [] } };
    const { container } = render(<P0NowPanel compact />);
    expect(container).toBeEmptyDOMElement();
  });

  it("HoR: prośby DL zostają rozwinięte pod zwiniętą linią", () => {
    state.value = { isSuccess: true, data: { items: [item(1, 5)], can_set: true, requests: [request] } };
    state.board = boardWith(1);
    render(<P0NowPanel compact />);
    expect(screen.getByTestId("p0-now-line")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("p0-request-row")).getByRole("button", { name: "Zatwierdź P0" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("p0-board")).toBeNull();
  });

  it("sama prośba bez trwającego P0: bez linii, sama prośba", () => {
    state.value = { isSuccess: true, data: { items: [], can_set: true, requests: [request] } };
    render(<P0NowPanel compact />);
    expect(screen.queryByTestId("p0-now-line")).toBeNull();
    expect(screen.getByTestId("p0-request-row")).toBeInTheDocument();
  });

  it("bez `compact` (Daily) tabela jak dotąd, bez paska", () => {
    state.value = { isSuccess: true, data: { items: [item(1, 5)], can_set: false } };
    state.board = boardWith(1);
    render(<P0NowPanel />);
    expect(screen.queryByTestId("p0-now-line")).toBeNull();
    expect(screen.getByTestId("p0-board")).toHaveAttribute("data-recruiters", "chipy");
  });
});
