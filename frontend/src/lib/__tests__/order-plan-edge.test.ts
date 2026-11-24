import { describe, expect, it } from "vitest";

import type {
  ConsultantOption,
  OrderGroupExtraction,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";
import {
  chooseConsultant,
  chooseContract,
  draftsFromPlan,
  duplicatePersonKeys,
  emptyDraft,
  keepAsHistory,
  lineIssues,
  lineValuePln,
  replaceWith,
  revenueUnitFromDocument,
  sourceLabel,
  splitPlanForGroup,
  toLineInput,
  type OrderLineDraft,
  type OrderPlanContext,
} from "@/lib/order-plan";

function contract(overrides: Partial<OrderPlanContract> = {}): OrderPlanContract {
  return {
    contract_id: 21,
    candidate_id: 201,
    contractor_name: "Jan Testowy",
    status: "active",
    start_date: "2026-01-01",
    end_date: null,
    rate_cost: 800,
    rate_cost_unit: "daily",
    rate_cost_currency: "PLN",
    rate_cost_rate_to_pln: 1,
    rate_cost_per_md_pln: 800,
    ...overrides,
  };
}

function line(overrides: Partial<OrderPlanLine> = {}): OrderPlanLine {
  return {
    ordinal: 1,
    document_name: "Jan Testowy",
    position_label: null,
    rate_revenue: 1000,
    rate_revenue_unit: "day",
    rate_revenue_gross: null,
    md_total: 20,
    start_date: null,
    end_date: null,
    match_status: "auto",
    match_reason: "",
    contract: contract(),
    options: [],
    nearest_names: [],
    warnings: [],
    ...overrides,
  };
}

function plan(lines: OrderPlanLine[], currency: string | null = "PLN"): OrderGroupExtraction {
  return {
    order_number: "T-1",
    start_date: "2027-01-01",
    end_date: null,
    total_value: null,
    currency,
    md_total: null,
    suggested_order_type: "md",
    client_policy: null,
    consultant_ref: null,
    title_needs_review: false,
    document_incomplete: false,
    uncertain: false,
    uncertain_reasons: [],
    lines,
  } as OrderGroupExtraction;
}

function option(overrides: Partial<ConsultantOption> = {}): ConsultantOption {
  return {
    candidate_id: 301,
    contract_id: 31,
    full_name: "Anna Przykładowa",
    first_name: "Anna",
    last_name: "Przykładowa",
    source: "client_recruitment",
    source_label: "Rekrutacja u klienta",
    job_title: null,
    suggested_rate_cost: null,
    has_different_client_contract_rates: false,
    ...overrides,
  } as ConsultantOption;
}

const md: OrderPlanContext = {
  clientId: 18,
  orderType: "md",
  sharedMd: false,
  groupStart: "2027-01-01",
  groupEnd: "2027-12-31",
};

function ready(overrides: Partial<OrderLineDraft> = {}): OrderLineDraft {
  return {
    ...emptyDraft(),
    person: { contractId: 21, candidateId: 201, name: "Jan Testowy", status: "active", startDate: null },
    rateCost: "800",
    rateRevenue: "1000",
    md: "20",
    ...overrides,
  };
}

describe("revenueUnitFromDocument", () => {
  it("godzina, miesiąc, dzień i brak jednostki", () => {
    expect(revenueUnitFromDocument("hour")).toBe("hour");
    expect(revenueUnitFromDocument("month")).toBe("month");
    expect(revenueUnitFromDocument("day")).toBe("md");
    expect(revenueUnitFromDocument(null)).toBeNull();
  });
});

describe("draftsFromPlan — brzegi", () => {
  it("kontrakt bez stawki kosztowej: puste pole, MD, PLN, bez źródła", () => {
    const [d] = draftsFromPlan(plan([line({ contract: contract({ rate_cost: null }) })]));
    expect(d).toMatchObject({ rateCost: "", costUnit: "md", costCurrency: "PLN", costSource: null });
  });

  it("waluta kosztu małymi literami i pusta → PLN; waluta zamówienia z PDF-a", () => {
    const [eur] = draftsFromPlan(plan([line({ contract: contract({ rate_cost_currency: " eur " }) })], " eur"));
    expect(eur.costCurrency).toBe("EUR");
    expect(eur.revenueCurrency).toBe("EUR");
    const [blank] = draftsFromPlan(plan([line({ contract: contract({ rate_cost_currency: "  " }) })], null));
    expect(blank.costCurrency).toBe("PLN");
    expect(blank.revenueCurrency).toBe("PLN");
  });

  it("kwota bez jednostki: jednostka null i problem przy karcie", () => {
    const [d] = draftsFromPlan(plan([line({ rate_revenue_unit: null })]));
    expect(d.revenueUnit).toBeNull();
    expect(lineIssues(d, md)).toContain("jednostka stawki przychodowej");
    expect(lineValuePln(d)).toBeNull();
    expect(() => toLineInput(d, md)).toThrow("Karta bez jednostki stawki przychodowej");
  });

  it("brak kwoty i MD: jednostka domyślna MD, bez źródeł", () => {
    const [d] = draftsFromPlan(plan([line({ rate_revenue: null, md_total: null })]));
    expect(d).toMatchObject({ revenueUnit: "md", revenueSource: null, mdSource: null, rateRevenue: "", md: "" });
  });

  it("dopasowanie bez kontraktu i zakończone bez daty końca", () => {
    const [none] = draftsFromPlan(plan([line({ match_status: "confirm", contract: null })]));
    expect(none.person).toBeNull();
    expect(none.costSource).toBeNull();
    const [inactive] = draftsFromPlan(plan([line({ match_status: "inactive", contract: contract({ end_date: null }) })]));
    expect(inactive.contractEndDate).toBeNull();
  });

  it("własny okres pozycji z czasem obcinany do dnia (granica roku)", () => {
    const [d] = draftsFromPlan(
      plan([line({ start_date: "2026-12-31T00:00:00", end_date: "2027-01-01T00:00:00" })]),
    );
    expect(d.startDate).toBe("2026-12-31");
    expect(d.endDate).toBe("2027-01-01");
  });
});

describe("chooseContract / chooseConsultant / replaceWith", () => {
  it("zakończony kontrakt bez komunikatu serwera i bez daty końca", () => {
    const d = chooseContract(emptyDraft(), contract({ status: "ended", end_date: null }));
    expect(d.match).toBe("inactive");
    expect(d.matchReason).toMatch(/nie ma już aktywnej współpracy/);
    expect(d.contractEndDate).toBeNull();
  });

  it("surowa stawka kontraktu z walutą; pusta waluta → PLN", () => {
    const eur = chooseConsultant(
      emptyDraft(),
      option({ suggested_contract_rate_cost: 100, suggested_rate_cost_unit: "hourly", suggested_rate_cost_currency: " eur" }),
    );
    expect(eur).toMatchObject({ rateCost: "100.000", costUnit: "hour", costCurrency: "EUR", costSource: "contract" });
    const blank = chooseConsultant(emptyDraft(), option({ suggested_contract_rate_cost: 900, suggested_rate_cost_currency: null }));
    expect(blank).toMatchObject({ costUnit: "md", costCurrency: "PLN" });
  });

  it("bez żadnej podpowiedzi: puste pole kosztu", () => {
    const d = chooseConsultant(ready(), option({ suggested_rate_cost: null }));
    expect(d).toMatchObject({ rateCost: "", costSource: null, match: "manual", confirmed: true });
    expect(d.person).toMatchObject({ contractId: 31, candidateId: 301, name: "Anna Przykładowa" });
  });

  it("zastępstwo: kolejno poprzednie zastępstwo, nazwa z dokumentu, osoba, null", () => {
    expect(replaceWith(ready({ replacesName: "Pierwszy Testowy", documentName: "X" }), option()).replacesName).toBe(
      "Pierwszy Testowy",
    );
    expect(replaceWith(ready({ documentName: null }), option()).replacesName).toBe("Jan Testowy");
    expect(replaceWith(emptyDraft(), option()).replacesName).toBeNull();
  });
});

describe("lineIssues — ścieżki odmowy", () => {
  it("historia bez daty końca współpracy", () => {
    const d = keepAsHistory(ready({ match: "inactive", contractEndDate: null }));
    expect(lineIssues(d, md)).toEqual(["data zakończenia współpracy"]);
  });

  it("historia z końcem przed startem zamówienia (granica roku), start z karty wygrywa", () => {
    const d = keepAsHistory(ready({ match: "inactive", contractEndDate: "2026-12-31" }));
    expect(lineIssues(d, md)).toEqual(["współpraca skończyła się przed startem zamówienia — wznów albo zastąp"]);
    expect(lineIssues({ ...d, startDate: "2026-12-01" }, md)).toEqual([]);
  });

  it("zerowa i ujemna stawka przychodowa, pusty koszt, zero MD, brak startu", () => {
    const d = ready({ rateCost: " ", rateRevenue: "-5", md: "0" });
    expect(lineIssues(d, { ...md, groupStart: "" })).toEqual([
      "stawka kosztowa",
      "stawka przychodowa",
      "liczba MD",
      "data rozpoczęcia",
    ]);
  });

  // Serwer odmawia ujemnego kosztu 422 (`rate_cost: Field(..., ge=0)`
  // w schemas/client_order_group.py), więc karta nie może wyglądać na gotową.
  it("ujemna stawka kosztowa to problem karty („stawka kosztowa”), jak u serwera (ge=0)", () => {
    expect(lineIssues(ready({ rateCost: "-5" }), md)).toEqual(["stawka kosztowa"]);
    expect(lineIssues(ready({ rateCost: "-0,01" }), md)).toEqual(["stawka kosztowa"]);
  });

  it("zerowa stawka kosztowa jest dozwolona (serwer też: ge=0)", () => {
    expect(lineIssues(ready({ rateCost: "0" }), md)).toEqual([]);
  });

  it("wspólna pula i zamówienie kosztowe nie wymagają MD przy osobie", () => {
    const d = ready({ md: "" });
    expect(lineIssues(d, { ...md, sharedMd: true })).toEqual([]);
    expect(lineIssues(d, { ...md, orderType: "cost" })).toEqual([]);
  });
});

describe("toLineInput — brzegi", () => {
  it("karta bez osoby rzuca", () => {
    expect(() => toLineInput(emptyDraft(), md)).toThrow("Karta bez wskazanego kontraktora");
  });

  it("nieliczbowa stawka rzuca zamiast wysłać NaN", () => {
    expect(() => toLineInput(ready({ rateCost: "abc" }), md)).toThrow("Nieprawidłowa stawka na karcie konsultanta");
    expect(() => toLineInput(ready({ rateRevenue: "" }), md)).toThrow("Nieprawidłowa stawka na karcie konsultanta");
  });

  it("stawka godzinowa przeliczona na MD, przecinek dziesiętny, osoba bez kontraktu", () => {
    const input = toLineInput(
      ready({
        person: { contractId: null, candidateId: 777, name: "Anna Przykładowa", status: null, startDate: null },
        rateCost: "100,5",
        costUnit: "hour",
        rateRevenue: "150",
        revenueUnit: "hour",
      }),
      md,
    );
    expect(input).toMatchObject({ candidate_id: 777, rate_cost: 804, rate_revenue: 1200, input_mode: "md", input_value: 20 });
    expect("contract_id" in input).toBe(false);
  });

  it("CeZ: opcja MD tylko dodatnia; inny klient nigdy", () => {
    const cez = { ...md, clientId: EZDROWIE_CLIENT_ID };
    expect(toLineInput(ready({ optionalMd: "5" }), cez)).toMatchObject({ optional_md: 5 });
    expect("optional_md" in toLineInput(ready({ optionalMd: "0" }), cez)).toBe(false);
    expect("optional_md" in toLineInput(ready({ optionalMd: "" }), cez)).toBe(false);
    expect("optional_md" in toLineInput(ready({ optionalMd: "5" }), md)).toBe(false);
  });

  it("bez MD przy osobie: brak trybu MD; koniec z karty albo zamówienia; nazwa z dokumentu", () => {
    const pooled = toLineInput(ready({ md: "", documentName: "Jan Testowy", endDate: "2027-06-30" }), {
      ...md,
      sharedMd: true,
    });
    expect("input_mode" in pooled).toBe(false);
    expect(pooled).toMatchObject({ end_date: "2027-06-30", document_name: "Jan Testowy", start_date: "2027-01-01" });
    const plain = toLineInput(ready(), { ...md, groupEnd: null });
    expect(plain.end_date).toBeNull();
    expect("document_name" in plain).toBe(false);
    expect("replaces_name" in plain).toBe(false);
  });
});

describe("sourceLabel / lineValuePln", () => {
  it("źródła: PDF bez pozycji z kolejnością, PDF bez niczego, brak", () => {
    expect(sourceLabel("manual", { positionLabel: null, ordinal: null })).toBe("wpisano ręcznie");
    expect(sourceLabel("pdf", { positionLabel: null, ordinal: 3 })).toBe("z PDF, 3. osoba w dokumencie");
    expect(sourceLabel("pdf", { positionLabel: null, ordinal: null })).toBe("z PDF");
    expect(sourceLabel(null, { positionLabel: "1", ordinal: 1 })).toBeNull();
  });

  it("wartość: inna waluta, brak MD albo stawki, godzinowa ×8, zero MD", () => {
    expect(lineValuePln(ready({ revenueCurrency: "EUR" }))).toBeNull();
    expect(lineValuePln(ready({ md: "" }))).toBeNull();
    expect(lineValuePln(ready({ rateRevenue: "x" }))).toBeNull();
    expect(lineValuePln(ready({ rateRevenue: "125", revenueUnit: "hour" }))).toBe(20 * 1000);
    expect(lineValuePln(ready({ md: "0" }))).toBe(0);
    expect(lineValuePln(ready({ md: "2,5", rateRevenue: "1000,10" }))).toBeCloseTo(2500.25);
  });
});

describe("splitPlanForGroup / duplicatePersonKeys — brzegi", () => {
  const ln = (id: number, contract_id: number, is_active: boolean, removed = false) => ({
    id,
    contract_id,
    consultant_name: "Jan Testowy",
    is_active,
    cooperation_ended_on: null,
    removed_from_order: removed,
    md_total: null,
    rate_revenue: null,
  });

  it("aktywna linia wygrywa z zakończoną, w obu kolejnościach; usunięta się nie liczy", () => {
    const d = ready();
    expect(splitPlanForGroup([d], [ln(1, 21, false), ln(2, 21, true)]).onOrder[0].line.id).toBe(2);
    expect(splitPlanForGroup([d], [ln(2, 21, true), ln(1, 21, false)]).onOrder[0].line.id).toBe(2);
    expect(splitPlanForGroup([d], [ln(3, 21, true, true)]).toAdd).toEqual([d]);
  });

  it("puste listy", () => {
    expect(splitPlanForGroup([], [])).toEqual({ toAdd: [], onOrder: [] });
    expect(duplicatePersonKeys([])).toEqual(new Set());
  });

  it("ta sama osoba bez kontraktu (po kandydacie) to duplikat; karta bez osoby pomijana", () => {
    const p = { contractId: null, candidateId: 9, name: "Anna Przykładowa", status: null, startDate: null };
    const a = ready({ key: "a", person: p });
    const b = ready({ key: "b", person: p });
    const c = ready({ key: "c", person: null });
    expect(duplicatePersonKeys([a, b, c])).toEqual(new Set(["a", "b"]));
  });
});
