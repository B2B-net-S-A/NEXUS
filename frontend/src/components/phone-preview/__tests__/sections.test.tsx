import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgendaEntry } from "@/lib/interview-cycle";

import { CompanySection } from "../CompanySection";
import { todayAgenda } from "../TodaySection";
import { Loaded } from "../ui";

const board = vi.fn();
const flows = vi.fn();
const ranking = vi.fn();

vi.mock("@/lib/insights-api", async (original) => ({
  ...(await original<typeof import("@/lib/insights-api")>()),
  insightsBoardApi: {
    board: (...a: unknown[]) => board(...a),
    boardFlows: (...a: unknown[]) => flows(...a),
    clientsRanking: (...a: unknown[]) => ranking(...a),
  },
  insightsApi: { inFlight: () => Promise.resolve({ forecast: { open: 0, low: 0, high: 0 } }) },
}));

const delta = (change_pct: number | null) => ({ current: 1, previous: 1, delta: 0, change_pct });
const BOARD = {
  period: { kind: "quarter", start: "2026-10-01T00:00:00+02:00", end: "2027-01-01T00:00:00+01:00", timezone: "Europe/Warsaw" },
  kpis: {
    placements: 27,
    hit_ratio_pct: null,
    jobs_closed: 0,
    jobs_closed_with_placement: 0,
    finance: { revenue_monthly_pln: 14081664, margin_monthly_pln: 3190348, active_consultants: 494 },
  },
  trend: { months: [] },
  comparison: {
    placements: delta(-27),
    placements_previous_window: { same_stretch: true },
    revenue_monthly_pln: delta(5.4),
    margin_monthly_pln: delta(7.7),
    active_consultants: delta(null),
  },
  degraded: null,
};
const FLOWS = {
  window: { from: "2026-10-01", to: "2026-11-05" },
  consultants: { starts: 49, ends: 13, resignations: 3, net: 36 },
  ending_without_continuation: { days: 30, contracts: 50 },
  jobs: { open: 185, open_clients: 15 },
};
const RANKING = { clients: [{ client_id: 1, name: "Klient A", monthly_margin_total: 2047227 }] };

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  board.mockReset().mockResolvedValue(BOARD);
  flows.mockReset().mockResolvedValue(FLOWS);
  ranking.mockReset().mockResolvedValue(RANKING);
});

describe("CompanySection", () => {
  it("ukrywa kwoty i zostawia procenty oraz sztuki", async () => {
    wrap(<CompanySection hidden period="quarter" />);
    await screen.findByText("Przychód / mc");
    await screen.findByText("Klient A");
    expect(document.body.textContent).not.toContain("14,08 mln");
    expect(document.body.textContent).not.toContain("3,19 mln");
    expect(document.body.textContent).not.toContain("2,05 mln");
    expect(screen.getByText("494")).toBeInTheDocument();
    expect(screen.getByText(/5,4%/)).toBeInTheDocument();
  });

  it("po odkryciu pokazuje kwoty", async () => {
    wrap(<CompanySection hidden={false} period="quarter" />);
    expect(await screen.findByText("14,08 mln zł")).toBeInTheDocument();
    expect(await screen.findByText("2,05 mln zł")).toBeInTheDocument();
  });

  it("nie liczy po swojemu: „Odeszli” to `ends`, rezygnacje są ich częścią", async () => {
    wrap(<CompanySection hidden period="quarter" />);
    expect(await screen.findByText("−13")).toBeInTheDocument();
    expect(screen.getByText("+36")).toBeInTheDocument();
    expect(screen.getByText("rezygnacje 3")).toBeInTheDocument();
    expect(screen.queryByText("−16")).not.toBeInTheDocument();
  });

  it("brak mianownika to kreska, nie zero", async () => {
    wrap(<CompanySection hidden period="quarter" />);
    const label = await screen.findByText("Hit ratio (zamknięte)");
    expect(label.parentElement?.textContent).toContain("—");
    expect(label.parentElement?.textContent).not.toContain("0%");
  });

  it("awaria jednej sekcji nie wygląda jak zero, reszta się pokazuje", async () => {
    ranking.mockRejectedValue(new Error("boom"));
    wrap(<CompanySection hidden period="quarter" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Spróbuj ponownie");
    expect(await screen.findByText("494")).toBeInTheDocument();
  });

  it("zmiana okresu pyta serwer o nowy okres", async () => {
    const { rerender } = wrap(<CompanySection hidden period="quarter" />);
    await screen.findByText("494");
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CompanySection hidden period="year" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(board).toHaveBeenCalledWith({ period: "year" }));
  });
});

describe("Loaded", () => {
  function Probe({ fn }: { fn: () => Promise<number> }) {
    const q = useQuery({ queryKey: ["probe"], queryFn: fn });
    return <Loaded query={q}>{(n) => <span>wynik {n}</span>}</Loaded>;
  }

  it("po awarii ponawia zapytanie przyciskiem", async () => {
    const fn = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue(7);
    wrap(<Probe fn={fn} />);
    fireEvent.click(await screen.findByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByText("wynik 7")).toBeInTheDocument();
  });
});

describe("todayAgenda", () => {
  const at = (start: string, kind = "interview") => ({ start, kind }) as AgendaEntry;

  it("bierze dzień z kalendarza firmy, nie z UTC, i sortuje po godzinie", () => {
    const now = new Date("2026-11-05T10:00:00Z");
    const rows = todayAgenda(
      [at("2026-11-05T14:00:00Z"), at("2026-11-04T23:30:00Z"), at("2026-11-05T23:30:00Z"), at("2026-11-04T22:30:00Z")],
      now,
    );
    expect(rows.map((r) => r.start)).toEqual(["2026-11-04T23:30:00Z", "2026-11-05T14:00:00Z"]);
  });
});
