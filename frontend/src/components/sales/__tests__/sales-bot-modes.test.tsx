/** Leady → „Warto wrócić” (G-E) i „Nowe centra IT” (G-D) z bota. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LatestSignalRun, Lead, LeadList } from "@/lib/api/sales";
import type { BotResult, BotResults } from "@/lib/api/sales-bot-results";

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: 1,
    source: "research",
    status: "new",
    title: "Nowy program chmurowy",
    summary: "Przenoszą aplikacje do chmury",
    company_name: "Firma A",
    company_id: 7,
    url: "https://example.com/a",
    score: 60,
    signal_at: "2026-11-01T12:00:00Z",
    opportunity_id: null,
    dismissed_reason: null,
    created_at: "2026-11-09T07:00:00Z",
    payload: {
      origin: "winback",
      type: "program",
      strength: "medium",
      why_now: "Program potrzebuje zespołu",
      published: "2026-11-01",
      lost_opportunity_id: 55,
      lost_opportunity_title: "Wsparcie aplikacji",
      lost_reason: "Klient zrezygnował z projektu",
      lost_at: "2026-04-08T10:00:00+00:00",
    },
    assignee: { id: 3, name: "Opiekun Testowy" },
    assignee_in_sales: true,
    ...over,
  };
}

function result(over: Partial<BotResult> = {}): BotResult {
  return {
    id: 9,
    kind: "discovery",
    company: null,
    status: "new",
    payload: {
      company: "Centrum Testowe",
      domain: null,
      city: "Wrocław",
      what: "Nowe centrum usług IT",
      scale: "200 miejsc pracy",
      why: "Buduje zespół od zera",
      url: "https://example.com/c",
      published: "2026-10-01",
      match: null,
    },
    created_at: "2026-11-02T07:00:00Z",
    run_id: 4,
    owner: null,
    owner_in_sales: false,
    ...over,
  };
}

type QueryState = { isSuccess: boolean; isError: boolean; error: Error | null };

let leadList: LeadList;
let leadsState: QueryState;
let botResults: BotResults;
let resultsState: QueryState;
let latest: LatestSignalRun;
let canEdit = true;
const update = vi.fn();
const takeOver = vi.fn();
const createActivity = vi.fn();
const accept = vi.fn();
const reject = vi.fn();
const push = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/sales/leads",
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: { user: { id: number } }) => unknown) => select({ user: { id: 42 } }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useLeads: () => ({
    data: leadsState.isSuccess ? leadList : undefined,
    isLoading: false,
    isSuccess: leadsState.isSuccess,
    isError: leadsState.isError,
    error: leadsState.error,
    refetch: vi.fn(),
  }),
  useLatestSignalRun: () => ({ data: latest, isSuccess: true, isError: false }),
  useUpdateLead: () => ({ mutate: update, mutateAsync: update, isPending: false }),
  useTakeOverLead: () => ({ mutateAsync: takeOver, isPending: false }),
  useCreateActivity: () => ({ mutateAsync: createActivity, isPending: false }),
}));
vi.mock("@/lib/api/sales-bot-results", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-bot-results")>()),
  useBotResults: () => ({
    data: resultsState.isSuccess ? botResults : undefined,
    isLoading: false,
    isSuccess: resultsState.isSuccess,
    isError: resultsState.isError,
    error: resultsState.error,
    refetch: vi.fn(),
  }),
  useAcceptBotResult: () => ({ mutate: accept, isPending: false }),
  useRejectBotResult: () => ({ mutate: reject, isPending: false }),
}));

import { groupNewFirms, inBaseLine, NewFirmsInbox } from "../bot-modes/NewFirmsInbox";
import { groupWinBack, WinBackInbox, winBackPayload } from "../bot-modes/WinBackInbox";

beforeEach(() => {
  vi.clearAllMocks();
  canEdit = true;
  leadList = { items: [lead()], total: 1, counts: { new: 1, contacted: 0, converted: 0, dismissed: 0 }, bot_tasks_enabled: true };
  leadsState = { isSuccess: true, isError: false, error: null };
  botResults = { enabled: true, items: [result()] };
  resultsState = { isSuccess: true, isError: false, error: null };
  latest = { enabled: true, reject_reasons: ["Nieaktualne", "Inna firma"], run: null };
  takeOver.mockResolvedValue(lead({ assignee: { id: 42, name: "Ja" }, assignee_in_sales: true }));
  createActivity.mockResolvedValue({ id: 100 });
  update.mockResolvedValue(lead({ status: "contacted" }));
});

describe("Warto wrócić", () => {
  it("reads the lost deal from the payload and groups by status", () => {
    expect(winBackPayload(lead())).toEqual({
      lostOpportunityId: 55,
      lostTitle: "Wsparcie aplikacji",
      lostReason: "Klient zrezygnował z projektu",
      lostAt: "2026-04-08T10:00:00+00:00",
    });
    const groups = groupWinBack([
      lead({ id: 1 }),
      lead({ id: 2, status: "contacted" }),
      lead({ id: 3, status: "dismissed" }),
    ]);
    expect(groups.check.map((l) => l.id)).toEqual([1]);
    expect(groups.planned.map((l) => l.id)).toEqual([2]);
    expect(groups.rejected.map((l) => l.id)).toEqual([3]);
  });

  it("shows the lost deal, the change with its source and the bot's conclusion", () => {
    render(<WinBackInbox />);
    expect(screen.getByRole("link", { name: "Firma A" })).toHaveAttribute("href", "/sales/opportunities/55");
    expect(screen.getAllByText(/Klient zrezygnował z projektu/).length).toBeGreaterThan(0);
    expect(screen.getByText("Co się zmieniło")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /example\.com/ })).toHaveAttribute("href", "https://example.com/a");
    expect(screen.queryByText("wniosek bota, nie fakt")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zaplanuj powrót" })).toBeInTheDocument();
  });

  it("plans the return as a task for the owner and marks the lead", async () => {
    render(<WinBackInbox />);
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj powrót" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz zadanie" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ id: 1, status: "contacted" }));
    expect(takeOver).not.toHaveBeenCalled();
    expect(createActivity).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "task", company_id: 7, assignee_user_id: 3, subject: "Powrót: Nowy program chmurowy" }),
    );
  });

  it("without an owner in Sales takes the lead over first", async () => {
    leadList = { ...leadList, items: [lead({ assignee: { id: 3, name: "Były" }, assignee_in_sales: false })] };
    render(<WinBackInbox />);
    expect(screen.getByText(/nie pracuje już w Sprzedaży/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Przejmij i zaplanuj" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz zadanie" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(takeOver).toHaveBeenCalledWith(1);
    expect(createActivity.mock.calls[0][0].assignee_user_id).toBe(42);
  });

  it("dismisses with a reason from the bot's list", () => {
    render(<WinBackInbox />);
    fireEvent.click(screen.getByRole("button", { name: "Nie teraz" }));
    fireEvent.click(screen.getByRole("button", { name: "Inna firma" }));
    expect(update).toHaveBeenCalledWith(
      { id: 1, status: "dismissed", dismissed_reason: "Inna firma" },
      expect.anything(),
    );
  });

  it("a failed query is not an empty list", () => {
    leadsState = { isSuccess: false, isError: true, error: new Error("500") };
    render(<WinBackInbox />);
    expect(screen.queryByText("Pusto")).not.toBeInTheDocument();
    expect(screen.getByText(/Pozycje mogą istnieć/)).toBeInTheDocument();
  });

  it("view-only accounts see no actions", () => {
    canEdit = false;
    render(<WinBackInbox />);
    expect(screen.queryByRole("button", { name: "Zaplanuj powrót" })).not.toBeInTheDocument();
  });
});

describe("Nowe centra IT", () => {
  it("groups results and describes the card in NEXUS", () => {
    const groups = groupNewFirms([result({ id: 1 }), result({ id: 2, status: "accepted" }), result({ id: 3, status: "rejected" })]);
    expect([groups.open, groups.accepted, groups.rejected].map((g) => g.map((r) => r.id))).toEqual([[1], [2], [3]]);
    expect(inBaseLine(result())).toBe("Firmy nie ma w kartotece Sprzedaży.");
    expect(inBaseLine(result({ company: { id: 5, name: "Karta" }, owner: { id: 3, name: "Ola" }, owner_in_sales: true }))).toBe(
      "Karta Karta jest w kartotece, opiekun Ola.",
    );
    expect(inBaseLine(result({ company: { id: 5, name: "Karta" }, owner: { id: 3, name: "Ola" }, owner_in_sales: false }))).toMatch(
      /nie pracuje już w Sprzedaży/,
    );
  });

  it("creates the IT factories account and opens it", () => {
    accept.mockImplementation((_id: number, options: { onSuccess: (o: unknown) => void }) =>
      options.onSuccess({ opportunity_id: 77, company_id: 5, company_created: true, existed: false }),
    );
    render(<NewFirmsInbox />);
    expect(screen.getByText("Buduje zespół od zera")).toBeInTheDocument();
    expect(screen.queryByText("wniosek bota, nie fakt")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Załóż konto w Fabrykach IT" }));
    expect(accept).toHaveBeenCalledWith(9, expect.anything());
    expect(push).toHaveBeenCalledWith("/sales/opportunities/77");
  });

  it("rejects with a reason", () => {
    render(<NewFirmsInbox />);
    fireEvent.click(screen.getByRole("button", { name: "Nie teraz" }));
    fireEvent.click(screen.getByRole("button", { name: "Nieaktualne" }));
    expect(reject).toHaveBeenCalledWith({ id: 9, reason: "Nieaktualne" }, expect.anything());
  });

  it("a failed query and a disabled channel are not an empty list", () => {
    resultsState = { isSuccess: false, isError: true, error: new Error("500") };
    const { unmount } = render(<NewFirmsInbox />);
    expect(screen.queryByText("Pusto")).not.toBeInTheDocument();
    expect(screen.getByText(/Pozycje mogą istnieć/)).toBeInTheDocument();
    unmount();

    resultsState = { isSuccess: true, isError: false, error: null };
    botResults = { enabled: false, items: [] };
    render(<NewFirmsInbox />);
    expect(screen.getByText("Zadania bota są wyłączone.")).toBeInTheDocument();
  });
});
