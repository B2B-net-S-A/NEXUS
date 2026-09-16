// Karty konsultantów w oknie „Nowe zamówienie" — czysta logika, bez Reacta.
//
// Odczyt PDF-a (`POST /order-groups/extract`) zwraca jedną pozycję na osobę
// z dokumentu. Tutaj każda pozycja staje się edytowalną kartą, a na końcu —
// linią `OrderLineInput` wysyłaną razem z zamówieniem w JEDNYM `POST`.
//
// Każda wartość karty zna swoje źródło („z kontraktu" / „z PDF, poz. 10" /
// „wpisano ręcznie"): ręczna poprawka zmienia źródło, żeby opis nigdy nie
// twierdził, że liczba pochodzi z dokumentu, kiedy wpisał ją człowiek.

import type {
  ConsultantOption,
  OrderGroupExtraction,
  OrderLineInput,
  OrderLineRead,
  OrderPlanContract,
  OrderPlanLine,
  OrderPlanMatchStatus,
  OrderType,
} from "@/lib/api/orderGroups";
import {
  contractRateUnitToInputUnit,
  toMdRate,
  type RateUnit,
} from "@/lib/rate-unit";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { numberToField } from "@/lib/order-extraction";
import { parseDecimalInput } from "@/lib/utils";

export type LineSource = "contract" | "pdf" | "manual";
/** `manual` = osobę wskazał Delivery Lead (po czerwonej karcie albo z listy). */
export type LineMatch = OrderPlanMatchStatus | "manual";

export interface LinePerson {
  /** `null` = osoba z bazy Nexus bez kontraktu u klienta — zapis go założy. */
  contractId: number | null;
  candidateId: number;
  /** Nazwa dokładnie tak, jak jest w kontrakcie (z dopiskiem). */
  name: string;
  status: string | null;
  startDate: string | null;
}

export interface OrderLineDraft {
  key: string;
  /** Kolejność osoby w dokumencie; `null` = karta dodana ręcznie. */
  ordinal: number | null;
  documentName: string | null;
  positionLabel: string | null;
  match: LineMatch;
  matchReason: string;
  /** Powód z ODCZYTU (np. „kilka osób o tym imieniu") — do powrotu do listy,
   *  gdy wybrany z niej kontrakt okazał się zakończony. */
  planReason: string;
  /** Żółta odznaka wymaga jednego kliknięcia potwierdzenia. */
  confirmed: boolean;
  person: LinePerson | null;
  options: OrderPlanContract[];
  nearestNames: string[];
  rateCost: string;
  costUnit: RateUnit;
  costCurrency: string;
  costSource: LineSource | null;
  rateRevenue: string;
  /** `null` = dokument podał kwotę bez jednostki — DL musi ją wskazać, bo
   *  „zł/h" zapisane jako „zł/MD" to cichy, ośmiokrotny błąd. */
  revenueUnit: RateUnit | null;
  revenueCurrency: string;
  revenueSource: LineSource | null;
  revenueGross: number | null;
  md: string;
  mdSource: LineSource | null;
  /** Zakres opcjonalny MD z umowy (CeZ). Nigdy z PDF-a — zamówienie nie zna
   *  opcji umowy wykonawczej; puste pole = brak opcji. */
  optionalMd: string;
  /** Okres WŁASNY pozycji z PDF-a; `null` = obowiązuje okres zamówienia. */
  startDate: string | null;
  endDate: string | null;
  warnings: string[];
  /** Osoba z PDF-a z ZAKOŃCZONĄ współpracą (`match === "inactive"`): decyzja
   *  Delivery Leada — zostaje na zamówieniu jako historia albo wraca do pracy.
   *  `null` = jeszcze nie zdecydowano (karta nie da się zapisać). */
  inactiveDecision: "history" | "resume" | null;
  /** Koniec kontraktu tej osoby — data końca udziału w zapisie historycznym. */
  contractEndDate: string | null;
  /** Karta jest zastępstwem za tę osobę z dokumentu. */
  replacesName: string | null;
}

