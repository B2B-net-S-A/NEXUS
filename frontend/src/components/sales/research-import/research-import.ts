// Lista osób z researchu → mapy Fabryk IT: co ekran przeglądu robi z wierszem.
// Stan firmy w NEXUSIE i los osoby liczy backend (services/sales/research_import.py);
// tu jest tylko to, co zależy od wyborów człowieka na ekranie.

import type {
  ResearchCard,
  ResearchCompany,
  ResearchOutcome,
  ResearchPersonInput,
  ResearchPreview,
  ResearchRow,
} from "@/lib/api/sales-research-import";

import { plural } from "../peoplePlural";

export const IMPORT_ACCEPT = ".csv,.xlsx";
export const MIN_SOURCE_CHARS = 3;

/** Karta wskazana przy firmie z kilkoma kartami: id karty albo nowa karta. */
export type CardChoice = number | "new";

/** Konto założone w tej sesji przeglądu: kolejne osoby firmy trafiają na jego mapę. */
export interface CreatedAccount {
  companyId: number;
  opportunityId: number;
}

export type TargetKind = "account" | "card" | "new_company";

export interface Target {
  kind: TargetKind;
  /** `null`: nowa karta firmy albo jedyna karta o tej nazwie. */
  companyId: number | null;
  opportunityId: number | null;
  card: ResearchCard | null;
}

export const ACTION_LABELS: Record<TargetKind, string> = {
  account: "Dodaj do mapy",
  card: "Załóż konto",
  new_company: "Załóż firmę",
};

export const LEVEL_OPTIONS = [
  { value: "1", label: "1 · Zarząd" },
  { value: "2", label: "2 · Dyrektorzy" },
  { value: "3", label: "3 · Kierownicy" },
  { value: "4", label: "4 · Zespół" },
];

function ofCard(card: ResearchCard): Target {
  return {
    kind: card.account ? "account" : "card",
    companyId: card.id,
    opportunityId: card.account?.opportunity_id ?? null,
    card,
  };
}

/** Karty, które da się wskazać: bez klienta NEXUSA i bez „Nie kontaktować”. */
export function selectableCards(company: ResearchCompany): ResearchCard[] {
  return company.cards.filter((card) => !card.client && !card.blocked);
}

/** Nową kartę zakłada się tylko wtedy, gdy żadna karta nie nosi nazwy z pliku. */
export function canCreateCard(company: ResearchCompany): boolean {
  return !company.cards.some((card) => card.exact);
}

/**
 * Gdzie trafi osoba z tej firmy. `null`: nigdzie (klient NEXUSA, „Nie kontaktować”,
 * nasza firma) albo człowiek nie wskazał jeszcze karty.
 */
export function resolveTarget(
  company: ResearchCompany,
  choice: CardChoice | undefined,
  created: CreatedAccount | undefined,
): Target | null {
  if (created) {
    return {
      kind: "account",
      companyId: created.companyId,
      opportunityId: created.opportunityId,
      card: company.cards.find((item) => item.id === created.companyId) ?? null,
    };
  }
  if (company.state === "no_card") return { kind: "new_company", companyId: null, opportunityId: null, card: null };
  if (company.state === "account" || company.state === "card") {
    const card = company.cards.find((item) => item.id === company.company_id);
    return card ? ofCard(card) : null;
  }
  if (company.state !== "choose" || choice === undefined) return null;
  if (choice === "new") {
    return canCreateCard(company) ? { kind: "new_company", companyId: null, opportunityId: null, card: null } : null;
  }
  const card = selectableCards(company).find((item) => item.id === choice);
  return card ? ofCard(card) : null;
}

export type RowPhase =
  /** Osoba dodana w tej sesji. */
  | "added"
  /** Już na mapie albo drugi raz w pliku: nie ma czego dodawać. */
  | "skip"
  /** Firma nie przyjmuje osób: klient NEXUSA, „Nie kontaktować”, nasza firma. */
  | "refused"
  /** Trzeba wskazać kartę firmy. */
  | "choose"
  | "ready";

export function rowPhase(
  row: ResearchRow,
  company: ResearchCompany,
  target: Target | null,
  outcome: ResearchOutcome | undefined,
): RowPhase {
  if (outcome?.result === "added") return "added";
  if (outcome?.result === "on_map" || row.person !== "new") return "skip";
  if (outcome && ["client", "blocked", "own_company"].includes(outcome.result)) return "refused";
  if (["client", "blocked", "own_company"].includes(company.state)) return "refused";
  return target ? "ready" : "choose";
}

export function toInput(row: ResearchRow, level: number, target: Target): ResearchPersonInput {
  return {
    line: row.line,
    company: row.company,
    name: row.name,
    role_in_company: row.role_in_company,
    email: row.email,
    phone: row.phone,
    linkedin_url: row.linkedin_url,
    source_url: row.source_url,
    domain: row.domain,
    notes: row.notes,
    confidence: row.confidence,
    decision_level: level,
    company_id: target.companyId,
  };
}

export function peopleCount(count: number): string {
  return `${count} ${plural(count, "osoba", "osoby", "osób")}`;
}

export function cardsCount(count: number): string {
  return `${count} ${plural(count, "karta", "karty", "kart")} firmy`;
}

export function previewSummary(preview: ResearchPreview): string {
  const confirmed = preview.rows.filter((row) => row.confidence === "confirmed").length;
  const companies = preview.companies.length;
  return [
    `${peopleCount(preview.rows.length)} w ${companies} ${plural(companies, "firmie", "firmach", "firmach")}`,
    `${confirmed} ${plural(confirmed, "pewna", "pewne", "pewnych")}, ${preview.rows.length - confirmed} do weryfikacji`,
    preview.skipped.length > 0
      ? `${preview.skipped.length} ${plural(preview.skipped.length, "wiersz pominięty", "wiersze pominięte", "wierszy pominiętych")}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Co powstanie przy zbiorczej akceptacji: konta i karty liczone raz na firmę. */
export function bulkEffect(items: readonly { row: ResearchRow; target: Target }[]): {
  people: number;
  accounts: number;
  companies: number;
} {
  const accounts = new Set<string>();
  const companies = new Set<string>();
  for (const { row, target } of items) {
    if (target.kind !== "account") accounts.add(row.company_key);
    if (target.kind === "new_company") companies.add(row.company_key);
  }
  return { people: items.length, accounts: accounts.size, companies: companies.size };
}

export function bulkQuestion(effect: ReturnType<typeof bulkEffect>): string {
  const parts = [`Na mapy trafi ${peopleCount(effect.people)} ze statusem „bez kontaktu”.`];
  if (effect.accounts > 0) {
    parts.push(
      `W lejku Fabryki IT powstanie ${effect.accounts} ${plural(effect.accounts, "konto", "konta", "kont")}` +
        (effect.companies > 0
          ? `, a w kartotece ${effect.companies} ${plural(effect.companies, "karta firmy", "karty firm", "kart firm")}.`
          : "."),
    );
  }
  parts.push("Osoby „do weryfikacji” i firmy, w których trzeba wskazać kartę, zostają na liście.");
  return parts.join(" ");
}

/** Nazwa pliku jako początek pola „Skąd lista”; eksport z Cognism mówi „Cognism”. */
export function sourceFromFile(fileName: string, origin?: string | null): string {
  const base = fileName.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  const prefix = origin ?? "Lista z researchu";
  if (!base) return origin ?? "";
  return `${prefix}: ${base}`.slice(0, 255);
}
