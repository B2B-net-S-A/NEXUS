import { describe, expect, it } from "vitest";

import type { ApprovalRequestRow } from "@/lib/api/hr-approvals";

import { parseLimit } from "../ApprovalRulesCard";
import { toInput, type FormState } from "../ConsentRequestForm";
import {
  KIND_OPTIONS,
  afterDecision,
  approveLabel,
  canChangeAmount,
  isUrgent,
  moneyPl,
  stageLine,
  timeline,
} from "../approvals-format";

const row = (overrides: Partial<ApprovalRequestRow> = {}): ApprovalRequestRow =>
  ({
    id: 1,
    kind: "trip",
    kind_label: "Delegacja",
    status: "pending_supervisor",
    status_label: "U koordynatora",
    title: "Gdańsk",
    purpose: "Warsztat",
    amount: "2180.00",
    decided_amount: null,
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    amount_text: "2 180 zł brutto",
    payer: "reimbursement",
    link_url: null,
    needed_by: null,
    starts_on: null,
    ends_on: null,
    beneficiary_user_id: null,
    beneficiary_name: null,
    payout_year: null,
    payout_month: null,
    requester_user_id: 1,
    requester_name: "Tomasz Podglądowy",
    supervisor_user_id: 2,
    supervisor_name: "Marta Fikcyjna",
    needs_final: true,
    final_approver_names: ["Aniela Administrująca"],
    endorsed_by_name: null,
    endorsed_at: null,
    endorse_note: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    decision_channel: null,
    bonus_id: null,
    submitted_at: "2026-10-20T07:00:00Z",
    can_decide: true,
    decides_as: "supervisor",
    can_edit: false,
    can_withdraw: false,
    ...overrides,
  }) as ApprovalRequestRow;

describe("teksty zgód", () => {
  it("kwota po polsku, bez groszy przy pełnych złotych", () => {
    expect(moneyPl("1500.00")).toBe("1500 zł");
    expect(moneyPl("21380.00")).toMatch(/^21\s380 zł$/);
    expect(moneyPl("1500.5", "EUR")).toBe("1500,50 EUR");
    expect(moneyPl(null)).toBe("—");
    expect(moneyPl("abc")).toBe("—");
  });

  it("przełożony ponad próg popiera i nie zmienia kwoty; w progu i zatwierdzający — zatwierdza", () => {
    expect(approveLabel(row())).toBe("Popieram");
    expect(canChangeAmount(row())).toBe(false);
    expect(afterDecision(row()).label).toBe("Po poparciu");
    expect(afterDecision(row()).text).toContain("Aniela Administrująca");
    expect(approveLabel(row({ needs_final: false }))).toBe("Zatwierdź");
    expect(approveLabel(row({ decides_as: "final" }))).toBe("Zatwierdź");
    expect(canChangeAmount(row({ decides_as: "final" }))).toBe(true);
  });

  it("premia po zatwierdzeniu trafia do Płac bez drugiej akceptacji", () => {
    const bonus = row({
      kind: "bonus",
      decides_as: "final",
      beneficiary_name: "Julia Próbna",
      payout_year: 2026,
      payout_month: 10,
    });
    expect(afterDecision(bonus).label).toBe("Po zatwierdzeniu");
    expect(afterDecision(bonus).text).toContain("Płac");
    expect(afterDecision(bonus).text).toContain("październik 2026");
    // Zgody to ekran wielu osób: neutralnie, bez „premii poza umową” (21.10.2026).
    expect(afterDecision(bonus).text).not.toMatch(/premi/i);
    const option = KIND_OPTIONS.find((item) => item.value === "bonus");
    expect(option?.label).toBe("Wynagrodzenie dodatkowe");
    expect(option?.hint).toBe("wymaga podstawy: punkt umowy albo aneks");
  });

  it("kto decyduje teraz", () => {
    expect(stageLine(row())).toBe("U koordynatora (Marta Fikcyjna), potem Aniela Administrująca");
    expect(stageLine(row({ status: "pending_final" }))).toBe("Czeka na: Aniela Administrująca");
    expect(stageLine(row({ status: "approved", decided_by_name: "Aniela Administrująca" }))).toBe(
      "Zatwierdził(a) Aniela Administrująca",
    );
  });

  it("oś zgody: poparcie i pytanie z uwagami, bieżący krok zaznaczony", () => {
    const returned = timeline(
      row({
        status: "returned",
        endorsed_by_name: "Marta Fikcyjna",
        endorsed_at: "2026-10-20T08:00:00Z",
        decided_by_name: "Aniela Administrująca",
        decided_at: "2026-10-20T09:00:00Z",
        decision_note: "Dopisz hotel",
      }),
    );
    expect(returned.map((step) => step.title)).toEqual([
      "Wysłana",
      "Poparł(a) Marta Fikcyjna",
      "Pytanie od Aniela Administrująca",
    ]);
    expect(returned[2].detail).toContain("Dopisz hotel");
    const waiting = timeline(row());
    expect(waiting.map((step) => step.state)).toEqual(["done", "current", "todo"]);
  });

  it("pilne = termin dziś albo jutro", () => {
    expect(isUrgent(row({ needed_by: "2026-10-21" }), "2026-10-20")).toBe(true);
    expect(isUrgent(row({ needed_by: "2026-10-22" }), "2026-10-20")).toBe(false);
    expect(isUrgent(row({ needed_by: null }), "2026-10-20")).toBe(false);
  });
});

