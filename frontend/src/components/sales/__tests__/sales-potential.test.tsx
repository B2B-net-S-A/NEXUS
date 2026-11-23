/** Ocena potencjału (23.11.2026): stany zakładki, skrót w „Moim dniu”, uwagi bazy wiedzy. Dane fikcyjne. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeReference, Potential } from "@/lib/api/sales-potential";

type QueryState<T> = {
  data?: T;
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
  error?: unknown;
  refetch: () => void;
};

const refetch = vi.fn();
const start = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };
let potentialQuery: QueryState<Potential>;

function ok<T>(data: T): QueryState<T> {
  return { data, isLoading: false, isError: false, isSuccess: true, refetch };
}

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales-potential", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-potential")>()),
  useCompanyPotential: () => potentialQuery,
  useStartPotential: () => ({ mutate: start, isPending: false }),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCompanyPeople: () => ok({ counts: { current: 1, via_us: 0, past: 2, unknown: 0 }, people: [] }),
}));
vi.mock("@/lib/api/sales-bot-people", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-bot-people")>()),
  useCompanyDecisionMap: () => ok({ enabled: true, company_id: 7, can_start: false, running: false, people: [] }),
}));

import { referenceWarning } from "../potential/KnowledgeBaseView";
import { eventDate, failureText, potentialView, wordCount } from "../potential/potential-format";
import { PotentialTab } from "../potential/PotentialTab";
import { PrepPotential } from "../potential/PrepPotential";

const LINES = { security: "Cyberbezpieczeństwo", elevate: "Dynaminds Elevate" };

function reference(over: Partial<KnowledgeReference> = {}): KnowledgeReference {
  return {
    id: "aaaa1111",
    client: "Fikcyjny Bank Omega",
    kind: "list",
    sectors: ["bankowość"],
    services: [],
    scope: "Body leasing IT",
    since: "2019",
    letter_date: "2026-05-28",
    valid_until: null,
    signed_by: "",
    quote: "",
    public_tender: false,
    note: "",
    fresh: true,
    nexus_active: 4,
    ...over,
  };
}

const READY: Potential = {
  enabled: true,
  lines: LINES,
  run: { id: 9, status: "received", started_at: "2026-11-23T08:00:00Z" },
  result: {
    id: 3,
    state: "ready",
    error: null,
    created_at: "2026-11-23T08:05:00Z",
    assessed_at: "2026-11-23T08:06:00Z",
    research: {
      pkd: "21.20.Z",
      employees: "250-999",
      events: [{ date: "2026-03", text: "Rozbudowa zakładu", url: "https://example.com/r", line: "security" }],
      jobs: [],
      stack: [],
    },
    ksc: { result: "PRAWDOPODOBNIE TAK", entity: "kluczowy", sector: "zdrowie", why: "PKD 21.20.Z." },
    assessment: {
      verdict: "ŚREDNI",
      summary: "Zakład w rozbudowie. Termin KSC blisko. Trzecie zdanie.",
      land: { title: "Diagnoza KSC", why: "Stała cena." },
      expand: ["Pentest OT"],
      fit: [{ line: "security", score: 4, need: "KSC", service: "Diagnoza", horizon: "teraz" }],
      references: [{ id: "aaaa1111", why: "Regulowany." }],
      questions: [
        { group: "Bezpieczeństwo", text: "Kto prowadzi KSC?" },
        { group: "IT i zespół", text: "Gdzie zapadają decyzje IT?" },
      ],
      verify: ["IT jest w centrali."],
      risks: [],
      opening: "Dzień dobry, rozmowa 30 minut?",
    },
    references: [{ reference: reference(), why: "Regulowany." }],
  },
};

function withClient(node: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  start.mockReset();
  potentialQuery = ok(READY);
});

describe("potentialView", () => {
  it("reads every state of the run and the result", () => {
    expect(potentialView(undefined)).toBe("off");
    expect(potentialView({ ...READY, enabled: false })).toBe("off");
    expect(potentialView({ ...READY, run: null, result: null })).toBe("empty");
    expect(potentialView({ ...READY, run: { id: 1, status: "started", started_at: "2026-11-23T09:00:00Z" } })).toBe(
      "running",
    );
    expect(potentialView({ ...READY, run: { id: 1, status: "expired", started_at: "x" }, result: null })).toBe("failed");
    expect(potentialView({ ...READY, result: { ...READY.result!, state: "pending", assessment: null } })).toBe(
      "assessing",
    );
    expect(potentialView({ ...READY, result: { ...READY.result!, state: "failed", assessment: null } })).toBe("failed");
    expect(potentialView(READY)).toBe("ready");
  });

  it("explains failures in plain words and formats dates", () => {
    const empty = { ...READY, result: { ...READY.result!, state: "failed" as const, error: "no_knowledge", assessment: null } };
    expect(failureText(empty)).toContain("Baza wiedzy jest pusta");
    expect(eventDate("2026-03")).toBe("03.2026");
    expect(eventDate("2026-03-14")).toBe("14.03.2026");
    expect(wordCount(" Dzień dobry, rozmowa ")).toBe(3);
  });
});

describe("PotentialTab", () => {
  it("shows the verdict, sourced events, picked references and questions", () => {
    render(withClient(<PotentialTab companyId={7} canEdit archived={false} />));
    expect(screen.getByText("ŚREDNI")).toBeInTheDocument();
    expect(screen.getByText("Diagnoza KSC")).toBeInTheDocument();
    expect(screen.getByText("Rozbudowa zakładu")).toBeInTheDocument();
    expect(screen.getByText("Fikcyjny Bank Omega")).toBeInTheDocument();
    expect(screen.getByText("Kto prowadzi KSC?")).toBeInTheDocument();
    expect(screen.getByText(/podmiot kluczowy/)).toBeInTheDocument();
    expect(screen.getByText(/teraz 1 · przez nas 0 · kiedyś 2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Odśwież" }));
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("offers the button when there is no assessment and hides it for view-only accounts", () => {
    potentialQuery = ok({ ...READY, run: null, result: null });
    const { rerender } = render(withClient(<PotentialTab companyId={7} canEdit archived={false} />));
    expect(screen.getByRole("button", { name: "Oceń potencjał" })).toBeInTheDocument();
    rerender(withClient(<PotentialTab companyId={7} canEdit={false} archived={false} />));
    expect(screen.queryByRole("button", { name: "Oceń potencjał" })).not.toBeInTheDocument();
  });

  it("says the bot is working instead of showing an empty tab", () => {
    potentialQuery = ok({ ...READY, run: { id: 10, status: "started", started_at: "2026-11-23T10:00:00Z" } });
    render(withClient(<PotentialTab companyId={7} canEdit archived={false} />));
    expect(screen.getByText(/Bot zbiera dane o firmie/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odśwież" })).toBeDisabled();
  });

  it("shows a query failure as an error, not as an empty assessment", () => {
    potentialQuery = { isLoading: false, isError: true, isSuccess: false, error: new Error("boom"), refetch };
    render(withClient(<PotentialTab companyId={7} canEdit archived={false} />));
    expect(screen.queryByText("Ta firma nie ma jeszcze oceny potencjału.")).not.toBeInTheDocument();
  });
});

describe("PrepPotential", () => {
  it("shows a short version with two sentences and three questions", () => {
    render(withClient(<PrepPotential companyId={7} data={READY} />));
    expect(screen.getByText("Zakład w rozbudowie. Termin KSC blisko.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pełna ocena" })).toHaveAttribute("href", "/sales/companies/7?tab=potential");
    expect(screen.getByText("Fikcyjny Bank Omega")).toBeInTheDocument();
  });

  it("falls back to sourced events when the model gave no assessment", () => {
    render(withClient(<PrepPotential companyId={7} data={{ ...READY, result: { ...READY.result!, assessment: null } }} />));
    expect(screen.getByText("Co się dzieje w firmie")).toBeInTheDocument();
    expect(screen.getByText(/Rozbudowa zakładu/)).toBeInTheDocument();
  });

  it("draws nothing without research or assessment", () => {
    const bare = { ...READY, result: { ...READY.result!, assessment: null, research: {} } };
    const { container } = render(withClient(<PrepPotential companyId={7} data={bare} />));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("referenceWarning", () => {
  it("flags stale letters and references missing from NEXUS", () => {
    expect(referenceWarning(reference())).toBeNull();
    expect(referenceWarning(reference({ fresh: false }))).toContain("starszy niż rok");
    expect(referenceWarning(reference({ nexus_active: null }))).toContain("Nie znalazłem klienta");
    expect(referenceWarning(reference({ nexus_active: 0 }))).toContain("bez aktywnych kontraktów");
    expect(referenceWarning(reference({ kind: "logo", fresh: null, nexus_active: null }))).toBeNull();
    expect(referenceWarning(reference({ kind: "realizacja", fresh: null, nexus_active: null }))).toBeNull();
  });
});