export interface OrderPlanContext {
  /** Klient zamówienia — bramka pól istniejących tylko u Centrum e-Zdrowia
   *  (zakres opcjonalny MD z umowy wykonawczej). */
  clientId: number;
  orderType: Exclude<OrderType, "periodic">;
  /** Wspólna pula MD zamówienia — linia nie ma wtedy własnego budżetu MD. */
  sharedMd: boolean;
  groupStart: string;
  groupEnd: string | null;
}

let draftSeq = 0;
function nextKey(): string {
  draftSeq += 1;
  return `line-${draftSeq}`;
}

export function revenueUnitFromDocument(
  unit: OrderPlanLine["rate_revenue_unit"],
): RateUnit | null {
  if (unit === "hour") return "hour";
  if (unit === "month") return "month";
  if (unit === "day") return "md";
  return null;
}

function numberField(value: number | string | null | undefined): string {
  return numberToField(value);
}

/** Stawka kosztowa z kontraktu — pole, jednostka i waluta naraz. */
function costFromContract(
  contract: Pick<
    OrderPlanContract,
    "rate_cost" | "rate_cost_unit" | "rate_cost_currency"
  >,
): Pick<OrderLineDraft, "rateCost" | "costUnit" | "costCurrency" | "costSource"> {
  if (contract.rate_cost === null || contract.rate_cost === undefined) {
    return { rateCost: "", costUnit: "md", costCurrency: "PLN", costSource: null };
  }
  return {
    rateCost: String(contract.rate_cost),
    costUnit: contractRateUnitToInputUnit(contract.rate_cost_unit),
    costCurrency: contract.rate_cost_currency?.trim().toUpperCase() || "PLN",
    costSource: "contract",
  };
}

function personFromContract(contract: OrderPlanContract): LinePerson {
  return {
    contractId: contract.contract_id,
    candidateId: contract.candidate_id,
    name: contract.contractor_name,
    status: contract.status,
    startDate: contract.start_date,
  };
}

/** Karty z odczytu PDF-a — jedna na rozpoznaną osobę. */
export function draftsFromPlan(plan: OrderGroupExtraction): OrderLineDraft[] {
  const currency = plan.currency?.trim().toUpperCase() || "PLN";
  return plan.lines.map((line) => {
    const hasRevenue = line.rate_revenue !== null && line.rate_revenue !== undefined;
    const hasMd = line.md_total !== null && line.md_total !== undefined;
    const matched =
      (line.match_status === "auto" ||
        line.match_status === "confirm" ||
        line.match_status === "inactive") &&
      line.contract !== null;
    return {
      key: nextKey(),
      ordinal: line.ordinal,
      documentName: line.document_name,
      positionLabel: line.position_label,
      match: line.match_status,
      matchReason: line.match_reason,
      planReason: line.match_reason,
      confirmed: line.match_status === "auto",
      person: matched && line.contract ? personFromContract(line.contract) : null,
      options: line.options,
      nearestNames: line.nearest_names,
      ...(matched && line.contract
        ? costFromContract(line.contract)
        : { rateCost: "", costUnit: "md" as RateUnit, costCurrency: "PLN", costSource: null }),
      rateRevenue: numberField(line.rate_revenue),
      // Bez kwoty jednostka nie ma znaczenia — domyślnie MD, jak w formularzu.
      revenueUnit: hasRevenue ? revenueUnitFromDocument(line.rate_revenue_unit) : "md",
      revenueCurrency: currency,
      revenueSource: hasRevenue ? "pdf" : null,
      revenueGross: line.rate_revenue_gross,
      md: numberField(line.md_total),
      mdSource: hasMd ? "pdf" : null,
      optionalMd: "",
      startDate: line.start_date ? line.start_date.slice(0, 10) : null,
      endDate: line.end_date ? line.end_date.slice(0, 10) : null,
      warnings: line.warnings,
      inactiveDecision: null,
      contractEndDate:
        line.match_status === "inactive" && line.contract?.end_date
          ? line.contract.end_date.slice(0, 10)
          : null,
      replacesName: null,
    };
  });
}

