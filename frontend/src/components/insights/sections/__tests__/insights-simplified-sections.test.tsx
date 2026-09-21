/**
 * Nowe sekcje uproszczonego Insights (21.09.2026): tablica ścieżki rozwoju,
 * macierz kompetencji i portfele Delivery Leadów.
 *
 * Wspólna reguła, której pilnują: `null` / brak danych to NIE jest zero,
 * a filtr „Tylko z uwagami" nie może udawać pustej bazy.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import {
  SeniorityBoard,
  progressCaption,
} from "@/components/insights/sections/SeniorityBoard";
import {
  CompetenceMatrix,
  heatLevel,
} from "@/components/insights/sections/CompetenceMatrix";
import {
  InsightsDlPortfolio,
  filterLeadsWithAlerts,
} from "@/components/insights/sections/InsightsDlPortfolio";
import { buildDlPortfolioCsvExport } from "@/lib/insights-csv";
import type {
  InsightsDlPortfolioClient,
  InsightsDlPortfolioLead,
  InsightsDlPortfolioResponse,
  SeniorityEntry,
} from "@/lib/insights-api";

function respond(map: Record<string, unknown>) {
  mocks.get.mockImplementation((url: string) => {
    if (!(url in map)) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    return Promise.resolve({ data: map[url] });
  });
}

function renderSection(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

const entry = (patch: Partial<SeniorityEntry>): SeniorityEntry => ({
  user_id: 1,
  name: "Anna Nowak",
  role: "recruiter",
  level: "junior",
  total_placements: 3,
  first_placement_month: "2026-01",
  placements_in_senior_window: 3,
  placements_in_expert_window: 0,
  placements_to_next_level: 3,
  progress_pct: 50,
  senior_since: null,
  expert_since: null,
  ...patch,
});

describe("SeniorityBoard", () => {
  it("podpis postępu odróżnia brak placementów od „0 z 6”", () => {
    expect(progressCaption(entry({ first_placement_month: null }))).toBe(
      "Brak przypisanych placementów",
    );
    expect(progressCaption(entry({}))).toBe("Do Seniora: brakuje 3 placementów");
    expect(progressCaption(entry({ placements_to_next_level: 1 }))).toBe(
      "Do Seniora: brakuje 1 placementu",
    );
    expect(
      progressCaption(entry({ level: "senior", placements_to_next_level: 4 })),
    ).toBe("Do Experta: brakuje 4 placementów");
    expect(
      progressCaption(entry({ level: "expert", expert_since: "2026-03" })),
    ).toBe("Expert od 2026-03");
  });

  it("rozkłada osoby na trzy kolumny poziomów", async () => {
    respond({
      "/api/insights/recruitment/seniority": {
        as_of: "2026-09-21",
        thresholds: {},
        window: {},
        entries: [
          entry({ user_id: 1, name: "Anna Nowak" }),
          entry({ user_id: 2, name: "Jan Kowal", level: "senior" }),
          entry({ user_id: 3, name: "Ewa Lis", level: "expert" }),
        ],
        totals: { users: 3, levels: { junior: 1, senior: 1, expert: 1 } },
        coverage: {},
      },
    });
    renderSection(<SeniorityBoard />);
    const junior = await screen.findByTestId("seniority-column-junior");
    expect(within(junior).getByText("Anna Nowak")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("seniority-column-senior")).getByText("Jan Kowal"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("seniority-column-expert")).getByText("Ewa Lis"),
    ).toBeInTheDocument();
  });
});

describe("CompetenceMatrix", () => {
  it("zero zawsze najjaśniejsze, reszta względem maksimum", () => {
    expect(heatLevel(0, 100)).toBe(0);
    expect(heatLevel(5, 0)).toBe(0);
    expect(heatLevel(5, 100)).toBe(1);
    expect(heatLevel(20, 100)).toBe(2);
    expect(heatLevel(50, 100)).toBe(3);
    expect(heatLevel(100, 100)).toBe(4);
  });

  it("renderuje kategorie i liczbę otwartych rekrutacji", async () => {
    const counts = { new: 10, screening: 5, cv_sent: 2, client_interview: 1, acceptance: 0 };
    respond({
      "/api/insights/recruitment/competence-matrix": {
        as_of: "2026-09-21",
        stages: [
          { key: "new", label: "Nowy" },
          { key: "screening", label: "Screening" },
          { key: "cv_sent", label: "Wysłany do klienta" },
          { key: "client_interview", label: "Interview" },
          { key: "acceptance", label: "Akceptacje" },
        ],
        categories: [
          { category_id: 1, name: "Data & AI", open_jobs: 7, stage_counts: counts },
          { category_id: null, name: "Bez kategorii", open_jobs: 2, stage_counts: counts },
        ],
        totals: { open_jobs: 9, stage_counts: counts },
      },
    });
    renderSection(<CompetenceMatrix />);
    expect(await screen.findByText("Data & AI")).toBeInTheDocument();
    expect(screen.getByText("Bez kategorii")).toBeInTheDocument();
    expect(screen.getByText("Wysłany do klienta")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });
});

const client = (patch: Partial<InsightsDlPortfolioClient>): InsightsDlPortfolioClient => ({
  client_id: 1,
  client_name: "Klient A",
  requests: 10,
  vacancies: 12,
  placements: 4,
  hit_ratio: 40,
  fill_rate: 33.3,
  open_jobs: 3,
  monthly_placements: [
    { month: "2026-04", placements: 1 },
    { month: "2026-05", placements: 0 },
    { month: "2026-06", placements: 1 },
    { month: "2026-07", placements: 0 },
    { month: "2026-08", placements: 1 },
    { month: "2026-09", placements: 1 },
  ],
  top_hiring_manager: { contact_id: 9, name: "Hanna Menedżer", title: "CTO", jobs: 5 },
  prev_hit_ratio: 45,
  delta_pp: -5,
  alert: null,
  ...patch,
});

const lead = (patch: Partial<InsightsDlPortfolioLead>): InsightsDlPortfolioLead => ({
  dl_id: 1,
  dl_name: "Delia Lead",
  is_active: true,
  requests: 10,
  vacancies: 12,
  placements: 4,
  hit_ratio: 40,
  fill_rate: 33.3,
  open_requests: 3,
  target_achieved: true,
  clients: [client({})],
  ...patch,
});

const portfolio = (leads: InsightsDlPortfolioLead[]): InsightsDlPortfolioResponse => ({
  period: {
    kind: "year",
    date_from: "2026-01-01",
    date_to: "2026-12-31",
    label: "2026",
    offset: 0,
  } as unknown as InsightsDlPortfolioResponse["period"],
  hit_ratio_target_pct: 30,
  leads,
  unattributed: { requests: 2, placements: 1 },
});

describe("InsightsDlPortfolio", () => {
  it("filtr uwag zostawia wyłącznie DL-e z klientem wymagającym uwagi", () => {
    const leads = [
      lead({ dl_id: 1, clients: [client({ alert: "hit_ratio_drop", delta_pp: -26 }), client({ client_id: 2 })] }),
      lead({ dl_id: 2, clients: [client({ client_id: 3 })] }),
    ];
    const filtered = filterLeadsWithAlerts(leads);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].clients).toHaveLength(1);
    expect(filtered[0].clients[0].alert).toBe("hit_ratio_drop");
  });

  it("DL jest nagłówkiem grupy, pod nim jego klienci; brak uwag to komunikat, nie pustka", async () => {
    respond({
      "/api/insights/delivery-leads/portfolio": portfolio([
        lead({ clients: [client({ hit_ratio: null })] }),
      ]),
    });
    renderSection(<InsightsDlPortfolio period={{ period: "year", offset: 0 }} />);
    expect(await screen.findByText("Delia Lead")).toBeInTheDocument();
    expect(screen.getByText("Klient A")).toBeInTheDocument();
    expect(screen.getByText("Hanna Menedżer")).toBeInTheDocument();
    // hit ratio `null` = „—”, nigdy „0%”.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText(/Bez przypisanego DL: 2 zapytań/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Tylko z uwagami/ }));
    expect(screen.getByText("Żaden klient nie wymaga teraz uwagi.")).toBeInTheDocument();
  });

  it("alert spadku pokazuje zmianę w punktach procentowych", async () => {
    respond({
      "/api/insights/delivery-leads/portfolio": portfolio([
        lead({ clients: [client({ alert: "hit_ratio_drop", delta_pp: -26 })] }),
      ]),
    });
    renderSection(<InsightsDlPortfolio period={{ period: "year", offset: 0 }} />);
    expect(await screen.findByText(/hit ratio -26 pp/)).toBeInTheDocument();
  });

  it("eksport CSV niesie wiersz DL, klientów i wiersz bez przypisanego DL", () => {
    const csv = buildDlPortfolioCsvExport(portfolio([lead({})]));
    expect(csv?.rows.map((r) => r[1])).toEqual(["(razem DL)", "Klient A", ""]);
    expect(csv?.rows[csv.rows.length - 1][0]).toBe("Bez przypisanego DL");
    expect(buildDlPortfolioCsvExport(undefined)).toBeNull();
  });
});
