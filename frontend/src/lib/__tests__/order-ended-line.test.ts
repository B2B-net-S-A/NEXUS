import { describe, expect, it } from "vitest";

import type { OrderOffboardingCaseRead } from "@/lib/api/orderGroups";
import {
  agreementSentence,
  decisionLabel,
  endedPeriod,
  endedStatus,
  endedUsage,
  requiresDecision,
  sortEndedLines,
} from "@/lib/order-ended-line";

type Line = Parameters<typeof requiresDecision>[0];

// Nazwiska i kwoty zmyślone (repo jest publiczne).
function ended(overrides: Partial<Line> = {}): Line {
  return {
    is_active: false,
    start_date: "2031-05-01",
    end_date: "2031-08-31",
    cooperation_ended_on: "2031-08-31",
    removed_from_order: false,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    replaced_by_scheduled: false,
    replaced_by_start_date: null,
    history_kept_at: null,
    offboarding_case: null,
    contract_type: "b2b",
    agreement_termination_mode: null,
    agreement_last_day: null,
    ...overrides,
  };
}

function poolCase(
  overrides: Partial<OrderOffboardingCaseRead> = {},
): OrderOffboardingCaseRead {
  return {
    id: 1,
    contract_id: 1,
    order_id: 1,
    order_group_id: 1,
    client_id: 1,
    effective_date: "2031-08-31",
    status: "pending",
    version: 1,
    uses_shared_md_pool: false,
    remaining_md_snapshot: 3.7,
    rate_cost_snapshot: null,
    rate_revenue_snapshot: null,
    currency_snapshot: null,
    order_number_snapshot: null,
    resolution: null,
    target_order_id: null,
    rate_basis: null,
    resolution_payload: null,
    resolved_at: null,
    resolved_by_user_id: null,
    created_by_user_id: null,
    created_at: "2031-08-31T10:00:00Z",
    updated_at: "2031-08-31T10:00:00Z",
    ...overrides,
  };
}

describe("plakietka zakończenia — tylko dwie", () => {
  it("umowa rozwiązana (wypowiedzenie albo porozumienie) = „Zakończył współpracę”", () => {
    expect(endedStatus(ended({ agreement_termination_mode: "notice" }))).toBe("cooperation");
    expect(endedStatus(ended({ agreement_termination_mode: "mutual_agreement" }))).toBe(
      "cooperation",
    );
  });

  it("koniec pracy na zamówieniu przy trwającej umowie B2B = „Zakończył projekt”", () => {
    expect(endedStatus(ended())).toBe("project");
    expect(endedStatus(ended({ cooperation_ended_on: null }))).toBe("project");
  });

  it("umowa o pracę/zlecenie bez osobnego rozwiązania: zakończony kontrakt = koniec współpracy", () => {
    expect(endedStatus(ended({ contract_type: "uop" }))).toBe("cooperation");
    expect(endedStatus(ended({ contract_type: "uop", cooperation_ended_on: null }))).toBe(
      "project",
    );
  });
});

describe("zdanie o umowie w rozwinięciu", () => {
  it("rozwiązanie: ostatni dzień umowy i tryb", () => {
    expect(
      agreementSentence(
        ended({ agreement_termination_mode: "notice", agreement_last_day: "2031-09-30" }),
      ),
    ).toBe("Ostatni dzień umowy: 30.09.2031 · Wypowiedzenie");
    expect(
      agreementSentence(
        ended({
          agreement_termination_mode: "mutual_agreement",
          agreement_last_day: "2031-08-31",
        }),
      ),
    ).toBe("Ostatni dzień umowy: 31.08.2031 · Porozumienie stron");
  });

  it("umowa B2B bez rozwiązania nadal obowiązuje", () => {
    expect(agreementSentence(ended())).toBe("Umowa B2B nadal obowiązuje");
  });

  it("bez danych o umowie — nic, zamiast zgadywać", () => {
    expect(agreementSentence(ended({ contract_type: null }))).toBeNull();
  });
});

describe("okres i wykorzystanie na zwiniętej karcie", () => {
  it("okres bez powtórzonej daty końca", () => {
    expect(endedPeriod(ended())).toBe("01.05.2031 – 31.08.2031");
    expect(endedPeriod(ended({ end_date: null }))).toBe("01.05.2031 – 31.08.2031");
  });

  it("MD i kwota: „25,45 MD · 25 450,00 zł”", () => {
    expect(
      endedUsage(
        { is_cost_based: false },
        { md_used: 25.45, rate_revenue: 1000, invoiced_total: null },
      ),
    ).toMatch(/^25,45 MD · 25\s450,00\szł$/);
  });

  it("rola bez finansów widzi same MD", () => {
    expect(
      endedUsage({ is_cost_based: false }, { md_used: 7, rate_revenue: null, invoiced_total: null }),
    ).toBe("7 MD");
  });

  it("zamówienie kosztowe: zafakturowana kwota; brak danych = null, nie zero", () => {
    expect(
      endedUsage({ is_cost_based: true }, { md_used: null, rate_revenue: 900, invoiced_total: 12500 }),
    ).toMatch(/^12\s500,00\szł$/);
    expect(
      endedUsage({ is_cost_based: false }, { md_used: null, rate_revenue: 900, invoiced_total: null }),
    ).toBeNull();
  });
});

describe("decyzja o osobie", () => {
  it("zakończona współpraca bez decyzji wymaga decyzji", () => {
    expect(requiresDecision(ended())).toBe(true);
    expect(decisionLabel(ended())).toBeNull();
  });

  it("czekająca sprawa puli MD wymaga decyzji; zaplanowany następca już nie", () => {
    expect(requiresDecision(ended({ offboarding_case: poolCase() }))).toBe(true);
    expect(
      requiresDecision(
        ended({
          offboarding_case: poolCase(),
          replaced_by_order_id: 9,
          replaced_by_consultant_name: "Ewa Następna",
          replaced_by_scheduled: true,
          replaced_by_start_date: "2031-09-15",
        }),
      ),
    ).toBe(false);
  });

  it("po decyzji: opis zamiast przycisku", () => {
    expect(requiresDecision(ended({ history_kept_at: "2031-09-01T10:00:00Z" }))).toBe(false);
    expect(decisionLabel(ended({ history_kept_at: "2031-09-01T10:00:00Z" }))).toBe(
      "Zostawiony jako historia",
    );
    expect(
      decisionLabel(ended({ replaced_by_order_id: 9, replaced_by_consultant_name: "Ewa Następna" })),
    ).toBe("Zastąpiony przez Ewa Następna");
    expect(
      decisionLabel(
        ended({ offboarding_case: poolCase({ status: "resolved", resolution: "transfer" }) }),
      ),
    ).toBe("Pula MD przeniesiona");
    expect(
      decisionLabel(
        ended({
          offboarding_case: poolCase({
            status: "resolved",
            resolution: "remove",
            resolution_payload: { automatic: true },
          }),
        }),
      ),
    ).toBe("Pula MD wykorzystana");
  });

  it("koniec projektu bez końca współpracy (np. zamknięte zamówienie) — bez decyzji", () => {
    expect(requiresDecision(ended({ cooperation_ended_on: null }))).toBe(false);
  });

  it("karty wymagające decyzji idą na górę, reszta w dotychczasowej kolejności", () => {
    const kept = { ...ended({ history_kept_at: "2031-09-01T10:00:00Z" }), id: 1 };
    const open = { ...ended(), id: 2 };
    const done = { ...ended({ cooperation_ended_on: null }), id: 3 };
    expect(sortEndedLines([kept, open, done]).map((line) => line.id)).toEqual([2, 1, 3]);
  });
});