/** Pusta karta „Dodaj konsultanta" — osoba i wartości do wskazania. */
export function emptyDraft(): OrderLineDraft {
  return {
    key: nextKey(),
    ordinal: null,
    documentName: null,
    positionLabel: null,
    match: "manual",
    matchReason: "",
    planReason: "",
    confirmed: true,
    person: null,
    options: [],
    nearestNames: [],
    rateCost: "",
    costUnit: "md",
    costCurrency: "PLN",
    costSource: null,
    rateRevenue: "",
    revenueUnit: "md",
    revenueCurrency: "PLN",
    revenueSource: null,
    revenueGross: null,
    md: "",
    mdSource: null,
    optionalMd: "",
    startDate: null,
    endDate: null,
    warnings: [],
    inactiveDecision: null,
    contractEndDate: null,
    replacesName: null,
  };
}

/** Kontrakt wybrany z listy przy „dwóch osobach" — decyzja DL, nie systemu.
 *
 *  Lista bywa mieszana: obok żywego kontraktu stoi zakończony (osoba wraca po
 *  przerwie). Wybór ZAKOŃCZONEGO nie może po cichu wznowić współpracy —
 *  karta przechodzi w to samo pytanie co odznaka „Zakończył współpracę":
 *  zostaw jako historię / wznów / zastąp / usuń. */
export function chooseContract(
  draft: OrderLineDraft,
  contract: OrderPlanContract,
): OrderLineDraft {
  // Stawka kosztowa należy do OSOBY — przy zmianie osoby nie przenosimy ani
  // podpowiedzi, ani ręcznego wpisu poprzedniej (jak w „Dodaj konsultanta").
  const base = {
    ...draft,
    ...costFromContract(contract),
    person: personFromContract(contract),
    inactiveDecision: null,
  };
  if (contract.status === "ended") {
    return {
      ...base,
      match: "inactive",
      // Tekst z serwera (`order_consultant_match`) — jedno źródło komunikatu.
      matchReason:
        contract.inactive_reason ??
        "Ta osoba nie ma już aktywnej współpracy u tego klienta — zdecyduj, co z nią zrobić",
      confirmed: false,
      contractEndDate: contract.end_date ? contract.end_date.slice(0, 10) : null,
    };
  }
  return { ...base, match: "manual", confirmed: true, contractEndDate: null };
}

/** Powrót do listy kontraktów („kilka osób") po wybraniu nie tej pozycji. */
export function backToOptions(draft: OrderLineDraft): OrderLineDraft {
  return {
    ...draft,
    rateCost: "",
    costUnit: "md" as RateUnit,
    costCurrency: "PLN",
    costSource: null,
    match: "ambiguous",
    matchReason: draft.planReason,
    confirmed: false,
    person: null,
    inactiveDecision: null,
    contractEndDate: null,
  };
}

/** Osoba z pickera (kontrakt u klienta albo baza Nexus). */
export function chooseConsultant(
  draft: OrderLineDraft,
  option: ConsultantOption,
): OrderLineDraft {
  const hasRaw =
    option.suggested_contract_rate_cost !== null &&
    option.suggested_contract_rate_cost !== undefined;
  const cost = hasRaw
        ? {
            rateCost: String(option.suggested_contract_rate_cost),
            costUnit: contractRateUnitToInputUnit(option.suggested_rate_cost_unit),
            costCurrency:
              option.suggested_rate_cost_currency?.trim().toUpperCase() || "PLN",
            costSource: "contract" as LineSource,
          }
        : option.suggested_rate_cost !== null &&
            option.suggested_rate_cost !== undefined
          ? {
              rateCost: String(option.suggested_rate_cost),
              costUnit: "md" as RateUnit,
              costCurrency: "PLN",
              costSource: "contract" as LineSource,
            }
          : { rateCost: "", costUnit: "md" as RateUnit, costCurrency: "PLN", costSource: null };
  return {
    ...draft,
    ...cost,
    match: "manual",
    confirmed: true,
    person: {
      contractId: option.contract_id,
      candidateId: option.candidate_id,
      name: option.full_name,
      status: null,
      startDate: null,
    },
    inactiveDecision: null,
    contractEndDate: null,
  };
}

