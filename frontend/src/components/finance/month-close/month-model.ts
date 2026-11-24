// Model ekranu „Przebieg miesiąca” po makietach 24.11.2026: cztery odpowiedzi
// (co zrobił automat, co jest źle, czego brakuje, faktury do klientów) i pięć
// kroków osoby — tych samych dla kontraktorów u klientów i dla biura.
// Czyste funkcje; liczby biorą się z `month_close.stage_counts` w backendzie.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  MonthCloseClient,
  MonthCloseOverview,
  MonthCloseReason,
  MonthCloseReasonLevel,
  MonthCloseStages,
  SettlementRow,
  TeamMonth,
  TeamMonthPerson,
} from "@/lib/api/client-settlements";

import { shortDay } from "../settlements/format";

/** Stan kroku w wierszu: zrobione, uwaga, błąd, ruch Finansów, czekamy na kogoś, nie dotyczy. */
export type StepTone = "done" | "warn" | "fail" | "todo" | "wait" | "na";

export const STEP_DOT: Record<StepTone, StatusDotTone> = {
  done: "success",
  warn: "warning",
  fail: "danger",
  todo: "info",
  wait: "neutral",
  na: "neutral",
};

export interface Step {
  tone: StepTone;
  label: string;
  note?: string;
}

export interface Segment {
  n: number;
  tone: StepTone;
  title: string;
}

/** Kolejność kroków — nagłówki kolumn tabeli. */
export const STEPS = [
  { key: "report", label: "Raport" },
  { key: "check", label: "Kontrola" },
  { key: "accept", label: "Przyjęcie" },
  { key: "contractor", label: "Faktura od osoby" },
  { key: "client", label: "Faktura do klienta" },
] as const;

const EMPTY: MonthCloseStages = {
  people: 0,
  report: { in: 0, missing: 0, md_auto: 0, md_manual: 0 },
  check: { clean: 0, auto_clean: 0, resolved: 0, warn: 0, fail: 0, returned: 0, unread: 0, no_md: 0, missing: 0 },
  accept: { done: 0, auto: 0, ready: 0 },
  contractor_invoice: { match: 0, differs: 0, nip: 0, can_issue: 0, none: 0, waiting: 0 },
  client_invoice: { issued: 0, ready: 0, waiting_client: 0, waiting: 0, issued_early: 0 },
  missing_order: 0,
};

export function stagesOf(c: Pick<MonthCloseClient, "stages"> | Pick<MonthCloseOverview, "stages">): MonthCloseStages {
  return c.stages ?? EMPTY;
}

// ---------------------------------------------------------------- odpowiedzi

export interface AutomatAnswer {
  people: number;
  clean: number;
  pct: number;
  steps: { label: string; value: number; of: number; note?: string }[];
}

/**
 * „Co zrobił automat”: osoby, które przeszły raport → MD z pliku → reguły bez
 * uwag bez człowieka. MD wpisane ręcznie i uwagi przyjęte przez Finanse się
 * nie liczą (`check.auto_clean`).
 */
export function automatAnswer(data: MonthCloseOverview, team: TeamMonth | null): AutomatAnswer {
  const s = stagesOf(data);
  const planned = data.clients.reduce((acc, c) => acc + (c.auto_accept?.count ?? 0), 0);
  const ksef = s.contractor_invoice.match + s.contractor_invoice.differs + s.contractor_invoice.nip;
  const steps: AutomatAnswer["steps"] = [
    { label: "Raport wczytany", value: s.report.in, of: s.people },
    {
      label: "MD odczytane z pliku",
      value: s.report.md_auto,
      of: s.report.in,
      note: s.report.md_manual ? `${s.report.md_manual} wpisały Finanse` : undefined,
    },
    { label: "Reguły bez uwag", value: s.check.auto_clean, of: s.report.md_auto },
    {
      label: planned ? `Przyjął sam · przyjmie ${planned}` : "Przyjął sam · reguła wył.",
      value: s.accept.auto,
      of: s.check.auto_clean,
      note: "Reguła „Przyjmuj RCP bez uwag automatycznie”",
    },
    {
      label: "KSeF: faktury kontraktorów",
      value: ksef,
      of: s.people,
      note: `${s.contractor_invoice.match} zgodnych z RCP`,
    },
  ];
  if (team && team.people.length) {
    const found = team.people.filter((p) => p.invoice === "in_ksef" || p.invoice === "differs").length;
    steps.push({ label: "KSeF: faktury biura", value: found, of: team.people.length });
  }
  return {
    people: s.people,
    clean: s.check.auto_clean,
    pct: s.people ? Math.round((s.check.auto_clean / s.people) * 100) : 0,
    steps,
  };
}

