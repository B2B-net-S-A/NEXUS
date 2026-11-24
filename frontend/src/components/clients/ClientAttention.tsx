"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { api } from "@/lib/api";
import { STATE_LABELS, getCalendar, type CalendarItem, type ReportState } from "@/lib/api/client-reports";
import { touchpointTone } from "@/components/clients/relationship-strength";
import { countPl } from "@/lib/plural-pl";
import { warsawToday } from "@/lib/warsaw-date";

/**
 * Kolumna „Wymaga uwagi” na liście klientów (makieta 18.11.2026, wersja
 * „prościej”): to, co dotąd miało osobne tryby modułu Klienci — raporty
 * miesiąca i kluczowe relacje — jako znacznik w wierszu klienta, z linkiem
 * do właściwej zakładki jego profilu. Pusta komórka = nic do zrobienia.
 */
export interface AttentionItem {
  key: string;
  tone: StatusDotTone;
  label: string;
  note?: string;
  href: string;
}

const OPEN_REPORT: ReadonlySet<ReportState> = new Set(["overdue", "today", "todo", "no_date"]);
const REPORT_TONE: Record<ReportState, StatusDotTone> = {
  overdue: "danger",
  today: "warning",
  todo: "info",
  sent: "success",
  no_date: "neutral",
};
/** Relacja bez osobistego kontaktu dłużej niż tyle dni prosi o uwagę (jak kropka „Ostatni kontakt”). */
const STALE_RELATIONSHIP_DAYS = 30;
export const CONTRACT_ENDING_DAYS = 90;

export interface AttentionRelationship {
  contact_id: number;
  name: string;
  client_id: number;
  days_since_personal_touchpoint: number | null;
}