/** „Zastąp kimś innym" — nowa osoba na miejscu osoby z dokumentu. Karta
 *  zapamiętuje, za kogo jest zastępstwem; historia zamówienia pokaże to przy
 *  nowej osobie razem z tym, kto i kiedy ją dodał. */
export function replaceWith(
  draft: OrderLineDraft,
  option: ConsultantOption,
): OrderLineDraft {
  return {
    ...chooseConsultant(draft, option),
    replacesName: draft.replacesName ?? draft.documentName ?? draft.person?.name ?? null,
  };
}

/** „Zostaw jako historię" — osoba z zakończoną współpracą zostaje na
 *  zamówieniu jako zakończona (nie wznawia kontraktu). */
export function keepAsHistory(draft: OrderLineDraft): OrderLineDraft {
  return { ...draft, inactiveDecision: "history", confirmed: true };
}

/** „Wznów współpracę" — to powrót tej osoby; zapis zamówienia wznowi kontrakt. */
export function resumeCooperation(draft: OrderLineDraft): OrderLineDraft {
  return { ...draft, inactiveDecision: "resume", confirmed: true };
}

/** Cofnięcie decyzji przy osobie z zakończoną współpracą. */
export function undoInactiveDecision(draft: OrderLineDraft): OrderLineDraft {
  return { ...draft, inactiveDecision: null, confirmed: false };
}

/** Czy karta zapisze osobę jako zapis historyczny (zakończona linia). */
export function isHistorical(draft: OrderLineDraft): boolean {
  return (
    draft.match === "inactive" &&
    draft.inactiveDecision === "history" &&
    draft.person?.contractId != null
  );
}

/** „To nie on" przy żółtej karcie — dopasowanie odrzucone, osoba do wskazania. */
export function rejectMatch(draft: OrderLineDraft): OrderLineDraft {
  return {
    ...draft,
    rateCost: "",
    costUnit: "md" as RateUnit,
    costCurrency: "PLN",
    costSource: null,
    match: "none",
    matchReason:
      "Odrzucono proponowane dopasowanie — wskaż kontraktora ręcznie",
    confirmed: false,
    person: null,
    inactiveDecision: null,
    contractEndDate: null,
  };
}

/** Czego brakuje, żeby kartę dało się zapisać. Pusta lista = gotowa. */
export function lineIssues(
  draft: OrderLineDraft,
  ctx: OrderPlanContext,
): string[] {
  const issues: string[] = [];
  if (!draft.person) {
    issues.push("wskaż kontraktora");
  } else if (draft.match === "inactive" && !draft.inactiveDecision) {
    issues.push("zdecyduj: zostaw jako historię, wznów, zastąp albo usuń");
  } else if (!draft.confirmed) {
    issues.push("potwierdź dopasowanie");
  }
  if (isHistorical(draft)) {
    const start = draft.startDate ?? ctx.groupStart;
    if (!draft.contractEndDate) {
      issues.push("data zakończenia współpracy");
    } else if (start && draft.contractEndDate < start) {
      issues.push(
        "współpraca skończyła się przed startem zamówienia — wznów albo zastąp",
      );
    }
  }
  if (parseDecimalInput(draft.rateCost) === null) {
    issues.push("stawka kosztowa");
  }
  if ((parseDecimalInput(draft.rateRevenue) ?? 0) <= 0) {
    issues.push("stawka przychodowa");
  } else if (draft.revenueUnit === null) {
    issues.push("jednostka stawki przychodowej");
  }
  if (usesLineMd(ctx) && (parseDecimalInput(draft.md) ?? 0) <= 0) {
    issues.push("liczba MD");
  }
  if (!(draft.startDate ?? ctx.groupStart)) {
    issues.push("data rozpoczęcia");
  }
  return issues;
}