export interface ProblemLine {
  level: MonthCloseReasonLevel;
  label: string;
  hint: string;
  count: number;
}

export const LEVEL_LOOK: Record<MonthCloseReasonLevel, { tone: StepTone; label: string; hint: string }> = {
  fail: { tone: "fail", label: "Błędy", hint: "reguła blokuje przyjęcie" },
  warn: { tone: "warn", label: "Uwagi", hint: "do przyjęcia na karcie osoby" },
  unread: { tone: "todo", label: "Plik nieodczytany", hint: "NEXUS nie odczytał MD — wpisz ręcznie" },
  order: { tone: "fail", label: "Zamówienie bez MD", hint: "nowe zamówienie albo wyjątek" },
  returned: { tone: "wait", label: "Odesłane do poprawy", hint: "czeka na konsultanta" },
  missing: { tone: "wait", label: "Brak raportu", hint: "nie ma go w poczcie rozliczeń" },
};

/** „Co jest źle”: sprawy, które czekają na decyzję albo poprawkę (bez braków raportu). */
export function problemLines(s: MonthCloseStages): ProblemLine[] {
  const lines: [MonthCloseReasonLevel, number][] = [
    ["fail", s.check.fail],
    ["warn", s.check.warn],
    ["unread", s.check.unread],
    ["order", s.check.no_md],
    ["returned", s.check.returned],
  ];
  return lines.map(([level, count]) => ({ level, count, label: LEVEL_LOOK[level].label, hint: LEVEL_LOOK[level].hint }));
}

export function problemTotal(s: MonthCloseStages): number {
  return s.check.fail + s.check.warn + s.check.unread + s.check.no_md + s.check.returned;
}

/** Najczęstsze powody spraw (bez braku raportu), z rodzajem. */
export function topProblems(reasons: MonthCloseReason[], limit = 3): MonthCloseReason[] {
  return reasons.filter((r) => r.key !== "missing" && r.level !== "missing").slice(0, limit);
}

export interface ClientInvoiceLook {
  key: "issued" | "partial" | "ready" | "client" | "blocked" | "report";
  tone: StepTone;
  label: string;
  note?: string;
}

/** Stan faktury do klienta za miesiąc — jedna etykieta na klienta. */
export function clientInvoiceLook(c: MonthCloseClient): ClientInvoiceLook {
  if (c.client_report) return { key: "report", tone: "wait", label: "Z raportu klienta", note: "T4T" };
  const s = stagesOf(c);
  const early = s.client_invoice.issued_early;
  const earlyNote = early ? `${early} przed przyjęciem RCP` : undefined;
  if (s.client_invoice.issued && s.client_invoice.issued >= s.people)
    return { key: "issued", tone: "done", label: "Wystawiona", note: earlyNote ?? `${s.people} os.` };
  if (s.client_invoice.issued)
    return {
      key: "partial",
      tone: early ? "warn" : "todo",
      label: `Wystawiona ${s.client_invoice.issued} z ${s.people}`,
      note: earlyNote,
    };
  if (s.client_invoice.ready)
    return { key: "ready", tone: "todo", label: "Do wystawienia", note: `${s.client_invoice.ready} os. przyjętych` };
  if (s.client_invoice.waiting_client)
    return { key: "client", tone: "wait", label: "Czeka na klienta", note: "podpis albo akceptacja" };
  const open = s.people - s.accept.done;
  return { key: "blocked", tone: "wait", label: "Wstrzymana", note: `${open} RCP nieprzyjętych` };
}

