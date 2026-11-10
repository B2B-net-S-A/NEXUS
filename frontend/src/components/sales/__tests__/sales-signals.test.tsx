/** Sygnały z bota researchu: skrzynka (G1), pas na karcie (G2), „Mój dzień” (G3), punkty do rozmowy. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CompanyBriefing, LatestSignalRun, Lead, LeadList, MyDay } from "@/lib/api/sales";

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: 1,
    source: "research",
    status: "new",
    title: "Połączenie spółek",
    summary: "Rejestracja w I kwartale",
    company_name: "Firma A",
    company_id: 7,
    url: "https://example.com/a",
    score: 60,
    signal_at: "2026-11-01T12:00:00Z",
    opportunity_id: null,
    dismissed_reason: null,
    created_at: "2026-11-09T07:00:00Z",
    payload: { origin: "grok", type: "restructuring", strength: "medium", why_now: "Integracja", domain: "example.com", published: "2026-11-01" },
    ...over,
  };
}

let leadList: LeadList;
let leadsState: { isSuccess: boolean; isError: boolean; error: Error | null };
let latest: LatestSignalRun;
let briefing: CompanyBriefing | undefined;
let briefingOk = true;
const update = vi.fn();
const convert = vi.fn();
const push = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/sales/leads",
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => true,
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
  useCompanyBriefing: () => ({ data: briefing, isSuccess: briefingOk, isError: !briefingOk }),
  useCompanyPeople: () => ({
    data: {
      counts: { current: 2, past: 0, via_us: 0, unknown: 0 },
      people: [{ candidate_id: 5, name: "Ewa", lastname: "Testowa", relationship: "current", title: "Tester" }],
    },
    isLoading: false,
    isError: false,
    isSuccess: true,
  }),
  useUpdateLead: () => ({ mutate: update, isPending: false }),
  useConvertLead: () => ({ mutate: convert, isPending: false }),
}));

import { groupSignals, SignalsInbox } from "../signals/SignalsInbox";
import { SignalStrip } from "../signals/SignalStrip";
import { TalkingPoints } from "../signals/TalkingPoints";
import { MyDaySignals } from "../signals/MyDaySignals";
import { dayLine, isDayEmpty } from "../my-day";

beforeEach(() => {
  vi.clearAllMocks();
  leadList = { items: [lead()], total: 1, counts: { new: 1, contacted: 0, converted: 0, dismissed: 0 }, signals_enabled: true };
  leadsState = { isSuccess: true, isError: false, error: null };
  latest = {
    enabled: true,
    reject_reasons: ["Nieaktualne", "Inna firma"],
    run: {
      id: 3,
      kind: "signals",
      status: "received",
      started_at: "2026-11-16T06:00:00Z",
      received_at: "2026-11-16T06:20:00Z",
      company_count: 20,
      report: { checked_firms: 20, by_strength: { medium: 4, weak: 7 }, quiet: ["Cisza"], dropped: {} },
      error: null,
    },
  };
  briefing = {
    enabled: true,
    briefing: {
      mode: "first_call",
      points: [{ text: "Nowy dyrektor IT", url: "https://example.com/cto", published: "2026-11-02" }],
      generated_at: "2026-11-09T07:00:00Z",
    },
  };
  briefingOk = true;
});

describe("groupSignals", () => {
  it("puts weak signals apart and dismissed ones under rejected", () => {
    const groups = groupSignals([
      lead({ id: 1 }),
      lead({ id: 2, payload: { strength: "weak" } }),
      lead({ id: 3, status: "dismissed", dismissed_reason: "Inna firma" }),
      lead({ id: 4, status: "contacted", payload: { strength: "strong" } }),
    ]);
    expect(groups.check.map((l) => l.id)).toEqual([1, 4]);
    expect(groups.weak.map((l) => l.id)).toEqual([2]);
    expect(groups.rejected.map((l) => l.id)).toEqual([3]);
    expect(groups.all).toHaveLength(4);
  });
});

describe("SignalsInbox", () => {
  it("shows the run line, the signal panel and the bot-inference label", () => {
    render(<SignalsInbox />);
    expect(screen.getByText(/20 firm sprawdzonych, 4 warte sprawdzenia, 7 słabych, 1 bez sygnału/)).toBeInTheDocument();
    expect(screen.getByText(/Do sprawdzenia \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Wniosek bota, nie fakt")).toBeInTheDocument();
    expect(screen.getByText("Ewa Testowa")).toBeInTheDocument();
    expect(screen.getByText("Nowy dyrektor IT")).toBeInTheDocument();
  });

  it("rejects with a reason from the server", () => {
    render(<SignalsInbox />);
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć" }));
    fireEvent.click(screen.getByRole("button", { name: "Inna firma" }));
    expect(update).toHaveBeenCalledWith(
      { id: 1, status: "dismissed", dismissed_reason: "Inna firma" },
      expect.anything(),
    );
  });

  it("shows an error, not an empty inbox, when leads fail", () => {
    leadsState = { isSuccess: false, isError: true, error: new Error("500") };
    render(<SignalsInbox />);
    expect(screen.queryByText("Pusto")).not.toBeInTheDocument();
    expect(screen.getByText(/Nie udało się pobrać sygnałów/)).toBeInTheDocument();
  });

  it("opens the full bot report", () => {
    render(<SignalsInbox />);
    fireEvent.click(screen.getByRole("button", { name: "Cały raport" }));
    const report = screen.getByRole("heading", { name: "Raport bota" }).closest("div")!.parentElement!;
    expect(within(report).getByText("Cisza")).toBeInTheDocument();
  });
});

describe("SignalStrip", () => {
  it("is absent when the channel is off", () => {
    leadList = { ...leadList, signals_enabled: false };
    const { container } = render(<SignalStrip companyId={7} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the newest signal with actions", () => {
    render(<SignalStrip companyId={7} />);
    expect(screen.getByText("Nowy sygnał")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Załóż szansę" })).toBeInTheDocument();
  });
});

describe("TalkingPoints", () => {
  it("lists points with the mode and a safe source link", () => {
    render(<TalkingPoints companyId={7} />);
    expect(screen.getByText(/Punkty do rozmowy na pierwszą rozmowę/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /źródło/ })).toHaveAttribute("href", "https://example.com/cto");
  });

  it("drops non-http links and renders nothing when the channel is off or failed", () => {
    briefing = {
      enabled: true,
      briefing: { mode: "ongoing", points: [{ text: "Punkt", url: "javascript:alert(1)", published: null }], generated_at: "2026-11-09T07:00:00Z" },
    };
    const { unmount } = render(<TalkingPoints companyId={7} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    unmount();
    briefing = { enabled: false, briefing: null };
    const off = render(<TalkingPoints companyId={7} showEmpty />);
    expect(off.container).toBeEmptyDOMElement();
    off.unmount();
    briefingOk = false;
    const failed = render(<TalkingPoints companyId={7} showEmpty />);
    expect(failed.container).toBeEmptyDOMElement();
  });
});

describe("Mój dzień", () => {
  const signal = { lead_id: 1, company: { id: 7, name: "Firma A" }, title: "Program AI", strength: "weak" as const, type: null, signal_at: null };

  it("marks a weak signal so it does not read as a task", () => {
    render(<MyDaySignals signals={[signal]} />);
    expect(screen.getByText("Nowe sygnały")).toBeInTheDocument();
    expect(screen.getByText("Słaby, do wzmianki w rozmowie")).toBeInTheDocument();
  });

  it("counts signals in the day line and in emptiness", () => {
    const day = {
      today: "2026-11-16",
      counts: { meetings: 0, reply: 0, overdue: 0, offers: 0, older_tasks: 0, signals: 2 },
      meetings: [],
      reply: [],
      overdue: [],
      offers: [],
      prep: null,
      signals: [signal, { ...signal, lead_id: 2 }],
    } satisfies MyDay;
    expect(dayLine(day)).toMatch(/2 sygnały$/);
    expect(isDayEmpty(day)).toBe(false);
    expect(isDayEmpty({ ...day, signals: [] })).toBe(true);
  });
});
