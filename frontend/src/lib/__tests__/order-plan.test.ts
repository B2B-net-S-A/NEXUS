import { describe, expect, it } from "vitest";

import type {
  OrderGroupExtraction,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import {
  chooseContract,
  draftsFromPlan,
  duplicatePersonKeys,
  emptyDraft,
  lineIssues,
  lineValuePln,
  rejectMatch,
  sourceLabel,
  toLineInput,
  type OrderPlanContext,
} from "@/lib/order-plan";

function contract(overrides: Partial<OrderPlanContract> = {}): OrderPlanContract {
  return {
    contract_id: 11,
    candidate_id: 101,
    contractor_name: "Krzysztof Suwała",
    status: "active",
    start_date: "2025-06-01",
    end_date: null,
    rate_cost: 148.75,
    rate_cost_unit: "daily",
    rate_cost_currency: "PLN",
    rate_cost_rate_to_pln: 1,
    rate_cost_per_md_pln: 148.75,
    ...overrides,
  };
}

function line(overrides: Partial<OrderPlanLine> = {}): OrderPlanLine {
  return {
    ordinal: 1,
    document_name: "Krzysztof Suwała",
    position_label: "10",
    rate_revenue: 1080,
    rate_revenue_unit: "day",
    rate_revenue_gross: null,
    md_total: 35,
    start_date: null,
    end_date: null,
    match_status: "auto",
    match_reason: "Zapis identyczny z dokumentem",
    contract: contract(),
    options: [],
    nearest_names: [],
    warnings: [],
    ...overrides,
  };
}

function plan(lines: OrderPlanLine[]): OrderGroupExtraction {
  return {
    order_number: "4500030845",
    start_date: "2026-09-03",
    end_date: null,
    total_value: 91560,
    currency: "PLN",
    md_total: null,
    suggested_order_type: "md",
    client_policy: null,
    consultant_ref: null,
    title_needs_review: false,
    document_incomplete: false,
    uncertain: false,
    uncertain_reasons: [],
    lines,
  };
}

const md: OrderPlanContext = {
  orderType: "md",
  sharedMd: false,
  groupStart: "2026-09-03",
  groupEnd: null,
};

describe("karty konsultantów z odczytu PDF-a", () => {
  it("automatyczne dopasowanie wypełnia osobę, koszt z kontraktu i PDF-owe MD", () => {
    const [draft] = draftsFromPlan(plan([line()]));

    expect(draft.person?.contractId).toBe(11);
    expect(draft.confirmed).toBe(true);
    expect(draft.rateCost).toBe("148.75");
    expect(sourceLabel(draft.costSource, draft)).toBe("z kontraktu");
    expect(draft.rateRevenue).toBe("1080");
    expect(sourceLabel(draft.revenueSource, draft)).toBe("z PDF, poz. 10");
    expect(sourceLabel(draft.mdSource, draft)).toBe("z PDF, poz. 10");
    expect(lineIssues(draft, md)).toEqual([]);
  });

  it("żółta karta czeka na jedno kliknięcie potwierdzenia", () => {
    const [draft] = draftsFromPlan(
      plan([
        line({
          match_status: "confirm",
          contract: contract({ contractor_name: "Active Paweł Łaski" }),
        }),
      ]),
    );

    expect(draft.person?.name).toBe("Active Paweł Łaski");
    expect(lineIssues(draft, md)).toEqual(["potwierdź dopasowanie"]);
    expect(lineIssues({ ...draft, confirmed: true }, md)).toEqual([]);
  });

  it("czerwona karta nie ma osoby ani stawki z cudzego kontraktu", () => {
    const [draft] = draftsFromPlan(
      plan([
        line({
          match_status: "none",
          contract: null,
          nearest_names: ["Jan Kowalczyk"],
        }),
      ]),
    );

    expect(draft.person).toBeNull();
    expect(draft.rateCost).toBe("");
    expect(draft.nearestNames).toEqual(["Jan Kowalczyk"]);
    expect(lineIssues(draft, md)).toContain("wskaż kontraktora");
  });

  it("przy dwóch osobach wybór kontraktu z listy uzupełnia koszt tej osoby", () => {
    const options = [
      contract({ contract_id: 21, candidate_id: 201, rate_cost: 120 }),
      contract({ contract_id: 22, candidate_id: 202, rate_cost: 150 }),
    ];
    const [draft] = draftsFromPlan(
      plan([line({ match_status: "ambiguous", contract: null, options })]),
    );
    expect(draft.person).toBeNull();

    const chosen = chooseContract(draft, options[1]);
    expect(chosen.person?.contractId).toBe(22);
    expect(chosen.rateCost).toBe("150");
    expect(chosen.match).toBe("manual");
    expect(lineIssues(chosen, md)).toEqual([]);
  });

  it("„To nie ta osoba” zdejmuje osobę i koszt pobrany z jej kontraktu", () => {
    const [draft] = draftsFromPlan(plan([line({ match_status: "confirm" })]));
    const rejected = rejectMatch(draft);

    expect(rejected.person).toBeNull();
    expect(rejected.rateCost).toBe("");
    expect(rejected.rateRevenue).toBe("1080");
  });

  it("linia do zapisu zawsze niesie stawki w zł/MD i MD osoby", () => {
    const [draft] = draftsFromPlan(
      plan([
        line({
          rate_revenue: 135,
          rate_revenue_unit: "hour",
          contract: contract({ rate_cost: 20, rate_cost_unit: "hourly" }),
        }),
      ]),
    );

    expect(toLineInput(draft, md)).toEqual({
      contract_id: 11,
      rate_candidate_currency: "PLN",
      rate_client_currency: "PLN",
      rate_cost: 160,
      rate_revenue: 1080,
      input_mode: "md",
      input_value: 35,
      start_date: "2026-09-03",
      end_date: null,
    });
  });

  it("zamówienie kosztowe nie wysyła budżetu MD przy osobie", () => {
    const [draft] = draftsFromPlan(plan([line()]));
    const input = toLineInput(draft, { ...md, orderType: "cost" });

    expect(input).not.toHaveProperty("input_mode");
    expect(input).not.toHaveProperty("input_value");
    expect(lineIssues({ ...draft, md: "" }, { ...md, orderType: "cost" })).toEqual([]);
  });

  it("okres własny pozycji z PDF-a wygrywa z okresem zamówienia", () => {
    const [draft] = draftsFromPlan(
      plan([line({ start_date: "2026-10-01", end_date: "2026-12-31" })]),
    );
    const input = toLineInput(draft, md);

    expect(input.start_date).toBe("2026-10-01");
    expect(input.end_date).toBe("2026-12-31");
  });

  it("osoba z bazy Nexus bez kontraktu jedzie jako candidate_id", () => {
    const draft = {
      ...emptyDraft(),
      person: {
        contractId: null,
        candidateId: 555,
        name: "Anna Nowak",
        status: null,
        startDate: null,
      },
      rateCost: "100",
      rateRevenue: "900",
      md: "10",
    };
    const input = toLineInput(draft, md);

    expect(input).toMatchObject({ candidate_id: 555 });
    expect(input).not.toHaveProperty("contract_id");
  });

  it("wartość zamówienia to MD × stawka za MD, a duplikat osoby jest oznaczony", () => {
    const drafts = draftsFromPlan(
      plan([
        line(),
        line({
          ordinal: 2,
          position_label: "20",
          rate_revenue: 1280,
          md_total: 42,
        }),
      ]),
    );

    expect(drafts.reduce((sum, item) => sum + (lineValuePln(item) ?? 0), 0)).toBe(
      91560,
    );
    expect(duplicatePersonKeys(drafts).size).toBe(2);
  });

  it("brak numeru pozycji opisuje źródło kolejnością osoby", () => {
    const [draft] = draftsFromPlan(plan([line({ position_label: null, ordinal: 2 })]));
    expect(sourceLabel("pdf", draft)).toBe("z PDF, 2. osoba w dokumencie");
    expect(sourceLabel("manual", draft)).toBe("wpisano ręcznie");
  });

  it("stawka bez jednostki w PDF-ie blokuje zapis, aż DL wskaże jednostkę", () => {
    const [draft] = draftsFromPlan(plan([line({ rate_revenue_unit: null })]));

    expect(draft.revenueUnit).toBeNull();
    expect(lineIssues(draft, md)).toEqual(["jednostka stawki przychodowej"]);
    expect(lineValuePln(draft)).toBeNull();
    expect(lineIssues({ ...draft, revenueUnit: "hour" }, md)).toEqual([]);
  });

  it("zmiana osoby nie przenosi ręcznie wpisanej stawki kosztowej poprzedniej", () => {
    const options = [contract({ contract_id: 41, candidate_id: 401, rate_cost: 130 })];
    const [draft] = draftsFromPlan(
      plan([line({ match_status: "ambiguous", contract: null, options })]),
    );
    const typed = { ...draft, rateCost: "999", costSource: "manual" as const };

    expect(chooseContract(typed, options[0]).rateCost).toBe("130");
    expect(rejectMatch(typed).rateCost).toBe("");
  });
});
