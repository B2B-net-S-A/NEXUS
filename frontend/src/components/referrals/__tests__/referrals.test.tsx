import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateReferral } from "@/lib/api/candidateReferrals";

import { ReferralsPanel } from "../ReferralsPanel";
import { actionsFor, formatBonus, parseBonus, payoutLine } from "../referral-model";

const mocks = vi.hoisted(() => ({
  referrals: [] as CandidateReferral[],
  canPay: false,
}));

vi.mock("@/lib/api/candidateReferrals", () => ({
  useCandidateReferrals: () => ({
    data: mocks.referrals,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
  }),
  useUpdateReferral: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMarkReferralPaid: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/permissions", () => ({
  hasPermission: (_user: unknown, permission: string) =>
    permission === "finance_module" && mocks.canPay,
}));
vi.mock("@/components/Toast", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

function referral(extra: Partial<CandidateReferral> = {}): CandidateReferral {
  return {
    id: 5,
    referrer_name: "Jan Testowy",
    referrer_email: "jan@example.com",
    referrer_candidate_id: null,
    referrer_contract_id: null,
    referred_name: "Ewa Przykładowa",
    referred_email: null,
    referred_linkedin: "https://linkedin.com/in/ewa",
    referred_role: "QA Automation",
    candidate_id: 77,
    submission_id: 9,
    was_in_database: false,
    statement_text: "Ta osoba wie, że ją polecam.",
    status: "started",
    bonus_amount: "2500.00",
    status_note: "",
    status_changed_at: null,
    created_at: "2026-11-28T10:00:00Z",
    ...extra,
  };
}

function renderPanel() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <ReferralsPanel />
    </QueryClientProvider>,
  );
}

describe("referral-model", () => {
  it("przyjmuje premię tylko od 1000 do 5000 zł", () => {
    expect(parseBonus("2 500")).toBe("2500.00");
    expect(parseBonus("1000")).toBe("1000.00");
    expect(parseBonus("5000,00")).toBe("5000.00");
    expect(parseBonus("999")).toBeNull();
    expect(parseBonus("5000,01")).toBeNull();
    expect(parseBonus("dużo")).toBeNull();
  });

  it("„Wypłacona” tylko z modułem Finanse i tylko po starcie projektu", () => {
    expect(actionsFor(referral(), { canPay: false }).some((a) => a.kind === "paid")).toBe(false);
    expect(actionsFor(referral(), { canPay: true })[0].kind).toBe("paid");
    expect(
      actionsFor(referral({ status: "contacted" }), { canPay: true }).some((a) => a.kind === "paid"),
    ).toBe(false);
    expect(actionsFor(referral({ status: "paid" }), { canPay: true })).toEqual([]);
  });

  it("mówi, jak premia trafi do polecającego", () => {
    expect(payoutLine(referral())).toContain("krótkiej umowy");
    expect(payoutLine(referral({ referrer_contract_id: 3 }))).toContain("faktury");
    expect(formatBonus(null)).toBe("nie ustalono");
  });
});

describe("ReferralsPanel", () => {
  beforeEach(() => {
    mocks.referrals = [];
    mocks.canPay = false;
  });

  it("rekruter nie widzi „Wypłacona”", async () => {
    mocks.referrals = [referral()];
    renderPanel();
    // Filtr startuje od „Nowe”; polecenie po starcie projektu jest pod swoim filtrem.
    await userEvent.click(screen.getByRole("button", { name: /Zaczął projekt\s*1/ }));

    expect(await screen.findByText("Ewa Przykładowa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wypłacona" })).not.toBeInTheDocument();
  });

  it("Finanse widzą „Wypłacona” przy premii należnej", async () => {
    mocks.referrals = [referral()];
    mocks.canPay = true;
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /Zaczął projekt\s*1/ }));

    expect(await screen.findByRole("button", { name: "Wypłacona" })).toBeInTheDocument();
  });

  it("link spoza http(s) nie jest linkiem", async () => {
    mocks.referrals = [
      referral({ status: "new", referred_linkedin: "javascript:alert(1)", bonus_amount: null }),
    ];
    renderPanel();

    expect(await screen.findByText("brak kontaktu")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Profil LinkedIn" })).not.toBeInTheDocument();
  });
});
