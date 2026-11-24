import { describe, expect, it } from "vitest";

import type { OrderOffboardingCaseRead } from "@/lib/api/orderGroups";
import {
  agreementModeLabel,
  agreementPartyLabel,
  agreementTerminationPayload,
  attachmentDocType,
  contractProjectEnd,
  defaultNonCompetePlan,
  emptyTerminationForm,
  missingTerminationFields,
  noticeReason,
  signedOnLabel,
  statusEventDetailsText,
  suggestedLastDay,
  terminationFormError,
  terminationWarnings,
} from "@/lib/contract-termination";
import {
  agreementSentence,
  decisionLabel,
  endedPeriod,
  endedStatus,
  endedUsage,
  hasPendingPoolDecision,
  requiresDecision,
} from "@/lib/order-ended-line";

type Line = Parameters<typeof requiresDecision>[0];

function ended(overrides: Partial<Line> = {}): Line {
  return {
    is_active: false,
    start_date: "2026-05-01",
    end_date: "2026-12-31",
    cooperation_ended_on: null,
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

function pool(overrides: Partial<OrderOffboardingCaseRead>): OrderOffboardingCaseRead {
  return {
    id: 1,
    contract_id: 1,
    order_id: 1,
    order_group_id: 1,
    client_id: 1,
    effective_date: "2026-12-31",
    status: "resolved",
    version: 1,
    uses_shared_md_pool: false,
    remaining_md_snapshot: 0,
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
    created_at: "2026-12-31T10:00:00Z",
    updated_at: "2026-12-31T10:00:00Z",
    ...overrides,
  };
}

describe("order-ended-line — brzegi", () => {
  it("umowa o pracę bez daty końca współpracy to koniec projektu, nie współpracy", () => {
    expect(endedStatus(ended({ contract_type: "uop", cooperation_ended_on: null }))).toBe("project");
    expect(endedStatus(ended({ contract_type: null, cooperation_ended_on: "2026-12-31" }))).toBe("project");
  });

  it("zdanie o umowie: rozwiązana bez ostatniego dnia, nieznany typ, umowa nie-B2B", () => {
    expect(agreementSentence(ended({ agreement_termination_mode: "mutual_agreement" }))).toBe(
      "Umowa rozwiązana · Porozumienie stron",
    );
    expect(agreementSentence(ended({ contract_type: null }))).toBeNull();
    expect(agreementSentence(ended({ contract_type: "uop", cooperation_ended_on: "2026-12-31" }))).toBe(
      "Umowa zakończona 31.12.2026",
    );
    expect(agreementSentence(ended({ contract_type: "uz" as never }))).toBe("Umowa nadal obowiązuje");
  });

  it("okres: bez startu z końcem, bez obu, bez końca, koniec z daty współpracy", () => {
    expect(endedPeriod(ended({ start_date: null }))).toBe("do 31.12.2026");
    expect(endedPeriod(ended({ start_date: null, end_date: null }))).toBe("—");
    expect(endedPeriod(ended({ end_date: null }))).toBe("01.05.2026 – …");
    expect(endedPeriod(ended({ end_date: null, cooperation_ended_on: "2027-01-01" }))).toBe(
      "01.05.2026 – 01.01.2027",
    );
  });

  it("zużycie: koszt bez faktur = null, MD zero, grosze zaokrąglone", () => {
    expect(endedUsage({ is_cost_based: true }, { invoiced_total: null, md_used: 3, rate_revenue: 100 })).toBeNull();
    expect(endedUsage({ is_cost_based: true }, { invoiced_total: 0, md_used: null, rate_revenue: null })).toMatch(
      /^0,00\s?zł$/,
    );
    expect(endedUsage({ is_cost_based: false }, { invoiced_total: null, md_used: 0, rate_revenue: 800 })).toMatch(
      /^0 MD · 0,00\s?zł$/,
    );
    expect(
      endedUsage({ is_cost_based: false }, { invoiced_total: null, md_used: 1.333, rate_revenue: 100.01 }),
    ).toMatch(/^1,333 MD · 133,31\s?zł$/);
  });

  it("aktywna linia nigdy nie wymaga decyzji, nawet z czekającą pulą", () => {
    expect(requiresDecision(ended({ is_active: true, offboarding_case: pool({ status: "pending" }) }))).toBe(false);
  });

  it("czekająca pula z zaplanowanym następcą nie czeka", () => {
    const line = ended({ offboarding_case: pool({ status: "pending" }), replaced_by_scheduled: true });
    expect(hasPendingPoolDecision(line)).toBe(false);
    expect(hasPendingPoolDecision(ended({ offboarding_case: pool({ status: "pending" }) }))).toBe(true);
  });

  it("decyzja: usunięcie z zamówienia wygrywa z innymi śladami", () => {
    expect(decisionLabel(ended({ removed_from_order: true, replaced_by_order_id: 9, history_kept_at: "2026-12-31" }))).toBe(
      "Usunięty z zamówienia",
    );
  });

  it("decyzja: zaplanowane zastępstwo bez nazwiska i daty", () => {
    expect(decisionLabel(ended({ replaced_by_order_id: 9, replaced_by_scheduled: true }))).toBe(
      "Zastępstwo: następca od —",
    );
    expect(decisionLabel(ended({ replaced_by_order_id: 9 }))).toBe("Zastąpiony przez następca");
  });

  it("decyzja: pula wykorzystana automatycznie, zamknięta, nierozstrzygnięta", () => {
    expect(decisionLabel(ended({ offboarding_case: pool({ resolution_payload: { automatic: true } }) }))).toBe(
      "Pula MD wykorzystana",
    );
    expect(decisionLabel(ended({ offboarding_case: pool({ resolution: "remove" }) }))).toBe("Pula MD zamknięta");
    expect(decisionLabel(ended({ offboarding_case: pool({ resolution: null }) }))).toBeNull();
    expect(decisionLabel(ended({ offboarding_case: pool({ status: "pending" }) }))).toBeNull();
  });
});

describe("contract-termination — etykiety", () => {
  it("tryb i strona: brak, znane, nieznane", () => {
    expect(agreementModeLabel(null)).toBeNull();
    expect(agreementModeLabel("")).toBeNull();
    expect(agreementModeLabel("notice")).toBe("Wypowiedzenie");
    expect(agreementModeLabel("inny")).toBe("inny");
    expect(agreementPartyLabel(undefined)).toBeNull();
    expect(agreementPartyLabel("company")).toBe("b2bnetwork");
    expect(agreementPartyLabel("trzecia")).toBe("trzecia");
  });
  it("koniec projektu: end_date przed terminated_at, oba puste = null", () => {
    expect(contractProjectEnd({ end_date: "2027-01-31", terminated_at: "2026-12-31" })).toBe("2027-01-31");
    expect(contractProjectEnd({ terminated_at: "2026-12-31" })).toBe("2026-12-31");
    expect(contractProjectEnd({})).toBeNull();
  });
  it("typ załącznika, powód wypowiedzenia, zakaz konkurencji", () => {
    expect(attachmentDocType("notice")).toBe("termination_notice");
    expect(attachmentDocType("mutual_agreement")).toBe("termination_agreement");
    expect(noticeReason("project_ended")).toBe("project_ended");
    expect(noticeReason("poached_by_client")).toBe("");
    expect(noticeReason("")).toBe("");
    expect(defaultNonCompetePlan("poached_by_client")).toBe("release");
    expect(defaultNonCompetePlan("")).toBe("keep");
  });
});

describe("suggestedLastDay — koniec miesiąca", () => {
  it("brak, zero i ujemny okres albo zła data: null", () => {
    expect(suggestedLastDay("", 1)).toBeNull();
    expect(suggestedLastDay("2026-09-15", 0)).toBeNull();
    expect(suggestedLastDay("2026-09-15", -1)).toBeNull();
    expect(suggestedLastDay("2026-09-15", null)).toBeNull();
    expect(suggestedLastDay("15.09.2026", 1)).toBeNull();
  });
  it("przez granicę roku, z lutym przestępnym i nieprzestępnym", () => {
    expect(suggestedLastDay("2026-12-31", 1)).toBe("2027-01-31");
    expect(suggestedLastDay("2026-11-30", 3)).toBe("2027-02-28");
    expect(suggestedLastDay("2027-11-01", 3)).toBe("2028-02-29");
    expect(suggestedLastDay("2026-01-15", 12)).toBe("2027-01-31");
    expect(suggestedLastDay("2026-01-15", 23)).toBe("2027-12-31");
  });
});

describe("formularz zakończenia — walidacja", () => {
  it("rozwiązana umowa bez trybu, strony i dat: wszystkie braki, etykieta daty dla wypowiedzenia", () => {
    expect(
      missingTerminationFields(
        emptyTerminationForm({ reason: "other", projectEndDate: "2026-12-31", agreementTerminated: true }),
      ),
    ).toEqual(["Tryb", "Strona", "Data złożenia wypowiedzenia", "Ostatni dzień umowy"]);
  });

  it("porozumienie: etykieta daty zawarcia", () => {
    expect(
      missingTerminationFields(
        emptyTerminationForm({
          reason: "other",
          projectEndDate: "2026-12-31",
          agreementTerminated: true,
          mode: "mutual_agreement",
          party: "consultant",
          lastDay: "2026-12-31",
        }),
      ),
    ).toEqual(["Data zawarcia porozumienia"]);
    expect(signedOnLabel("")).toBe("Data złożenia wypowiedzenia");
  });

  it("wymagany plan umowy", () => {
    expect(missingTerminationFields(emptyTerminationForm(), { requirePlan: true })).toEqual([
      "Powód zakończenia",
      "Data zakończenia projektu",
      "Co z umową B2B",
    ]);
  });

  it("koniec projektu równy startowi kontraktu przechodzi, dzień wcześniej — błąd", () => {
    const form = emptyTerminationForm({ projectEndDate: "2027-01-01" });
    expect(terminationFormError(form, "2027-01-01T00:00:00")).toBeNull();
    expect(terminationFormError({ ...form, projectEndDate: "2026-12-31" }, "2027-01-01")).toMatch(
      /^Data zakończenia projektu jest wcześniejsza niż start kontraktu \(01\.01\.2027\)/,
    );
    expect(terminationFormError(form, null)).toBeNull();
  });

  it("ostatni dzień przed datą porozumienia: błąd z nazwą porozumienia", () => {
    expect(
      terminationFormError(
        emptyTerminationForm({
          agreementTerminated: true,
          mode: "mutual_agreement",
          signedOn: "2027-01-01",
          lastDay: "2026-12-31",
        }),
      ),
    ).toBe("Ostatni dzień umowy nie może być wcześniejszy niż data zawarcia porozumienia.");
  });

  it("ostrzeżenia: brak końca, praca bez umowy, poza okresem zamówienia", () => {
    expect(terminationWarnings(emptyTerminationForm(), "2026-12-31")).toEqual([]);
    expect(
      terminationWarnings(
        emptyTerminationForm({ projectEndDate: "2027-01-01", agreementTerminated: true, lastDay: "2026-12-31" }),
        "2026-12-31",
      ),
    ).toEqual([
      "Konsultant pracowałby na projekcie bez obowiązującej umowy.",
      "Data zakończenia projektu wykracza poza okres zamówienia.",
    ]);
    expect(terminationWarnings(emptyTerminationForm({ projectEndDate: "2026-12-31" }), null)).toEqual([]);
  });

  it("payload: odznaczone albo bez trybu/strony = null", () => {
    const full = emptyTerminationForm({
      agreementTerminated: true,
      mode: "notice",
      party: "company",
      signedOn: "2026-12-01",
      lastDay: "2027-01-31",
    });
    expect(agreementTerminationPayload(full)).toEqual({
      mode: "notice",
      party: "company",
      signed_on: "2026-12-01",
      last_day: "2027-01-31",
    });
    expect(agreementTerminationPayload({ ...full, agreementTerminated: false })).toBeNull();
    expect(agreementTerminationPayload({ ...full, mode: "" })).toBeNull();
    expect(agreementTerminationPayload({ ...full, party: "" })).toBeNull();
  });
});

describe("statusEventDetailsText — wszystkie źródła", () => {
  it("brak szczegółów albo źródła: null; nieznane źródło: null", () => {
    expect(statusEventDetailsText(null)).toBeNull();
    expect(statusEventDetailsText({})).toBeNull();
    expect(statusEventDetailsText({ source: "manual" })).toBeNull();
  });

  it("zakończenie z pełnym rozwiązaniem", () => {
    expect(
      statusEventDetailsText({
        source: "contract_termination_synced",
        contract_id: 12,
        project_end_date: "2026-12-31",
        agreement_terminated: true,
        mode: "notice",
        party: "consultant",
        signed_on: "2026-11-30",
        agreement_last_day: "2027-01-31",
      }),
    ).toBe(
      "Zakończenie współpracy (kontrakt #12) · koniec zamówienia 31.12.2026 · Wypowiedzenie · strona: Konsultant · data złożenia wypowiedzenia 30.11.2026 · ostatni dzień umowy 31.01.2027",
    );
  });

  it("zakończenie bez id kontraktu, z rozwiązaniem bez strony i dat", () => {
    expect(
      statusEventDetailsText({ source: "contract_termination_synced", agreement_terminated: true, mode: "x" }),
    ).toBe("Zakończenie współpracy (kontrakt) · x");
  });

  it("zakończenie z rozwiązaniem bez trybu: umowa obowiązuje dalej", () => {
    expect(
      statusEventDetailsText({ source: "contract_termination_synced", agreement_terminated: true }),
    ).toBe("Zakończenie współpracy (kontrakt) · umowa obowiązuje dalej");
  });

  it("rozwiązanie zapisane po zakończeniu: z trybem i dniem albo bez", () => {
    expect(
      statusEventDetailsText({
        source: "agreement_termination_recorded",
        contract_id: 3,
        mode: "mutual_agreement",
        agreement_last_day: "2026-12-31",
      }),
    ).toBe("Rozwiązanie umowy zapisane po zakończeniu (kontrakt #3) · Porozumienie stron · ostatni dzień umowy 31.12.2026");
    expect(statusEventDetailsText({ source: "agreement_termination_recorded" })).toBe(
      "Rozwiązanie umowy zapisane po zakończeniu (kontrakt)",
    );
  });

  it("powiązanie, cofnięcie, powrót po przerwie, nowa umowa po przerwie", () => {
    expect(statusEventDetailsText({ source: "linked_to_contract", contract_id: 4 })).toMatch(
      /^Powiązano z kontraktem #4/,
    );
    expect(statusEventDetailsText({ source: "contract_termination_undone", contract_id: 4 })).toMatch(
      /^Cofnięto zakończenie współpracy \(kontrakt #4\)/,
    );
    expect(statusEventDetailsText({ source: "contract_returned_after_break" })).toBe(
      "Powrót po przerwie (kontrakt) — projekt wznowiony",
    );
    expect(statusEventDetailsText({ source: "created_after_break" })).toBe("Nowa umowa po przerwie");
    expect(
      statusEventDetailsText({ source: "created_after_break", previous_contract_number: "B2B/2026/01" }),
    ).toBe("Nowa umowa po przerwie — poprzednia: B2B/2026/01");
  });
});
