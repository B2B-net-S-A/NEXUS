"use client";
// A · Historia — zastępuje „Timeline”: zamiast „via sharepoint_import”,
// „doc type annex”, „size bytes”, e-maili autorów i JSON-a „new/old” wychodzącego
// poza kartę — strumień po ludzku, pogrupowany po miesiącach. Jedno zdarzenie
// w jednej linii (data · tytuł · szczegół · kto), automatyczne wyszarzone,
// kolejne zdarzenia tego samego rodzaju tej samej osoby tego samego dnia
// zwinięte. Zapis formularza bez pól „przed” porównuje się z poprzednią znaną
// wartością z historii, więc widać, co się naprawdę zmieniło.
// `buildHistory`, `groupHistory` i `EventLine` bierze też zakładka „Aktywność” (B).
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Banknote, ChevronDown, FileText, PenLine, RefreshCw, StickyNote, type LucideIcon } from "lucide-react";
import { contractActivityLabel } from "@/components/contracts/contract-timeline-labels";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkActivities, type MkActivity } from "../shared/data";
import {
  CONTRACT_STATUS_LABEL,
  CONTRACT_TYPE_LABEL,
  fmtDate,
  fmtDayMonth,
  fmtMonthYear,
  personFromEmail,
  plural,
  terminationReasonLabel,
} from "../shared/format";
import type { TabProps } from "./types";

export type HistCategory = "contract" | "money" | "documents" | "auto" | "other";

export interface FieldChange {
  field: string;
  label: string;
  /** Brak = poprzedniej wartości nie ma w historii (pierwszy zapis). */
  before?: string;
  after: string;
}

export interface HistDoc {
  op: "added" | "deleted" | "other";
  type: string;
  name: string;
  viaSharePoint: boolean;
}

export interface HistEvent {
  id: number;
  action: string;
  at: string;
  /** Dzień w kalendarzu firmy, „RRRR-MM-DD”. */
  day: string;
  time: string;
  who: string;
  automatic: boolean;
  /** Zapis bez zmian — wyciszony jak automatyczne. */
  quiet: boolean;
  category: HistCategory;
  /** Klucz zwijania: „documents” albo nazwa akcji. */
  family: string;
  title: string;
  detail?: string;
  changes: FieldChange[];
  doc?: HistDoc;
  noteId?: number;
}

export interface HistGroup {
  key: string;
  day: string;
  time: string;
  who: string;
  automatic: boolean;
  quiet: boolean;
  category: HistCategory;
  title: string;
  detail?: string;
  items: HistEvent[];
}

type Rec = Record<string, unknown>;

// ── Słowniki ─────────────────────────────────────────────────────────────────

// Kolejność kluczy = kolejność w opisie zmiany (stawki, daty, reszta).
const FIELD_LABEL: Record<string, string> = {
  rate_client: "stawka klienta",
  rate_candidate: "stawka kandydata",
  framework_rate: "stawka ramowa",
  start_date: "start",
  end_date: "koniec projektu",
  client_order_start_date: "początek zamówienia",
  client_order_end_date: "koniec zamówienia",
  status: "status",
  contract_type: "typ umowy",
  rate_unit: "jednostka stawek",
  billing_hours_per_month: "godziny w miesiącu",
  line_manager: "line manager",
  work_mode: "tryb pracy",
  team_name: "zespół",
  project_name: "projekt",
  office_location: "biuro",
  client_pm_name: "PM po stronie klienta",
  currency: "waluta",
  rate_client_currency: "waluta stawki klienta",
  rate_candidate_currency: "waluta stawki kandydata",
  target_rate_min: "widełki od",
  target_rate_max: "widełki do",
  handover_notes: "notatki wewnętrzne",
};

/** Krótko w linii strumienia („klient 175,00 → 163,00”). */
const SHORT_LABEL: Record<string, string> = {
  rate_client: "klient",
  rate_candidate: "kandydat",
  framework_rate: "ramowa",
};

