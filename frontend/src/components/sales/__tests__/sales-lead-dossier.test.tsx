/** Teczka leada: blok przy leadzie (firma, znamy, decydenci, punkty), raz na firmę. */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Lead, LeadDossier as Dossier, LeadList } from "@/lib/api/sales";

function dossier(over: Partial<Dossier> = {}): Dossier {
  return {
    company_id: 7,
    industry: "Bankowość",
    city: "Warszawa",
    nip: "5261021021",
    website: "example.pl",
    known: 9,
    known_with_email: 6,
    owner: "Opiekun Testowy",
    decision_makers: ["Prezes Zarządu", "CTO", "Dyrektor IT"],
    points: 3,
    points_at: "2026-11-12T07:00:00Z",
    ...over,
  };
}

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
    payload: {},
    assignee: null,
    assignee_in_sales: false,
    dossier: dossier(),
    ...over,
  };
}

type QueryState = { isSuccess: boolean; isError: boolean; error: Error | null };

let leadList: LeadList;
let leadsState: QueryState;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/sales/leads",
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => true,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: { user: { id: number } }) => unknown) => select({ user: { id: 42 } }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn() }),
}));
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
  useConvertLead: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateLead: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateLead: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { firstLeadOfCompany, formatNip, LeadDossier } from "../LeadDossier";
import { LeadsView } from "../LeadsView";

beforeEach(() => {
  leadList = {
    items: [lead()],
    total: 1,
    counts: { new: 1, contacted: 0, converted: 0, dismissed: 0 },
    signals_enabled: false,
    bot_tasks_enabled: false,
  };
  leadsState = { isSuccess: true, isError: false, error: null };
});

describe("LeadDossier", () => {
  it("shows the company, who we know, decision makers and points with a link to the card", () => {
    render(<LeadDossier dossier={dossier()} />);
    expect(screen.getByText("Bankowość · Warszawa · NIP 526-102-10-21 · example.pl")).toBeInTheDocument();
    expect(screen.getByText("9 osób, 6 z e-mailem · opiekun Opiekun Testowy")).toBeInTheDocument();
    expect(screen.getByText("Prezes Zarządu, CTO, Dyrektor IT")).toBeInTheDocument();
    expect(screen.getByText(/3 punkty/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "karta firmy" })).toHaveAttribute("href", "/sales/companies/7");
    expect(screen.queryByText(/bot|wniosek|sprawdź/i)).not.toBeInTheDocument();
  });

  it("skips empty lines and draws nothing without data", () => {
    const { rerender, container } = render(
      <LeadDossier
        dossier={dossier({ industry: null, city: null, nip: null, website: null, decision_makers: [], points: 0, known: 1, known_with_email: 0, owner: null })}
      />,
    );
    expect(screen.getByText("1 osoba, 0 z e-mailem")).toBeInTheDocument();
    expect(screen.queryByText("Firma:")).not.toBeInTheDocument();
    expect(screen.queryByText("Na pierwszą rozmowę:")).not.toBeInTheDocument();
    rerender(<LeadDossier dossier={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(
      <LeadDossier
        dossier={dossier({ industry: null, city: null, nip: null, website: null, decision_makers: [], points: 0, known: 0, owner: null })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("formats a ten-digit NIP and leaves other values alone", () => {
    expect(formatNip("526 102 10 21")).toBe("526-102-10-21");
    expect(formatNip("DE123")).toBe("DE123");
  });

  it("marks only the first lead of each company", () => {
    const first = firstLeadOfCompany([
      { id: 1, company_id: 7 },
      { id: 2, company_id: 8 },
      { id: 3, company_id: 7 },
      { id: 4, company_id: null },
    ]);
    expect([...first]).toEqual([1, 2]);
  });
});

describe("Leady z teczką", () => {
  it("shows the dossier once per company and the source without a score", () => {
    leadList = {
      ...leadList,
      items: [lead({ id: 1 }), lead({ id: 2, title: "Druga wiadomość" }), lead({ id: 3, company_id: 9, dossier: null })],
    };
    render(<LeadsView />);
    expect(screen.getAllByTestId("lead-dossier")).toHaveLength(1);
    expect(screen.getAllByText(/Bot Leady/)).toHaveLength(3);
    expect(screen.queryByText(/ocena/)).not.toBeInTheDocument();
  });

  it("keeps the score for leads from other sources", () => {
    leadList = { ...leadList, items: [lead({ source: "atlas", score: 70, dossier: null })] };
    render(<LeadsView />);
    expect(screen.getByText(/Z Atlasa.*ocena 70/)).toBeInTheDocument();
  });

  it("a failed query is an error notice, not an empty list", () => {
    leadsState = { isSuccess: false, isError: true, error: new Error("500") };
    render(<LeadsView />);
    expect(screen.queryByTestId("lead-dossier")).not.toBeInTheDocument();
    expect(screen.queryByText("Brak nowych leadów")).not.toBeInTheDocument();
  });
});
