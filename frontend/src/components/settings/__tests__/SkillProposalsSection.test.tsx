import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SkillProposal, SkillProposalPage } from "@/lib/api";

const api = vi.hoisted(() => ({
  proposals: vi.fn(),
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
  acceptSureProposals: vi.fn(),
  list: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, skillsAdminApi: { ...actual.skillsAdminApi, ...api } };
});
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { SkillProposalsSection } from "../SkillProposalsSection";

function row(over: Partial<SkillProposal>): SkillProposal {
  return {
    id: 1,
    family_key: "excel",
    display_name: "Excel",
    names: [
      { name: "excel", count: 5000, cand: 4428 },
      { name: "ms excel", count: 800, cand: 721 },
    ],
    cand_count: 5149,
    cv_count: 300,
    job_count: 15,
    weight: 5749,
    decision: "new",
    canonical: "Microsoft Excel",
    target_skill_id: null,
    target_name: null,
    category: "tools",
    replacements: [],
    confidence: "high",
    review_note: null,
    status: "open",
    sure: true,
    ...over,
  };
}

function page(items: SkillProposal[]): SkillProposalPage {
  return {
    items,
    total: items.length,
    totals: { open: items.length, names: 9, sure: items.filter((i) => i.sure).length, by_decision: {} },
    computed_at: null,
    categories: ["tools", "practice"],
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SkillProposalsSection />
    </QueryClientProvider>,
  );
}

describe("SkillProposalsSection — propozycje do słownika (06.11.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pokazuje rodzinę zapisów, liczby, polską kategorię i uwagę przy roli", async () => {
    api.proposals.mockResolvedValue(
      page([
        row({}),
        row({
          id: 2,
          family_key: "teamleadership",
          display_name: "team leadership",
          names: [{ name: "team leadership", count: 2400 }],
          decision: "alias",
          canonical: "team lead",
          target_skill_id: 9,
          target_name: "Team Lead",
          category: "role_management",
          confidence: "low",
          review_note: "Wskazuje rolę „Team Lead”, nie umiejętność: tylko ręcznie",
          sure: false,
        }),
      ]),
    );
    renderSection();
    const rows = await screen.findAllByTestId("skill-proposal-row");
    expect(within(rows[0]).getByText("Microsoft Excel")).toBeInTheDocument();
    expect(within(rows[0]).getByText("excel · ms excel")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Narzędzia")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Wskazuje rolę/)).toBeInTheDocument();
    expect(within(rows[1]).getByText("Rola")).toBeInTheDocument();
  });

  it("„Zatwierdź pewne” pyta przez okno potwierdzenia, nie natywny confirm", async () => {
    const user = userEvent.setup();
    const native = vi.spyOn(window, "confirm");
    api.proposals.mockResolvedValue(page([row({})]));
    api.acceptSureProposals.mockResolvedValue({ accepted: 1, skipped: [] });
    renderSection();
    await user.click(await screen.findByRole("button", { name: /Zatwierdź pewne nowe hasła i warianty \(1\)/ }));
    expect(api.acceptSureProposals).not.toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "Zatwierdź" }));
    expect(api.acceptSureProposals).toHaveBeenCalledTimes(1);
    expect(native).not.toHaveBeenCalled();
  });

  it("ogólnik pomija się jednym kliknięciem, nie ma „Dodaj”", async () => {
    const user = userEvent.setup();
    api.proposals.mockResolvedValue(
      page([row({ id: 3, decision: "generic", canonical: null, category: null, replacements: ["PostgreSQL"], sure: false })]),
    );
    api.rejectProposal.mockResolvedValue({ id: 3, status: "rejected" });
    renderSection();
    const r = await screen.findByTestId("skill-proposal-row");
    expect(within(r).queryByRole("button", { name: "Dodaj" })).not.toBeInTheDocument();
    expect(within(r).getByText("Zamiast: PostgreSQL")).toBeInTheDocument();
    await user.click(within(r).getByRole("button", { name: "Pomiń" }));
    expect(api.rejectProposal).toHaveBeenCalledWith(3);
  });

  it("pusty stan tylko po udanym odczycie, awaria mówi o sobie", async () => {
    api.proposals.mockResolvedValueOnce(page([]));
    renderSection();
    expect(await screen.findByText(/Nie ma propozycji do przejrzenia/)).toBeInTheDocument();
  });

  it("awaria odczytu nie wygląda jak pusta lista", async () => {
    api.proposals.mockRejectedValue(new Error("500"));
    renderSection();
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów|ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma propozycji do przejrzenia/)).not.toBeInTheDocument();
  });
});