export interface InvoiceAnswer {
  clients: number;
  counts: Record<ClientInvoiceLook["key"], number>;
  issuedPeople: number;
  issuedEarly: number;
}

/** „Faktury do klientów”: klienci wg stanu faktury za miesiąc. */
export function invoiceAnswer(data: MonthCloseOverview): InvoiceAnswer {
  const counts: InvoiceAnswer["counts"] = { issued: 0, partial: 0, ready: 0, client: 0, blocked: 0, report: 0 };
  for (const c of data.clients) counts[clientInvoiceLook(c).key] += 1;
  const s = stagesOf(data);
  return {
    clients: data.clients.length,
    counts,
    issuedPeople: s.client_invoice.issued,
    issuedEarly: s.client_invoice.issued_early,
  };
}

export interface MissingAnswer {
  reports: number;
  reportClients: number;
  orders: number;
  teamTimesheets: number | null;
  teamInvoices: number | null;
  teamNip: number | null;
}

/** „Czego brakuje”: dokumenty, bez których krok nie ruszy. */
export function missingAnswer(data: MonthCloseOverview, team: TeamMonth | null): MissingAnswer {
  const s = stagesOf(data);
  return {
    reports: s.report.missing,
    reportClients: data.clients.filter((c) => !c.client_report && stagesOf(c).report.missing > 0).length,
    orders: s.missing_order,
    teamTimesheets: team ? team.people.filter((p) => p.timesheet === "missing" || p.timesheet === "draft").length : null,
    teamInvoices: team ? team.people.filter((p) => p.invoice === "missing").length : null,
    teamNip: team ? team.people.filter((p) => p.invoice === "no_nip").length : null,
  };
}

// --------------------------------------------------------------- kto teraz

export interface Move {
  who: string;
  count: number;
  tone: StepTone;
}

/** Czyj ruch w kliencie: najpierw nasze sprawy, potem ludzie, na których czekamy. */
export function clientMoves(s: MonthCloseStages): Move[] {
  const finance =
    s.check.fail + s.check.warn + s.check.unread + s.accept.ready + s.client_invoice.ready +
    s.contractor_invoice.differs + s.contractor_invoice.nip;
  const moves: Move[] = [];
  if (finance) moves.push({ who: "Finanse", count: finance, tone: s.check.fail ? "fail" : "todo" });
  const consultants = s.report.missing + s.check.returned + s.contractor_invoice.waiting;
  if (consultants) moves.push({ who: "Konsultanci", count: consultants, tone: "wait" });
  if (s.check.no_md) moves.push({ who: "Opiekun", count: s.check.no_md, tone: "fail" });
  if (s.client_invoice.waiting_client) moves.push({ who: "Klient", count: s.client_invoice.waiting_client, tone: "wait" });
  return moves;
}

// --------------------------------------------------------- kroki jednej osoby

export interface PersonSteps {
  report: Step;
  check: Step;
  accept: Step;
  contractor: Step;
  client: Step;
  who: Step;
}

const NA: Step = { tone: "na", label: "—" };