const RATE_FIELDS = new Set(["rate_client", "rate_candidate", "framework_rate", "target_rate_min", "target_rate_max"]);
const MONEY_FIELDS = new Set([...RATE_FIELDS, "rate_unit", "billing_hours_per_month", "currency", "rate_client_currency", "rate_candidate_currency"]);
/** Pola warte pokazania, gdy w historii nie ma ich poprzedniej wartości. */
const RECORD_FIELDS = new Set([
  "rate_client",
  "rate_candidate",
  "framework_rate",
  "start_date",
  "end_date",
  "client_order_end_date",
  "billing_hours_per_month",
  "line_manager",
  "project_name",
  "team_name",
  "work_mode",
]);
const UNIT_WORD: Record<string, string> = { hourly: "godzinowa", daily: "dzienna", monthly: "miesięczna" };

const DOC_ACC: Record<string, string> = { contract: "umowę", annex: "aneks", order: "zamówienie", nda: "NDA", other: "dokument" };
const DOC_FORMS: Record<string, [string, string, string]> = {
  annex: ["aneks", "aneksy", "aneksów"],
  contract: ["umowa", "umowy", "umów"],
  order: ["zamówienie", "zamówienia", "zamówień"],
  nda: ["NDA", "NDA", "NDA"],
  other: ["inny dokument", "inne dokumenty", "innych dokumentów"],
};
const DOKUMENTY: [string, string, string] = ["dokument", "dokumenty", "dokumentów"];

const AUTO_ACTIONS = new Set([
  "synced_with_orders",
  "end_date_cleared",
  "start_date_corrected",
  "rate_unit_converted_to_hourly",
  "status_auto_changed",
  "candidate_contact_backfilled",
]);

const TITLES: Record<string, string> = {
  created: "Utworzono kontrakt",
  contract_activated: "Kontrakt aktywowany",
  contract_reopened: "Przywrócono kontrakt do aktywnych",
  status_updated: "Zmieniono status",
  status_auto_changed: "Status zmieniony dzień po końcu projektu",
  termination_reversed: "Cofnięto zakończenie współpracy",
  termination_undone: "Cofnięto zakończenie współpracy",
  termination_data_cleared: "Usunięto datę i powód cofniętego zakończenia",
  note_added: "Dodano notatkę",
  candidate_contact_backfilled: "Uzupełniono kontakt kandydata z profilu",
  auto_drafted_from_generated_contract: "Założono szkic z umowy z Generatora B2B",
  auto_drafted_from_pipeline: "Założono szkic z rekrutacji",
  linked_to_generated_contract: "Powiązano z umową z Generatora B2B",
  amendment_early_termination: "Aneks: wcześniejsze zakończenie",
  amendment_start_date_change: "Aneks: zmiana daty startu",
  contract_voided: "Unieważniono kontrakt",
  bulk_extended_3m: "Przedłużono o 3 miesiące (zbiorczo)",
  notice_withdrawn: "Wycofano wypowiedzenie",
  client_reassigned: "Przepięto na innego klienta",
  dl_alert_handled: "Obsłużono alert Delivery Leada",
  orders_card_dismissed: "Ukryto kartę zamówień",
  documents_moved: "Przeniesiono dokumenty",
  document_folder_created: "Utworzono folder dokumentów",
};

// ── Wartości ─────────────────────────────────────────────────────────────────