const form = (overrides: Partial<FormState> = {}): FormState => ({
  kind: "subscription",
  title: " Narzędzie ",
  purpose: "Ogłoszenia",
  amount: "1 240,50",
  amountBasis: "net",
  recurrence: "monthly",
  payer: "company_card",
  linkUrl: "",
  neededBy: "",
  startsOn: "2026-11-01",
  endsOn: "",
  beneficiary: "",
  payout: "2026-10",
  client: null,
  sellerNip: "",
  contractBasis: "",
  ...overrides,
});

describe("ciało formularza zgody", () => {
  it("kwota z przecinkiem i spacją, puste pola jako null", () => {
    const input = toInput(form());
    expect(input).toMatchObject({
      title: "Narzędzie",
      amount: "1240.50",
      amount_basis: "net",
      recurrence: "monthly",
      payer: "company_card",
      link_url: null,
      starts_on: "2026-11-01",
      beneficiary_user_id: null,
      payout_year: null,
    });
  });

  it("premia: raz, brutto, bez płatnika i dat — kształt z CHECK-a w bazie", () => {
    const input = toInput(form({ kind: "bonus", beneficiary: "107", payout: "2026-11" }));
    expect(input).toMatchObject({
      amount_basis: "gross",
      recurrence: "once",
      payer: null,
      starts_on: null,
      beneficiary_user_id: 107,
      payout_year: 2026,
      payout_month: 11,
    });
  });

  it("klient tylko przy prezencie, NIP sprzedawcy bez spacji i myślników", () => {
    const client = { id: 42, name: "Bank Przykładowy" } as NonNullable<FormState["client"]>;
    expect(toInput(form({ kind: "gift", client, sellerNip: "123-456-32 18" }))).toMatchObject({
      client_id: 42,
      seller_nip: "1234563218",
    });
    expect(toInput(form({ kind: "training", client }))).toMatchObject({ client_id: null, seller_nip: null });
    expect(toInput(form({ kind: "bonus", sellerNip: "1234563218", beneficiary: "7" }))).toMatchObject({
      seller_nip: null,
    });
  });
});

describe("podstawa w umowie przy premii (0491)", () => {
  it("tylko przy premii, przycięta, pusta jako null", () => {
    expect(
      toInput(form({ kind: "bonus", beneficiary: "7", contractBasis: "  § 6 ust. 2 umowy " })),
    ).toMatchObject({ contract_basis: "§ 6 ust. 2 umowy" });
    expect(toInput(form({ kind: "bonus", beneficiary: "7", contractBasis: "  " }))).toMatchObject({
      contract_basis: null,
    });
    expect(toInput(form({ kind: "training", contractBasis: "§ 6" }))).toMatchObject({
      contract_basis: null,
    });
  });
});

describe("próg przełożonego w Ustawieniach", () => {
  it("puste albo „nigdy” = zawsze zatwierdzający; liczby całkowite do miliona", () => {
    expect(parseLimit("")).toBeNull();
    expect(parseLimit("never")).toBeNull();
    expect(parseLimit("1 500")).toBe(1500);
    expect(parseLimit("0")).toBe(0);
    expect(parseLimit("12,5")).toBeUndefined();
    expect(parseLimit("-3")).toBeUndefined();
    expect(parseLimit("2000000")).toBeUndefined();
  });
});