/** Pięć kroków kontraktora u klienta z wiersza `month_view`. */
export function personSteps(r: SettlementRow): PersonSteps {
  const accepted = r.status === "accepted";
  const report: Step = r.status === "missing" ? { tone: "wait", label: "Brak", note: "nie ma w poczcie" } : { tone: "done", label: "Jest" };

  let check: Step = NA;
  if (r.status === "checking") check = { tone: "todo", label: "Nieodczytany", note: "wpisz MD z pliku" };
  else if (r.status === "no_md") check = { tone: "fail", label: "Zamówienie bez MD", note: r.issues ?? undefined };
  else if (r.status === "needs_fix") check = { tone: "wait", label: "Odesłane", note: r.issues ?? undefined };
  else if (r.status === "warnings")
    check =
      r.issue_level === "fail"
        ? { tone: "fail", label: "Błąd", note: r.issues ?? "reguła blokuje przyjęcie" }
        : { tone: "warn", label: "Uwaga", note: r.issues ?? "bez opisu — otwórz kartę" };
  else if (accepted && r.accepted_issue) check = { tone: "done", label: "Przyjęte z uwagą", note: "rozstrzygnęły Finanse" };
  else if (r.status === "ok" || accepted) check = { tone: "done", label: "Bez uwag" };

  let accept: Step = NA;
  if (accepted) accept = { tone: "done", label: r.accepted_auto ? "Przyjął automat" : "Przyjęte" };
  else if (r.status === "ok") accept = { tone: "todo", label: "Do przyjęcia" };
  else if (r.status === "warnings" && r.issue_level !== "fail") accept = { tone: "todo", label: "Po decyzji" };

  const contractorMap: Record<SettlementRow["contractor_invoice"], Step> = {
    none: accepted ? { tone: "wait", label: "Czeka na fakturę" } : { tone: "na", label: "Po przyjęciu" },
    can_issue: { tone: "wait", label: "Może wystawić" },
    in_ksef: { tone: "done", label: "W KSeF, zgodna" },
    differs: { tone: "fail", label: "Inna kwota" },
    nip_check: { tone: "warn", label: "NIP do zatwierdzenia" },
    extra_pending: { tone: "warn", label: "Czeka na dodatek" },
  };
  const contractor = contractorMap[r.contractor_invoice];

  const clientMap: Record<SettlementRow["client_invoice"], Step> = {
    waiting: { tone: "na", label: "Czeka" },
    ready: { tone: "todo", label: "Do wystawienia" },
    issued: accepted ? { tone: "done", label: "Wystawiona" } : { tone: "warn", label: "Wystawiona", note: "przed przyjęciem RCP" },
    awaiting_signature: { tone: "wait", label: "Czeka na podpis" },
    awaiting_client: { tone: "wait", label: "Czeka na klienta" },
    awaiting_t4t: { tone: "wait", label: "Czeka na T4T" },
  };
  const client = clientMap[r.client_invoice];

  let who: Step = { tone: "done", label: "Zamknięte" };
  if (r.status === "missing") who = { tone: "wait", label: "Konsultant", note: "raport" };
  else if (r.status === "checking") who = { tone: "todo", label: "Finanse", note: "wpisz MD" };
  else if (r.status === "no_md") who = { tone: "fail", label: "Opiekun", note: "zamówienie" };
  else if (r.status === "needs_fix") who = { tone: "wait", label: "Konsultant", note: "poprawka" };
  else if (r.status === "warnings") who = { tone: r.issue_level === "fail" ? "fail" : "warn", label: "Finanse", note: "decyzja" };
  else if (r.status === "ok") who = { tone: "todo", label: "Finanse", note: "przyjmij" };
  else if (r.contractor_invoice === "differs" || r.contractor_invoice === "nip_check") who = { tone: "warn", label: "Finanse", note: "faktura" };
  // Po przyjęciu dwie drogi naraz: nasza faktura do klienta i faktura konsultanta.
  // Najpierw nasz ruch — tak samo liczy wiersz klienta (`clientMoves`).
  else if (r.client_invoice === "ready") who = { tone: "todo", label: "Finanse", note: "wystaw" };
  else if (r.contractor_invoice === "none" || r.contractor_invoice === "can_issue") who = { tone: "wait", label: "Konsultant", note: "faktura" };
  else if (r.client_invoice !== "issued") who = { tone: "wait", label: "Klient" };
  return { report, check, accept, contractor, client, who };
}

