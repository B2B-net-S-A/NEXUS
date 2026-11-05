/**
 * Zespół: odpowiedź, soczewka etapu i to, czego nie widzi rola bez wglądu w osoby
 * (05.11.2026). Reguły liczb są w `lib/__tests__/insights-team-view.test.ts`.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), search: "" }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));
class ResizeObserverStub {
  observe() {}
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

import { ZespolView } from "../ZespolView";
import { useAuthStore } from "@/store/auth";

const PERIOD = {
  kind: "month",
  start: "2026-10-01T00:00:00+02:00",
  end: "2026-11-01T00:00:00+01:00",
  timezone: "Europe/Warsaw",
};

const STAGES = [
  ["verified", 730],
  ["cv_sent", 647],
  ["client_interview", 114],
  ["acceptance", 27],
  ["hired", 26],
].map(([stage, count]) => ({ stage, label: stage, count, counted_from: null }));

const RESPONSES: Record<string, unknown> = {
  "/api/insights/recruitment/funnel": { period: PERIOD, stages: STAGES, conversions: [], coverage: {} },
  "/api/insights/recruitment/team-goals": {
    company_month_placements: 1,
    goals: [{ goal_id: "team_monthly_placements", target: 36, current: 1, expected: 6, period: "month", unit: "count" }],
  },
  "/api/insights/recruitment/in-flight": {
    stale_days: 10,
    columns: [{ column: "cv_sent", label: "", count: 675, stale_count: 453, oldest_days: 174 }],
    acceptances: [],
    forecast: { open: 0, hired: 0, resolved: 0, min_sample: 10, since: "2026-10-12", rate_pct: null, low: null, high: null },
    definitions: {},
  },
  "/api/insights/recruitment/weekly-trend": {
    weeks: [{ week_start: "2026-10-26", partial: false, counts: { verified: 206, cv_sent: 177, client_interview: 38, acceptance: 9, hired: 7 } }],
  },
  "/api/insights/team/attention": {
    items: [
      { kind: "stale_postings", count: 28, label: "zgłoszeń czeka", report: null },
      { kind: "dl_send_stale", count: 26, label: "CV czeka na wysyłkę", report: null, href: "/jobs?open=1&tosend=stale" },
    ],
  },
  "/api/insights/team/people": {
    period: PERIOD,
    workdays: 22,
    low_precision_pct: 50,
    precision_target_pct: 75,
    rows: [
      { user_id: 1, name: "Anna Test", role: "recruiter", is_active: true, verifications: 70, recommendations: 60, interviews: 9, acceptances: 5, placements: 19, placements_target: 36, in_flight: 80, previous_placements: 0, verifications_per_workday: 3, precision_pct: 80 },
    ],
    totals: { verifications: 0, recommendations: 0, interviews: 0, placements: 0, precision_pct: null, people: 1, unattributed: 0 },
    previous_totals: { verifications: 0, recommendations: 0, interviews: 0, placements: 0 },
  },
  "/api/insights/performance-flags": { flags_by_user: {}, types: [] },
};

function renderView() {
  mocks.get.mockImplementation((url: string) =>
    url in RESPONSES ? Promise.resolve({ data: RESPONSES[url] }) : new Promise(() => {}),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ZespolView />
    </QueryClientProvider>,
  );
}

function setUser(role: string, capabilities: string[]) {
  useAuthStore.setState({ user: { id: 99, role, roles: [role], analytics_capabilities: capabilities } } as never);
}

describe("Zespół: odpowiedź i soczewka", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.search = "";
  });

  it("lider widzi zdanie z odpowiedzią, a zdanie o zatorze otwiera właściwy etap", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    renderView();
    const stall = await screen.findByRole("link", { name: /Dziś najwięcej stoi u klientów: 453 z 675/ });
    expect(stall.getAttribute("href")).toContain("etap=cv_sent");
    expect(await screen.findByRole("heading", { level: 2, name: /19 u osób z celem 36\. Do celu zabrakło 17/ })).toBeTruthy();
  });

  it("sygnał bez listy nie jest linkiem do tabeli, w której go nie ma", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    renderView();
    const send = await screen.findByText("CV czeka na wysyłkę");
    expect(send.closest("a")?.getAttribute("href")).toBe("/jobs?open=1&tosend=stale");
    expect(screen.getByText("zgłoszeń czeka").closest("a")).toBeNull();
  });

  it("start na „Całym lejku”, a `etap` w adresie otwiera etap z osobami", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    const first = renderView();
    const whole = await screen.findByRole("tab", { name: /Cały lejek/ });
    expect(whole.getAttribute("aria-selected")).toBe("true");
    first.unmount();

    mocks.search = "etap=cv_sent";
    renderView();
    const tab = await screen.findByRole("tab", { name: /Rekomendacje/ });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    // Osoba stoi przy etapie i w mapie osób: oba miejsca otwierają tę samą listę.
    const list = await screen.findAllByRole("button", { name: "Anna Test · Rekomendacje: 60. Pokaż osoby" });
    expect(list).toHaveLength(2);
  });

  it("rola bez wglądu w osoby nie pyta o osoby i sygnały, ani ich nie widzi", async () => {
    setUser("recruiter", []);
    mocks.search = "etap=cv_sent";
    renderView();
    await screen.findByRole("tab", { name: /Rekomendacje/ });
    const urls = mocks.get.mock.calls.map(([url]) => url);
    expect(urls).not.toContain("/api/insights/team/people");
    expect(urls).not.toContain("/api/insights/team/attention");
    expect(screen.queryByText("Najpierw to")).toBeNull();
    expect(screen.queryByText("Kto ma ten etap w okresie")).toBeNull();
    expect(screen.getByText(/Wyniki poszczególnych osób widzą liderzy zespołu/)).toBeTruthy();
  });

  it("awaria lejka nie wygląda jak pusta zakładka", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    mocks.get.mockImplementation((url: string) =>
      url === "/api/insights/recruitment/funnel"
        ? Promise.reject(new Error("500"))
        : url in RESPONSES
          ? Promise.resolve({ data: RESPONSES[url] })
          : new Promise(() => {}),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ZespolView />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów|ponownie/i })).toBeTruthy();
    // Pasek okresu zostaje: przy awarii jednego okresu trzeba móc przejść na inny.
    expect(screen.getByRole("group", { name: "Granulacja okresu" })).toBeTruthy();
  });

  it("awaria stanu na dziś ma komunikat, a nie znika po cichu", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    mocks.get.mockImplementation((url: string) =>
      url === "/api/insights/recruitment/in-flight"
        ? Promise.reject(new Error("500"))
        : url in RESPONSES
          ? Promise.resolve({ data: RESPONSES[url] })
          : new Promise(() => {}),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ZespolView />
      </QueryClientProvider>,
    );
    expect((await screen.findAllByRole("button", { name: /Spróbuj|Ponów|ponownie/i })).length).toBeGreaterThan(0);
  });

  it("cele w trakcie ładowania nie rysują zer", async () => {
    setUser("head_of_recruitment", ["view_team_kpi"]);
    mocks.get.mockImplementation((url: string) =>
      url === "/api/insights/recruitment/team-goals"
        ? new Promise(() => {})
        : url in RESPONSES
          ? Promise.resolve({ data: RESPONSES[url] })
          : new Promise(() => {}),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ZespolView />
      </QueryClientProvider>,
    );
    await screen.findByRole("tab", { name: /Cały lejek/ });
    expect(screen.queryByText("30 dni")).toBeNull();
    expect(screen.getByRole("group", { name: "Granulacja okresu" })).toBeTruthy();
  });

  it("Rada bez sekcji Pipeline nie dostaje linku do rekrutacji", async () => {
    useAuthStore.setState({
      user: { id: 99, role: "board", roles: ["board"], analytics_capabilities: ["view_team_kpi"], section_access: { pipeline: false } },
    } as never);
    renderView();
    const send = await screen.findByText("CV czeka na wysyłkę");
    expect(send.closest("a")).toBeNull();
  });

  it("Delivery Lead: klik w osobę w soczewce przełącza na tabelę z listą", async () => {
    setUser("delivery_lead", ["view_team_kpi"]);
    mocks.search = "etap=cv_sent&kto=rekomendacje&osoba=1";
    renderView();
    expect(await screen.findByRole("heading", { name: /Kto się liczy · Anna Test/ })).toBeTruthy();
  });
});
