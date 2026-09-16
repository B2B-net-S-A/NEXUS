import { describe, expect, it } from "vitest";

import type {
  OrderGroupExtraction,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import type { ConsultantOption } from "@/lib/api/orderGroups";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";
import {
  backToOptions,
  chooseContract,
  draftsFromPlan,
  duplicatePersonKeys,
  emptyDraft,
  isHistorical,
  keepAsHistory,
  lineIssues,
  lineValuePln,
  rejectMatch,
  replaceWith,
  resumeCooperation,
  sourceLabel,
  splitPlanForGroup,
  toLineInput,
  undoInactiveDecision,
  usesOptionalMd,
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
  clientId: 18,
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
      // Pochodzenie linii — historia zamówienia odróżnia osoby z PDF-a od
      // dopisanych ręcznie.
      document_name: "Krzysztof Suwała",
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

// ── Osoba z PDF-a z zakończoną współpracą (ticket 09.2026) ────────────────────

describe("konsultant nieaktywny albo nieznaleziony", () => {
  const cost: OrderPlanContext = {
    clientId: 18,
    orderType: "cost",
    sharedMd: false,
    groupStart: "2026-03-30",
    groupEnd: null,
  };
  const ended = () =>
    draftsFromPlan(
      plan([
        line({
          document_name: "Odeszły Marian",
          match_status: "inactive",
          match_reason: "„Odeszły Marian” nie ma już aktywnej współpracy u tego klienta",
          md_total: null,
          rate_revenue: 1280,
          contract: contract({
            contract_id: 77,
            contractor_name: "Marian Odeszły",
            status: "ended",
            end_date: "2026-08-12",
          }),
        }),
      ]),
    )[0];

  it("karta mówi wprost o zakończonej współpracy i czeka na decyzję", () => {
    const draft = ended();
    expect(draft.person?.contractId).toBe(77);
    expect(draft.confirmed).toBe(false);
    expect(draft.contractEndDate).toBe("2026-08-12");
    expect(lineIssues(draft, cost)).toEqual([
      "zdecyduj: zostaw jako historię, wznów, zastąp albo usuń",
    ]);
  });

  it("„Zostaw jako historię” zapisuje zakończoną linię do końca współpracy", () => {
    const draft = keepAsHistory(ended());
    expect(isHistorical(draft)).toBe(true);
    expect(lineIssues(draft, cost)).toEqual([]);
    expect(toLineInput(draft, cost)).toMatchObject({
      contract_id: 77,
      historical: true,
      start_date: "2026-03-30",
      end_date: "2026-08-12",
      document_name: "Odeszły Marian",
    });
  });

  it("„Wznów współpracę” to zwykła linia na okres zamówienia", () => {
    const input = toLineInput(resumeCooperation(ended()), cost);
    expect(input).not.toHaveProperty("historical");
    expect(input.end_date).toBeNull();
    expect(lineIssues(undoInactiveDecision(resumeCooperation(ended())), cost)).toHaveLength(1);
  });

  it("zapis historyczny sprzed startu zamówienia nie przejdzie", () => {
    const draft = keepAsHistory(ended());
    expect(lineIssues(draft, { ...cost, groupStart: "2026-09-01" })).toEqual([
      "współpraca skończyła się przed startem zamówienia — wznów albo zastąp",
    ]);
  });

  it("„Zastąp kimś innym” zapisuje zastępcę z nazwą osoby z dokumentu", () => {
    const option: ConsultantOption = {
      candidate_id: 505,
      contract_id: 55,
      full_name: "Tadeusz Zastępca",
      first_name: "Tadeusz",
      last_name: "Zastępca",
      source: "client_recruitment",
      source_label: "Rekrutacja u klienta",
      job_title: null,
      suggested_rate_cost: 900,
      has_different_client_contract_rates: false,
    };
    const draft = replaceWith(ended(), option);
    expect(draft.match).toBe("manual");
    expect(draft.replacesName).toBe("Odeszły Marian");
    expect(isHistorical(draft)).toBe(false);
    const input = toLineInput(draft, cost);
    expect(input).toMatchObject({ contract_id: 55, replaces_name: "Odeszły Marian" });
    expect(input).not.toHaveProperty("document_name");
    expect(input).not.toHaveProperty("historical");
  });
});

describe("ta sama decyzja na każdej ścieżce wyboru osoby", () => {
  const cost: OrderPlanContext = {
    clientId: 18,
    orderType: "cost",
    sharedMd: false,
    groupStart: "2026-03-30",
    groupEnd: null,
  };
  const ambiguous = () =>
    draftsFromPlan(
      plan([
        line({
          document_name: "Jan Powrotny",
          match_status: "ambiguous",
          match_reason: "Znaleziono 2 różne osoby o tym imieniu i nazwisku",
          contract: null,
          options: [
            contract({ contract_id: 21, contractor_name: "Jan Powrotny" }),
            contract({
              contract_id: 22,
              candidate_id: 202,
              contractor_name: "Jan Powrotny",
              status: "ended",
              end_date: "2026-06-30",
              inactive_reason:
                "„Jan Powrotny” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 30.06.2026). Zdecyduj: …",
            }),
          ],
        }),
      ]),
    )[0];

  it("wybór ZAKOŃCZONEGO kontraktu z listy nie wznawia go po cichu", () => {
    const options = ambiguous().options;
    const draft = chooseContract(ambiguous(), options[1]);
    expect(draft.match).toBe("inactive");
    expect(draft.matchReason).toContain("nie ma już aktywnej współpracy");
    expect(draft.contractEndDate).toBe("2026-06-30");
    expect(lineIssues(draft, cost)).toEqual([
      "zdecyduj: zostaw jako historię, wznów, zastąp albo usuń",
    ]);
    expect(toLineInput(keepAsHistory(draft), cost)).toMatchObject({
      contract_id: 22,
      historical: true,
      end_date: "2026-06-30",
    });
  });

  it("wybór żywego kontraktu z listy to zwykłe wskazanie ręczne", () => {
    const draft = chooseContract(ambiguous(), ambiguous().options[0]);
    expect(draft.match).toBe("manual");
    expect(lineIssues(draft, cost)).toEqual([]);
  });

  it("z pytania o zakończoną współpracę można wrócić do listy osób", () => {
    const original = ambiguous();
    const back = backToOptions(chooseContract(original, original.options[1]));
    expect(back.person).toBeNull();
    expect(back.match).toBe("ambiguous");
    expect(back.matchReason).toBe(original.matchReason);
    expect(back.rateCost).toBe("");
  });
});

describe("„Uzupełnij zamówienie” — karty tylko dla osób spoza zamówienia", () => {
  const drafts = () =>
    draftsFromPlan(
      plan([
        line({ document_name: "Jest Na Zamówieniu", contract: contract({ contract_id: 31 }) }),
        line({
          document_name: "Nowa Osoba",
          contract: contract({ contract_id: 32, candidate_id: 302 }),
        }),
        line({ document_name: "Nikt Nieznany", match_status: "none", contract: null }),
        line({
          document_name: "Usunięta Wcześniej",
          contract: contract({ contract_id: 33, candidate_id: 303 }),
        }),
      ]),
    );
  const orderLines = [
    {
      id: 1,
      contract_id: 31,
      consultant_name: "Jest Na Zamówieniu",
      is_active: true,
      cooperation_ended_on: null,
      removed_from_order: false,
      md_total: null,
      rate_revenue: null,
    },
    {
      id: 2,
      contract_id: 33,
      consultant_name: "Usunięta Wcześniej",
      is_active: false,
      cooperation_ended_on: null,
      removed_from_order: true,
      md_total: null,
      rate_revenue: null,
    },
  ];

  it("osoba już na zamówieniu nie dostaje drugiej karty", () => {
    const { toAdd, onOrder } = splitPlanForGroup(drafts(), orderLines);
    expect(onOrder.map((item) => item.line.id)).toEqual([1]);
    expect(toAdd.map((draft) => draft.documentName)).toEqual([
      "Nowa Osoba",
      "Nikt Nieznany",
      "Usunięta Wcześniej",
    ]);
  });
});

describe("zakres opcjonalny MD (CeZ) na karcie", () => {
  const cez: OrderPlanContext = { ...md, clientId: EZDROWIE_CLIENT_ID };

  it("karta z PDF-a nie zgaduje opcji — pole puste, klucz `optional_md` nie jedzie", () => {
    const [draft] = draftsFromPlan(plan([line()]));
    expect(draft.optionalMd).toBe("");
    expect(emptyDraft().optionalMd).toBe("");
    expect(toLineInput(draft, cez)).not.toHaveProperty("optional_md");
  });

  it("wpisana opcja jedzie obok podstawy, ale tylko u CeZ i przy własnym budżecie MD osoby", () => {
    const [draft] = draftsFromPlan(plan([line()]));
    const withOption = { ...draft, optionalMd: "170" };
    expect(usesOptionalMd(cez)).toBe(true);
    expect(toLineInput(withOption, cez)).toMatchObject({
      input_mode: "md",
      input_value: 35,
      optional_md: 170,
    });
    // Klient spoza CeZ nie ma umów wykonawczych — pola nie ma i nic nie jedzie,
    // nawet gdy stan karty niesie wartość (przegląd adwersarialny 09.2026).
    expect(usesOptionalMd(md)).toBe(false);
    expect(toLineInput(withOption, md)).not.toHaveProperty("optional_md");
    // Zamówienie kosztowe i wspólna pula nie mają budżetu przy osobie —
    // opcja nie ma się do czego doliczyć.
    expect(toLineInput(withOption, { ...cez, orderType: "cost" })).not.toHaveProperty("optional_md");
    expect(toLineInput(withOption, { ...cez, sharedMd: true })).not.toHaveProperty("optional_md");
    // Zero to „brak opcji", nie opcja o wielkości zero.
    expect(toLineInput({ ...draft, optionalMd: "0" }, cez)).not.toHaveProperty("optional_md");
  });
});