/** Budżet MD per osoba — tylko zwykłe zamówienie MD (nie kosztowe, nie pula). */
export function usesLineMd(ctx: Pick<OrderPlanContext, "orderType" | "sharedMd">): boolean {
  return ctx.orderType === "md" && !ctx.sharedMd;
}

/** Zakres opcjonalny MD przy osobie — własny budżet MD u Centrum e-Zdrowia.
 *  Inni klienci nie mają umów wykonawczych, więc pole u nich nie istnieje
 *  (przegląd adwersarialny 09.2026: pokazywało się każdemu). */
export function usesOptionalMd(
  ctx: Pick<OrderPlanContext, "orderType" | "sharedMd" | "clientId">,
): boolean {
  return usesLineMd(ctx) && isEzdrowieClient(ctx.clientId);
}

/** Linia do `POST /order-groups`. Wołać wyłącznie dla kart bez `lineIssues`. */
export function toLineInput(
  draft: OrderLineDraft,
  ctx: OrderPlanContext,
): OrderLineInput {
  const person = draft.person;
  if (!person) throw new Error("Karta bez wskazanego kontraktora");
  const cost = toMdRate(parseDecimalInput(draft.rateCost) ?? Number.NaN, draft.costUnit);
  if (draft.revenueUnit === null) {
    throw new Error("Karta bez jednostki stawki przychodowej");
  }
  const revenue = toMdRate(
    parseDecimalInput(draft.rateRevenue) ?? Number.NaN,
    draft.revenueUnit,
  );
  if (cost === null || revenue === null) {
    throw new Error("Nieprawidłowa stawka na karcie konsultanta");
  }
  const md = parseDecimalInput(draft.md);
  const optionalMd = parseDecimalInput(draft.optionalMd);
  const historical = isHistorical(draft);
  return {
    // Dokładnie jedno z pól — serwer odrzuca oba naraz.
    ...(person.contractId !== null
      ? { contract_id: person.contractId }
      : { candidate_id: person.candidateId }),
    rate_candidate_currency: draft.costCurrency,
    rate_client_currency: draft.revenueCurrency,
    rate_cost: cost,
    rate_revenue: revenue,
    ...(usesLineMd(ctx) && md !== null
      ? { input_mode: "md" as const, input_value: md }
      : {}),
    // Opcja tylko u CeZ, przy własnym budżecie MD osoby i tylko gdy wpisana —
    // brak klucza to „brak opcji", więc karta bez CeZ nie wysyła `null`.
    ...(usesOptionalMd(ctx) && optionalMd !== null && optionalMd > 0
      ? { optional_md: optionalMd }
      : {}),
    start_date: draft.startDate ?? ctx.groupStart,
    // Zapis historyczny kończy się z końcem współpracy, nie zamówienia.
    end_date: historical ? draft.contractEndDate : (draft.endDate ?? ctx.groupEnd),
    ...(historical ? { historical: true } : {}),
    // Pochodzenie linii: osoba z PDF-a albo zastępstwo za nią — historia
    // zamówienia pokazuje przy zastępcy, kto i kiedy go dodał.
    ...(draft.replacesName
      ? { replaces_name: draft.replacesName }
      : draft.documentName
        ? { document_name: draft.documentName }
        : {}),
  };
}