/** Pięć kroków osoby z biura: ewidencja zamiast RCP, bez faktury do klienta. */
export function teamSteps(p: TeamMonthPerson): PersonSteps {
  const report: Step =
    p.timesheet === "missing"
      ? { tone: "wait", label: "Brak ewidencji" }
      : p.timesheet === "draft"
        ? { tone: "wait", label: "Szkic" }
        : p.timesheet === "returned"
          ? { tone: "warn", label: "Zwrócona" }
          : { tone: "done", label: "Ewidencja" };
  const accept: Step =
    p.timesheet === "approved"
      ? { tone: "done", label: "Zatwierdzona", note: shortDay(p.timesheet_on) || undefined }
      : p.timesheet === "submitted"
        ? { tone: "todo", label: "Do zatwierdzenia", note: "przełożony" }
        : NA;
  const contractor: Step =
    p.invoice === "no_nip"
      ? { tone: "fail", label: "Brak NIP-u", note: "uzupełnij w Ludziach" }
      : p.invoice === "missing"
      ? { tone: "wait", label: "Brak faktury" }
      : p.invoice === "differs"
        ? { tone: "fail", label: "Inna kwota" }
        : {
            tone: "done",
            label: `W KSeF ${shortDay(p.invoice_on)}`.trim(),
            note: p.paid ? `zapłacona ${shortDay(p.paid_on)}`.trim() : "do zapłaty",
          };
  let who: Step = { tone: "done", label: "Zamknięte" };
  if (p.timesheet === "missing" || p.timesheet === "draft") who = { tone: "wait", label: "Osoba", note: "ewidencja" };
  else if (p.timesheet === "submitted") who = { tone: "todo", label: "Przełożony", note: "zatwierdź" };
  else if (p.invoice === "no_nip") who = { tone: "fail", label: "Płace", note: "NIP osoby" };
  else if (p.invoice === "missing") who = { tone: "wait", label: "Osoba", note: "faktura" };
  else if (p.invoice === "differs") who = { tone: "fail", label: "Finanse", note: "kwota" };
  else if (!p.paid) who = { tone: "todo", label: "Finanse", note: "zapłata" };
  return {
    report,
    check: { tone: "na", label: "—" },
    accept,
    contractor,
    client: { tone: "na", label: "Nie dotyczy", note: "klientem jesteśmy my" },
    who,
  };
}

export interface TeamSummary {
  people: number;
  timesheets: number;
  approved: number;
  invoices: number;
  differs: number;
  paid: number;
  /** Osoby bez NIP-u w „Danych do rozliczeń” — faktur z KSeF nie da się im przypiąć. */
  noNip: number;
}

export function teamSummary(team: TeamMonth): TeamSummary {
  const p = team.people;
  return {
    people: p.length,
    timesheets: p.filter((x) => x.timesheet !== "missing" && x.timesheet !== "draft").length,
    approved: p.filter((x) => x.timesheet === "approved").length,
    invoices: p.filter((x) => x.invoice === "in_ksef" || x.invoice === "differs").length,
    differs: p.filter((x) => x.invoice === "differs").length,
    paid: p.filter((x) => x.paid).length,
    noNip: p.filter((x) => x.invoice === "no_nip").length,
  };
}

export function teamMoves(t: TeamSummary): Move[] {
  const moves: Move[] = [];
  const toPay = t.invoices - t.differs - t.paid;
  if (toPay + t.differs) moves.push({ who: "Finanse", count: toPay + t.differs, tone: t.differs ? "fail" : "todo" });
  if (t.noNip) moves.push({ who: "Płace (NIP)", count: t.noNip, tone: "fail" });
  if (t.people - t.invoices - t.noNip) moves.push({ who: "Osoby", count: t.people - t.invoices - t.noNip, tone: "wait" });
  if (t.timesheets - t.approved) moves.push({ who: "Przełożeni", count: t.timesheets - t.approved, tone: "wait" });
  return moves;
}