function rateText(v: number): string {
  const digits = Math.round(Math.abs(v) * 1000) % 10 === 0 ? 2 : 3;
  return new Intl.NumberFormat("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

function show(field: string, v: unknown): string {
  if (v == null || v === "") return field === "end_date" ? "bezterminowo" : "—";
  if (field.endsWith("_date") && typeof v === "string") return fmtDate(v);
  if (RATE_FIELDS.has(field) && typeof v === "number") return rateText(v);
  if (field === "rate_unit") return UNIT_WORD[String(v)] ?? String(v);
  if (field === "billing_hours_per_month") return `${String(v)} h`;
  if (field === "status") return (CONTRACT_STATUS_LABEL[String(v)] ?? String(v)).toLowerCase();
  if (field === "contract_type") return CONTRACT_TYPE_LABEL[String(v)] ?? String(v);
  if (field === "handover_notes") return "nowa treść";
  if (typeof v === "object") return "zmieniono";
  return String(v);
}

function norm(v: unknown): unknown {
  return v === undefined || v === "" ? null : v;
}

function same(a: unknown, b: unknown): boolean {
  const x = norm(a);
  const y = norm(b);
  if (typeof x === "number" && typeof y === "number") return Math.abs(x - y) < 1e-9;
  return x === y || JSON.stringify(x) === JSON.stringify(y);
}

const rec = (v: unknown): Rec | undefined => (v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : undefined);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

function diff(oldV: Rec | undefined, newV: Rec | undefined): FieldChange[] {
  if (!newV) return [];
  return Object.entries(newV)
    .filter(([k, v]) => FIELD_LABEL[k] && !same(oldV?.[k], v))
    .map(([k, v]) => ({
      field: k,
      label: FIELD_LABEL[k],
      before: oldV && k in oldV ? show(k, oldV[k]) : undefined,
      after: show(k, v),
    }));
}

const FIELD_ORDER = Object.keys(FIELD_LABEL);
const byField = (a: FieldChange, b: FieldChange) => FIELD_ORDER.indexOf(a.field) - FIELD_ORDER.indexOf(b.field);

/** „klient 175,00 → 163,00 · kandydat 135,00 → 125,00”. */
export function changesLine(changes: FieldChange[], short = true): string {
  return [...changes]
    .sort(byField)
    .map((c) => {
      const label = short ? SHORT_LABEL[c.field] ?? c.label : c.label;
      if (c.before === undefined) return `${label} ${c.after}`;
      if (c.before === "—") return `uzupełniono ${label} ${c.after}`;
      if (c.after === "—") return `usunięto ${label} (było ${c.before})`;
      return `${label} ${c.before} → ${c.after}`;
    })
    .join(" · ");
}

const TIME = new Intl.DateTimeFormat("pl-PL", { timeZone: "Europe/Warsaw", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

/** „12:58” w czasie firmy. */
export function warsawTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : TIME.format(d);
}

const statusWord = (v: unknown) => (v ? (CONTRACT_STATUS_LABEL[String(v)] ?? String(v)).toLowerCase() : "—");

// ── Historia po ludzku ───────────────────────────────────────────────────────

/** Zdarzenia od najnowszych, z porównaniem zapisów formularza z poprzednią znaną wartością. */
export function buildHistory(acts: MkActivity[]): HistEvent[] {
  const asc = [...acts].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
  const known = new Map<string, unknown>();
  let pending: { day: string; field: string; value: unknown }[] = [];
  const out: HistEvent[] = [];

  const seed = (snapshot: Rec | undefined) => {
    for (const [k, v] of Object.entries(snapshot ?? {})) if (FIELD_LABEL[k] && !known.has(k)) known.set(k, norm(v));
  };

  for (const a of asc) {
    const day = warsawDateOf(a.created_at) ?? a.created_at.slice(0, 10);
    // Aneks ze stawką od przyszłej daty zmienia „bieżącą” stawkę dopiero tego dnia.
    const still: typeof pending = [];
    for (const p of pending) {
      if (p.day <= day) known.set(p.field, p.value);
      else still.push(p);
    }
    pending = still;

    const d: Rec = a.details ?? {};
    const source = str(d.source);
    const automatic =
      !a.user_name || /^\d{4}_/.test(source) || source.includes("backfill") || source.includes("sync") || AUTO_ACTIONS.has(a.action) || a.action.startsWith("auto_");
    const ev: HistEvent = {
      id: a.id,
      action: a.action,
      at: a.created_at,
      day,
      time: warsawTime(a.created_at),
      who: a.user_name ? personFromEmail(a.user_name) : "NEXUS",
      automatic,
      quiet: false,
      category: "other",
      family: a.action,
      title: TITLES[a.action] ?? contractActivityLabel(a.action),
      changes: [],
    };

    switch (a.action) {
      case "created":
      case "contract_activated":
      case "contract_reopened":
      case "status_updated":
      case "status_auto_changed": {
        ev.category = "contract";
        const from = d.from_status ?? d.previous_status;
        const to = d.to_status ?? (a.action === "created" ? undefined : d.status);
        if (to !== undefined && !same(from, to)) {
          ev.changes = [{ field: "status", label: "status", before: from !== undefined ? statusWord(from) : undefined, after: statusWord(to) }];
          ev.detail = changesLine(ev.changes, false).replace(/^status /, "");
          known.set("status", norm(to));
        }
        break;
      }
      case "updated": {
        const changes: FieldChange[] = [];
        const recorded: FieldChange[] = [];
        for (const [k, v] of Object.entries(d)) {
          if (!FIELD_LABEL[k]) continue;
          const value = norm(v);
          if (known.has(k)) {
            if (!same(known.get(k), value)) changes.push({ field: k, label: FIELD_LABEL[k], before: show(k, known.get(k)), after: show(k, value) });
          } else if (value != null && RECORD_FIELDS.has(k)) {
            recorded.push({ field: k, label: FIELD_LABEL[k], after: show(k, value) });
          }
          known.set(k, value);
        }
        const sync = rec(d.order_sync)?.order_period_changed ? "okres zamówienia uzgodniony z zamówieniem klienta" : null;
        // Stawka w innej walucie niż złote dostaje kod waluty („277,00 EUR”).
        for (const c of [...changes, ...recorded]) {
          const cur = c.field === "rate_client" ? norm(d.rate_client_currency ?? known.get("rate_client_currency")) : c.field === "rate_candidate" ? norm(d.rate_candidate_currency ?? known.get("rate_candidate_currency")) : null;
          if (typeof cur === "string" && cur.toUpperCase() !== "PLN") {
            c.after = `${c.after} ${cur.toUpperCase()}`;
            if (c.before !== undefined && c.before !== "—") c.before = `${c.before} ${cur.toUpperCase()}`;
          }
        }
        changes.sort(byField);
        recorded.sort(byField);
        ev.changes = [...changes, ...recorded];
        if (changes.length) {
          ev.title = "Zmieniono dane kontraktu";
          ev.category = changes.every((c) => MONEY_FIELDS.has(c.field)) ? "money" : "contract";
          ev.detail = [changesLine(changes, false), sync].filter(Boolean).join(" · ");
        } else if (recorded.length) {
          const money = recorded.every((c) => MONEY_FIELDS.has(c.field));
          ev.title = money ? "Wpisano stawki" : "Zapisano dane kontraktu";
          ev.category = money ? "money" : "contract";
          ev.detail = [changesLine(recorded, money), sync].filter(Boolean).join(" · ");
        } else {
          ev.title = "Zapisano dane kontraktu bez zmian";
          ev.category = "contract";
          ev.quiet = !sync;
          ev.detail = sync ?? undefined;
        }
        break;
      }
      case "amendment_rate_change":
      case "amendment_extension":
      case "amendment_early_termination":
      case "amendment_start_date_change": {
        const oldV = rec(d.old);
        const newV = rec(d.new);
        const eff = str(d.effective_date);
        ev.changes = diff(oldV, newV).sort(byField);
        seed(oldV);
        for (const [k, v] of Object.entries(newV ?? {})) {
          if (!FIELD_LABEL[k]) continue;
          if (a.action === "amendment_rate_change" && eff && eff > day) pending.push({ day: eff, field: k, value: norm(v) });
          else known.set(k, norm(v));
        }
        const from = eff ? `od ${fmtDate(eff)}` : null;
        if (a.action === "amendment_rate_change") {
          ev.title = "Aneks: zmiana stawek";
          ev.category = "money";
          ev.detail = [changesLine(ev.changes.filter((c) => RATE_FIELDS.has(c.field))), from].filter(Boolean).join(" · ");
        } else if (a.action === "amendment_extension") {
          const end = newV?.end_date;
          const prev = ev.changes.find((c) => c.field === "end_date")?.before;
          ev.title = typeof end === "string" ? `Aneks: przedłużenie do ${fmtDate(end)}` : "Aneks: przedłużenie";
          ev.category = "contract";
          ev.detail = [prev ? `wcześniej do ${prev}` : null, from].filter(Boolean).join(" · ") || undefined;
        } else {
          ev.category = "contract";
          ev.detail = [changesLine(ev.changes, false), from].filter(Boolean).join(" · ") || undefined;
        }
        break;
      }
      case "synced_with_orders": {
        ev.category = "auto";
        if ("client_order_end_date" in d || "client_order_start_date" in d) {
          const startV = norm(d.client_order_start_date);
          const endV = norm(d.client_order_end_date);
          const prevEnd = "previous_client_order_end_date" in d ? norm(d.previous_client_order_end_date) : known.get("client_order_end_date");
          ev.title = "Okres zamówienia z zamówień klienta";
          ev.changes = [
            ...(startV != null && !same(known.get("client_order_start_date"), startV)
              ? [{ field: "client_order_start_date", label: FIELD_LABEL.client_order_start_date, before: known.has("client_order_start_date") ? show("client_order_start_date", known.get("client_order_start_date")) : undefined, after: show("client_order_start_date", startV) }]
              : []),
            ...(!same(prevEnd, endV)
              ? [{ field: "client_order_end_date", label: FIELD_LABEL.client_order_end_date, before: prevEnd !== undefined ? show("client_order_end_date", prevEnd) : undefined, after: show("client_order_end_date", endV) }]
              : []),
          ];
          ev.detail = `${fmtDate(str(startV))} – ${fmtDate(str(endV))}${prevEnd ? ` · wcześniej do ${show("client_order_end_date", prevEnd)}` : ""}`;
          if (startV != null) known.set("client_order_start_date", startV);
          known.set("client_order_end_date", endV);
        } else if (Array.isArray(d.order_cost_synced)) {
          ev.title = "Stawka kandydata przepisana do zamówień";
          ev.detail = plural(d.order_cost_synced.length, ["zamówienie", "zamówienia", "zamówień"]);
        } else {
          const parts = [
            d.order_period_changed ? "okres zamówienia" : null,
            typeof d.revenue_steps_changed === "number" ? plural(d.revenue_steps_changed, ["krok stawki klienta", "kroki stawki klienta", "kroków stawki klienta"]) : null,
            d.rate_client_currency_changed ? "waluta stawki klienta" : null,
          ].filter(Boolean);
          ev.title = "Uzgodniono z zamówieniem klienta";
          ev.detail = [
            parts.length ? `zmieniono ${parts.join(" i ")}` : null,
            typeof d.currency_conflict === "string" ? `zamówienia w różnych walutach (ostatnie w ${d.currency_conflict}) — waluta do decyzji` : null,
          ]
            .filter(Boolean)
            .join(" · ") || undefined;
        }
        break;
      }
      case "end_date_cleared": {
        ev.category = "auto";
        ev.title = "Umowa oznaczona jako bezterminowa";
        const prev = norm(d.previous_end_date);
        ev.changes = [{ field: "end_date", label: FIELD_LABEL.end_date, before: prev != null ? show("end_date", prev) : undefined, after: "bezterminowo" }];
        ev.detail = prev ? `wcześniej koniec ${show("end_date", prev)}` : undefined;
        known.set("end_date", null);
        break;
      }
      case "start_date_corrected": {
        ev.category = "auto";
        ev.title = "Poprawiono datę startu";
        ev.changes = [{ field: "start_date", label: FIELD_LABEL.start_date, before: show("start_date", d.previous_start_date), after: show("start_date", d.start_date) }];
        ev.detail = `${show("start_date", d.previous_start_date)} → ${show("start_date", d.start_date)}`;
        known.set("start_date", norm(d.start_date));
        break;
      }
      case "rate_unit_converted_to_hourly": {
        ev.category = "auto";
        ev.title = "Stawki przeliczone na godzinowe";
        const unit = rec(d.rate_unit);
        const hours = rec(d.billing_hours_per_month);
        ev.changes = [
          ...(unit ? [{ field: "rate_unit", label: FIELD_LABEL.rate_unit, before: show("rate_unit", unit.from), after: show("rate_unit", unit.to) }] : []),
          ...(hours ? [{ field: "billing_hours_per_month", label: FIELD_LABEL.billing_hours_per_month, before: show("billing_hours_per_month", hours.from), after: show("billing_hours_per_month", hours.to) }] : []),
        ];
        ev.detail = [
          unit ? `${show("rate_unit", unit.from)} → ${show("rate_unit", unit.to)}${typeof d.divisor === "number" ? ` (÷ ${d.divisor})` : ""}` : null,
          hours ? `${show("billing_hours_per_month", hours.from)} → ${show("billing_hours_per_month", hours.to)} w miesiącu` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        if (unit) known.set("rate_unit", norm(unit.to));
        if (hours) known.set("billing_hours_per_month", norm(hours.to));
        break;
      }
      case "terminated": {
        ev.category = "contract";
        ev.title = "Zapisano zakończenie współpracy";
        const reason = terminationReasonLabel(str(d.termination_reason) || null);
        ev.detail = [d.terminated_at ? `koniec ${fmtDate(str(d.terminated_at))}` : null, reason ? reason.toLowerCase() : null].filter(Boolean).join(" · ") || undefined;
        break;
      }
      case "note_added":
        ev.noteId = typeof d.note_id === "number" ? d.note_id : undefined;
        break;
      case "document_uploaded":
      case "document_deleted":
      case "documents_moved":
      case "document_folder_created": {
        ev.category = "documents";
        ev.family = "documents";
        const type = str(d.doc_type) || "other";
        const name = str(d.filename);
        const viaSharePoint = d.via === "sharepoint_import";
        if (a.action === "document_uploaded") {
          ev.title = `Dodano ${DOC_ACC[type] ?? "dokument"}`;
          ev.detail = `„${name}”${viaSharePoint ? " z SharePointa" : ""}`;
          ev.doc = { op: "added", type, name, viaSharePoint };
        } else if (a.action === "document_deleted") {
          ev.title = "Usunięto dokument";
          ev.detail = name ? `„${name}”` : undefined;
          ev.doc = { op: "deleted", type, name, viaSharePoint };
        } else {
          ev.doc = { op: "other", type, name, viaSharePoint };
        }
        break;
      }
      default:
        if (a.action.startsWith("equipment_")) ev.category = "other";
    }

    if (ev.automatic) ev.category = "auto";
    out.push(ev);
  }
  return out.reverse();
}

function docGroupTitle(items: HistEvent[]): { title: string; detail?: string } {
  const added = items.filter((i) => i.doc?.op === "added");
  const deleted = items.filter((i) => i.doc?.op === "deleted");
  const allSp = added.length > 0 && added.every((i) => i.doc?.viaSharePoint);
  let title: string;
  if (added.length && deleted.length) title = `Dodano ${added.length} i usunięto ${plural(deleted.length, DOKUMENTY)}`;
  else if (added.length) title = `Dodano ${plural(added.length, DOKUMENTY)}${allSp ? " z SharePointa" : ""}`;
  else if (deleted.length) title = `Usunięto ${plural(deleted.length, DOKUMENTY)}`;
  else title = `${items[0].title} (${items.length}×)`;
  const names = [...new Set(items.map((i) => i.doc?.name).filter((n): n is string => Boolean(n)))];
  if (names.length === 1) return { title, detail: `„${names[0]}”` };
  const counts = new Map<string, number>();
  for (const i of added) counts.set(i.doc?.type ?? "other", (counts.get(i.doc?.type ?? "other") ?? 0) + 1);
  const detail = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, n]) => {
      const forms = DOC_FORMS[type] ?? DOC_FORMS.other;
      return n === 1 ? forms[0] : plural(n, forms);
    })
    .join(", ");
  return { title, detail: detail || undefined };
}

/** Kolejne zdarzenia tego samego rodzaju, tej samej osoby, tego samego dnia — w jednej linii. */
export function groupHistory(events: HistEvent[]): HistGroup[] {
  const groups: HistGroup[] = [];
  for (const ev of events) {
    const last = groups[groups.length - 1];
    const head = last?.items[0];
    if (head && head.family === ev.family && head.who === ev.who && head.day === ev.day && head.automatic === ev.automatic) {
      last.items.push(ev);
      continue;
    }
    groups.push({
      key: `g-${ev.id}`,
      day: ev.day,
      time: ev.time,
      who: ev.who,
      automatic: ev.automatic,
      quiet: ev.quiet,
      category: ev.category,
      title: ev.title,
      detail: ev.detail,
      items: [ev],
    });
  }
  for (const g of groups) {
    if (g.items.length < 2) continue;
    if (g.items[0].family === "documents") {
      Object.assign(g, docGroupTitle(g.items));
    } else {
      const titles = new Set(g.items.map((i) => i.title));
      g.title = titles.size === 1 ? `${g.items[0].title} (${g.items.length}×)` : `${g.items[0].title} i ${plural(g.items.length - 1, ["podobny wpis", "podobne wpisy", "podobnych wpisów"])}`;
      g.detail = undefined;
    }
    g.quiet = g.items.every((i) => i.quiet);
  }
  return groups;
}

// ── Widok ────────────────────────────────────────────────────────────────────

const ICON: Record<HistCategory, LucideIcon> = {
  contract: PenLine,
  money: Banknote,
  documents: FileText,
  auto: RefreshCw,
  other: StickyNote,
};

/** Jedna linia: data · ikona · tytuł · szczegół · kto; zwinięta grupa rozwija się pod spodem. */
export function EventLine({
  group,
  open,
  onToggle,
  dateFormat = "day",
}: {
  group: HistGroup;
  open: boolean;
  onToggle: () => void;
  dateFormat?: "day" | "full";
}) {
  const Icon = ICON[group.category];
  const dim = group.automatic || group.quiet;
  const many = group.items.length > 1;
  return (
    <li className="border-t border-border/50 first:border-t-0">
      <div className="grid grid-cols-[auto_16px_minmax(0,1fr)_auto_24px] items-center gap-x-2.5 py-[7px] text-[13px] leading-5">
        <time
          dateTime={group.items[0].at}
          title={`${fmtDate(group.day)}, ${group.time}`}
          className={cn("tabular-nums text-muted-foreground", dateFormat === "day" ? "w-10" : "w-[74px]")}
        >
          {dateFormat === "day" ? fmtDayMonth(group.day) : fmtDate(group.day)}
        </time>
        <Icon className={cn("size-3.5", dim ? "text-muted-foreground/60" : "text-muted-foreground")} aria-hidden />
        <p className="min-w-0 truncate" title={[group.title, group.detail].filter(Boolean).join(" · ")}>
          <span className={dim ? "text-muted-foreground" : "font-medium text-foreground"}>{group.title}</span>
          {group.detail ? <span className={dim ? "text-muted-foreground/80" : "text-muted-foreground"}> · {group.detail}</span> : null}
        </p>
        <span className={cn("whitespace-nowrap text-[12.5px]", dim ? "text-muted-foreground/80" : "text-muted-foreground")}>
          {group.automatic ? "automatycznie" : group.who}
        </span>
        {many ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-label={open ? "Zwiń" : `Pokaż ${group.items.length} wpisy`}
            className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
          </button>
        ) : (
          <span aria-hidden />
        )}
      </div>
      {many && open ? (
        <ul className={cn("mb-2 space-y-0.5 border-l border-border pl-3 text-[12.5px] leading-5", dateFormat === "day" ? "ml-[72px]" : "ml-[106px]")}>
          {group.items.map((i) => (
            <li key={i.id} className="flex min-w-0 gap-2">
              <span className="w-10 shrink-0 tabular-nums text-muted-foreground">{i.time}</span>
              <span className="min-w-0 truncate" title={[i.title, i.detail].filter(Boolean).join(" · ")}>
                <span className="text-foreground">{i.title}</span>
                {i.detail ? <span className="text-muted-foreground"> · {i.detail}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

const FILTERS: { key: "all" | Exclude<HistCategory, "other">; label: string }[] = [
  { key: "all", label: "Wszystko" },
  { key: "contract", label: "Zmiany umowy" },
  { key: "money", label: "Stawki" },
  { key: "documents", label: "Dokumenty" },
  { key: "auto", label: "Automatyczne" },
];

type FilterKey = (typeof FILTERS)[number]["key"];

export function HistoriaA({ contractId }: TabProps) {
  const q = useMkActivities(contractId);
  const sp = useSearchParams();
  const initial = FILTERS.find((f) => f.key === sp.get("filtr"))?.key ?? "all";
  const [filter, setFilter] = useState<FilterKey>(initial);
  // `rozwin=<id>` rozwija grupę od razu (do zrzutów makiety).
  const [open, setOpen] = useState<Set<string>>(() => new Set((sp.get("rozwin") ?? "").split(",").filter(Boolean).map((id) => `g-${id}`)));

  if (q.isLoading) return <p className="text-sm text-muted-foreground">Ładowanie historii…</p>;
  if (q.isError) return <p role="alert" className="text-sm text-destructive">Nie udało się pobrać historii kontraktu.</p>;

  const events = buildHistory(q.data ?? []);
  const count = (key: FilterKey) => (key === "all" ? events.length : events.filter((e) => e.category === key).length);
  const shown = filter === "all" ? events : events.filter((e) => e.category === filter);
  const groups = groupHistory(shown);
  const months: { key: string; groups: HistGroup[] }[] = [];
  for (const g of groups) {
    const key = g.day.slice(0, 7);
    const last = months[months.length - 1];
    if (last?.key === key) last.groups.push(g);
    else months.push({ key, groups: [g] });
  }
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Rodzaj zdarzeń">
          {FILTERS.map((f) => {
            const active = f.key === filter;
            const n = count(f.key);
            return (
              <button
                key={f.key}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-medium",
                  active ? "border-primary/40 bg-primary/8 text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {f.label}
                <span
                  className={cn(
                    "rounded-full px-1.5 text-[11px] tabular-nums",
                    active ? "bg-primary text-primary-foreground" : n === 0 ? "text-muted-foreground/60" : "bg-muted text-muted-foreground",
                  )}
                >
                  {n}
                </span>
              </button>
            );
          })}
        </div>
        <p className="text-[12px] text-muted-foreground">Zdarzenia automatyczne są wyszarzone</p>
      </div>

      <section className="rounded-xl border border-border bg-card px-4 pb-2 pt-1 shadow-xs">
        {groups.length === 0 ? (
          <p className="py-4 text-[13px] text-muted-foreground">
            {events.length === 0
              ? "Historia jest pusta — zmiany kontraktu, aneksy i dokumenty pojawią się tu same."
              : "W tym rodzaju nie ma zdarzeń; pozostałe są pod „Wszystko”."}
          </p>
        ) : (
          months.map((m) => (
            <div key={m.key}>
              <h3 className="flex items-center gap-2 pb-1 pt-3 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                {fmtMonthYear(m.key)}
                <span className="h-px flex-1 bg-border/70" aria-hidden />
              </h3>
              <ol>
                {m.groups.map((g) => (
                  <EventLine key={g.key} group={g} open={open.has(g.key)} onToggle={() => toggle(g.key)} />
                ))}
              </ol>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