/** Opis źródła wartości pod liczbą na karcie. */
export function sourceLabel(
  source: LineSource | null,
  draft: Pick<OrderLineDraft, "positionLabel" | "ordinal">,
): string | null {
  if (source === "contract") return "z kontraktu";
  if (source === "manual") return "wpisano ręcznie";
  if (source === "pdf") {
    if (draft.positionLabel) return `z PDF, poz. ${draft.positionLabel}`;
    if (draft.ordinal !== null) return `z PDF, ${draft.ordinal}. osoba w dokumencie`;
    return "z PDF";
  }
  return null;
}

/** Wartość pozycji w PLN (MD × stawka przychodowa za MD) — do podsumowania. */
export function lineValuePln(draft: OrderLineDraft): number | null {
  if (draft.revenueCurrency !== "PLN" || draft.revenueUnit === null) return null;
  const md = parseDecimalInput(draft.md);
  const rate = parseDecimalInput(draft.rateRevenue);
  if (md === null || rate === null) return null;
  const mdRate = toMdRate(rate, draft.revenueUnit);
  return mdRate === null ? null : md * mdRate;
}

/** Osoba z PDF-a, która JUŻ jest na uzupełnianym zamówieniu. */
export interface PersonAlreadyOnOrder {
  draft: OrderLineDraft;
  line: Pick<
    OrderLineRead,
    | "id"
    | "consultant_name"
    | "is_active"
    | "cooperation_ended_on"
    | "md_total"
    | "rate_revenue"
  >;
}

/** „Uzupełnij zamówienie": karty tylko dla osób, których na zamówieniu nie ma.
 *
 *  Osoba z dokumentu dopasowana do kontraktu, który ma już linię na tym
 *  zamówieniu, nie dostaje drugiej karty — decyzje wobec niej (np. zakończona
 *  współpraca) zapadają na karcie zamówienia, przy jej linii. Linia usunięta
 *  z zamówienia nie liczy się jako obecna: nowy PDF, który znów ją wymienia,
 *  to nowa decyzja Delivery Leada. Karty bez wskazanej osoby (kilka osób,
 *  nieznaleziona) zostają zawsze — właśnie o nie ticket pyta. */
export function splitPlanForGroup(
  drafts: OrderLineDraft[],
  lines: Array<
    Pick<
      OrderLineRead,
      | "id"
      | "contract_id"
      | "consultant_name"
      | "is_active"
      | "cooperation_ended_on"
      | "removed_from_order"
      | "md_total"
      | "rate_revenue"
    >
  >,
): { toAdd: OrderLineDraft[]; onOrder: PersonAlreadyOnOrder[] } {
  const byContract = new Map<number, (typeof lines)[number]>();
  for (const line of lines) {
    if (line.removed_from_order) continue;
    const current = byContract.get(line.contract_id);
    // Aktywna linia tej osoby jest ważniejsza niż zakończona sprzed zamiany.
    if (!current || (!current.is_active && line.is_active)) {
      byContract.set(line.contract_id, line);
    }
  }
  const toAdd: OrderLineDraft[] = [];
  const onOrder: PersonAlreadyOnOrder[] = [];
  for (const draft of drafts) {
    const contractId = draft.person?.contractId;
    const line = contractId != null ? byContract.get(contractId) : undefined;
    if (line) {
      onOrder.push({ draft, line });
    } else {
      toAdd.push(draft);
    }
  }
  return { toAdd, onOrder };
}

/** Klucze kart wskazujących tę samą osobę/kontrakt — ostrzeżenie, nie blokada. */
export function duplicatePersonKeys(drafts: OrderLineDraft[]): Set<string> {
  const byPerson = new Map<string, string[]>();
  for (const draft of drafts) {
    if (!draft.person) continue;
    const id =
      draft.person.contractId !== null
        ? `c${draft.person.contractId}`
        : `p${draft.person.candidateId}`;
    byPerson.set(id, [...(byPerson.get(id) ?? []), draft.key]);
  }
  const duplicated = new Set<string>();
  for (const keys of byPerson.values()) {
    if (keys.length > 1) keys.forEach((key) => duplicated.add(key));
  }
  return duplicated;
}