export function daysUntil(isoDate: string, today: string = warsawToday()): number {
  return Math.round(
    (Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000,
  );
}

/**
 * Znaczniki raportów miesiąca (otwarte: po terminie, dziś, do przygotowania,
 * bez terminu) i kluczowych relacji bez kontaktu od ponad 30 dni, po `client_id`.
 */
export function buildClientAttention(
  reports: readonly CalendarItem[],
  relationships: readonly AttentionRelationship[],
): Map<number, AttentionItem[]> {
  const byClient = new Map<number, AttentionItem[]>();
  const push = (clientId: number, item: AttentionItem) => {
    byClient.set(clientId, [...(byClient.get(clientId) ?? []), item]);
  };
  for (const report of reports) {
    if (!OPEN_REPORT.has(report.state)) continue;
    push(report.client_id, {
      key: `report-${report.definition_id}-${report.period_key}`,
      tone: REPORT_TONE[report.state],
      label: `Raport: ${STATE_LABELS[report.state].toLocaleLowerCase("pl")}`,
      note: report.report,
      href: `/clients/${report.client_id}?tab=raporty`,
    });
  }
  for (const row of relationships) {
    const days = row.days_since_personal_touchpoint;
    if (days !== null && days <= STALE_RELATIONSHIP_DAYS) continue;
    push(row.client_id, {
      key: `relationship-${row.contact_id}`,
      tone: days === null ? "neutral" : touchpointTone(days),
      label: days === null ? "Relacja bez kontaktu" : `Relacja: ${countPl(days, "dzień", "dni", "dni")} bez kontaktu`,
      note: row.name,
      href: `/clients/${row.client_id}?tab=kontakty`,
    });
  }
  return byClient;
}

/** Umowa ramowa, która wygasła albo kończy się w 90 dni — znacznik do „Umów” klienta. */
export function contractAttention(
  row: { client_id: number; scope_id: number | string; expiry_date: string | null },
  today: string = warsawToday(),
): AttentionItem | null {
  if (!row.expiry_date) return null;
  const days = daysUntil(row.expiry_date, today);
  if (days > CONTRACT_ENDING_DAYS) return null;
  return {
    key: `contract-${row.scope_id}`,
    tone: days < 0 ? "danger" : "warning",
    label: days < 0 ? "Umowa wygasła" : `Umowa kończy się za ${countPl(days, "dzień", "dni", "dni")}`,
    href: `/clients/${row.client_id}?tab=umowy-ramowe`,
  };
}

export interface ConsultantAttentionCounts {
  order_ending: number;
  order_ending_first: string | null;
  no_current_order: number;
  notice: number;
}

function shortDate(isoDate: string): string {
  const [, month, day] = isoDate.slice(0, 10).split("-");
  return `${day}.${month}`;
}

/**
 * Konsultanci ze znacznikiem „Wymaga uwagi” (lista „Klienci”, 19.11.2026) —
 * liczby z serwera, te same reguły co podzakładka „Wymaga uwagi” w zakładce
 * Konsultanci profilu, więc link prowadzi tam, gdzie widać te same osoby.
 */
export function consultantAttention(row: {
  client_id: number;
  consultant_attention: ConsultantAttentionCounts;
}): AttentionItem[] {
  const counts = row.consultant_attention;
  const href = `/clients/${row.client_id}?tab=konsultanci`;
  const items: AttentionItem[] = [];
  if (counts.order_ending > 0) {
    items.push({
      key: `order-ending-${row.client_id}`,
      tone: "warning",
      // Słownictwo zakładki Konsultanci i pigułki „Bez kontynuacji 30 dni”.
      label: `${countPl(counts.order_ending, "zamówienie", "zamówienia", "zamówień")} bez kontynuacji`,
      note: counts.order_ending_first
        ? `najbliższe ${shortDate(counts.order_ending_first)}`
        : undefined,
      href,
    });
  }
  if (counts.no_current_order > 0) {
    items.push({
      key: `no-order-${row.client_id}`,
      tone: "warning",
      // Ta sama nazwa co znacznik w zakładce Konsultanci („Brak bieżącego zamówienia”).
      label: "Brak bieżącego zamówienia",
      note: countPl(counts.no_current_order, "osoba", "osoby", "osób"),
      href,
    });
  }
  if (counts.notice > 0) {
    items.push({
      key: `notice-${row.client_id}`,
      tone: "info",
      label: countPl(counts.notice, "umowa wypowiedziana", "umowy wypowiedziane", "umów wypowiedzianych"),
      href,
    });
  }
  return items;
}

export interface ClientAttentionState {
  byClient: Map<number, AttentionItem[]>;
  /** Któreś z dwóch zapytań padło: pusta komórka nie znaczy wtedy „nic nie czeka”. */
  failed: boolean;
}

/** Znaczniki raportów miesiąca i relacji, po `client_id` (dane z dwóch zapytań). */
export function useClientAttention(): ClientAttentionState {
  const month = warsawToday().slice(0, 7);
  const calendar = useQuery({
    queryKey: ["client-reports-calendar", month, false],
    queryFn: () => getCalendar(month, false),
    staleTime: 60_000,
    retry: false,
  });
  const relationships = useQuery({
    queryKey: ["my-relationships"],
    queryFn: async () => (await api.get<AttentionRelationship[]>("/api/my-relationships")).data,
    staleTime: 60_000,
    retry: false,
  });
  return {
    byClient: buildClientAttention(calendar.data?.items ?? [], relationships.data ?? []),
    failed: calendar.isError || relationships.isError,
  };
}

export function AttentionCell({ items, failed = false }: { items: AttentionItem[]; failed?: boolean }) {
  if (items.length === 0 && !failed) return <span className="text-muted-foreground/60">—</span>;
  const shown = items.slice(0, 2);
  return (
    <span className="flex flex-col gap-1">
      {failed ? (
        // Awaria zapytania nie może wyglądać jak „nic nie czeka” (audyt 24.11.2026).
        <StatusDot tone="danger" title="Raporty miesiąca albo relacje nie wczytały się — odśwież stronę.">
          Nie udało się wczytać
        </StatusDot>
      ) : null}
      {shown.map((item) => (
        <Link key={item.key} href={item.href} className="rounded-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <StatusDot tone={item.tone} note={item.note}>
            {item.label}
          </StatusDot>
        </Link>
      ))}
      {items.length > shown.length ? (
        <span className="pl-3 text-[11px] text-muted-foreground">+ {items.length - shown.length} więcej</span>
      ) : null}
    </span>
  );
}
