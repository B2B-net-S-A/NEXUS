"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import type { StatusDotTone } from "@/components/ds/StatusDot";
import { api } from "@/lib/api";
import {
  STATE_LABELS,
  getClientCatalog,
  type ReportDefinition,
  type ReportState,
} from "@/lib/api/client-reports";
import { dlPortalApi, type FrameworkContractRead } from "@/lib/api/dlPortal";
import type { ClientTab } from "@/lib/client-tab";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { warsawToday } from "@/lib/warsaw-date";
import type { ActiveConsultantItem, ClientProfileResponse } from "@/types/client-profile";

import { useClientProfile } from "./useClientProfile";

/**
 * „Wymaga uwagi” w Przeglądzie klienta (makieta 19.11.2026, wariant A):
 * sprawy zebrane z całego profilu w jednej liście z linkiem do zakładki,
 * zamiast czytania pięciu kart. Wyłącznie istniejące reguły — te same co
 * znaczniki w zakładce Konsultanci, karta umowy ramowej, katalog raportów
 * i kropka „Ostatni kontakt”. Liczbę spraw pokazuje też nagłówek klienta.
 *
 * Świadomie bez „po terminie” z rozliczenia: 19.11.2026 żadna z 2 741 faktur
 * „po terminie” nie miała zapisanej zapłaty, więc liczba nie mówi o zaległościach.
 */
export interface OverviewAttentionItem {
  key: string;
  tone: StatusDotTone;
  label: string;
  note?: string;
  tab: ClientTab;
}

/** Wiersz `GET /api/clients/{id}/contacts` (pola, których potrzebuje Przegląd). */
export interface OverviewContact {
  id: number;
  name: string;
  position: string | null;
  is_decision_maker: boolean;
  is_key_relationship?: boolean;
  last_personal_touchpoint_at: string | null;
}

const LIVE_FRAMEWORK_STATUSES = new Set(["active", "pending_signature"]);
/** Ten sam próg co znacznik umowy na liście klientów i karta umowy ramowej. */
const FRAMEWORK_ENDING_DAYS = 90;
const OPEN_REPORT_STATES: ReadonlySet<ReportState> = new Set(["overdue", "today", "todo", "no_date"]);
const REPORT_TONE: Record<ReportState, StatusDotTone> = {
  overdue: "danger",
  today: "warning",
  todo: "info",
  sent: "success",
  no_date: "neutral",
};
/** Jak kropka „Ostatni kontakt” i znacznik relacji na liście klientów. */
const STALE_TOUCHPOINT_DAYS = 30;
/** Więcej osób albo raportów zbija się w jedną pozycję, żeby lista nie rosła. */
const MAX_SEPARATE = 2;

function names(rows: readonly { candidate: { name: string } }[]): string {
  const shown = rows.slice(0, 3).map((row) => row.candidate.name);
  const rest = rows.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} i ${rest} więcej` : shown.join(", ");
}

function daysSince(iso: string, today: string): number {
  return Math.round(
    (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${iso.slice(0, 10)}T00:00:00Z`)) / 86_400_000,
  );
}

function frameworkItem(contracts: readonly FrameworkContractRead[]): OverviewAttentionItem | null {
  const live = contracts.filter((contract) => LIVE_FRAMEWORK_STATUSES.has(contract.status));
  if (live.length === 0) return null;
  // Umowa bezterminowa albo kończąca się za ponad 90 dni = klient ma na czym stać.
  const covered = live.some(
    (contract) =>
      !contract.expiry_date || (contract.days_to_expiry ?? Number.POSITIVE_INFINITY) > FRAMEWORK_ENDING_DAYS,
  );
  if (covered) return null;
  const latest = live.reduce((a, b) => ((a.expiry_date ?? "") >= (b.expiry_date ?? "") ? a : b));
  const days = latest.days_to_expiry ?? 0;
  return {
    key: "framework",
    tone: days < 0 ? "danger" : "warning",
    label:
      days < 0
        ? `Umowa ramowa wygasła ${formatIsoDatePl(latest.expiry_date)}`
        : `Umowa ramowa kończy się za ${countPl(days, "dzień", "dni", "dni")}`,
    note: latest.name,
    tab: "umowy-ramowe",
  };
}

function consultantItems(active: readonly ActiveConsultantItem[]): OverviewAttentionItem[] {
  const items: OverviewAttentionItem[] = [];
  const ending = active.filter((row) => row.attention?.includes("order_ending"));
  if (ending.length > 0) {
    const first = ending
      .map((row) => row.order_ending_on)
      .filter((value): value is string => Boolean(value))
      .sort()[0];
    items.push({
      key: "order-ending",
      tone: "warning",
      // Słownictwo zakładki Konsultanci i pigułki „Bez kontynuacji 30 dni”.
      label: `${countPl(ending.length, "zamówienie", "zamówienia", "zamówień")} bez kontynuacji${
        first ? `, najbliższe kończy się ${formatIsoDatePl(first)}` : ""
      }`,
      note: names(ending),
      tab: "konsultanci",
    });
  }
  const noOrder = active.filter((row) => row.attention?.includes("no_current_order"));
  if (noOrder.length > 0) {
    items.push({
      key: "no-order",
      tone: "warning",
      label: "Brak bieżącego zamówienia",
      note: names(noOrder),
      tab: "konsultanci",
    });
  }
  const notice = active.filter((row) => row.attention?.includes("notice"));
  if (notice.length > 0) {
    items.push({
      key: "notice",
      tone: "info",
      label: countPl(notice.length, "umowa wypowiedziana", "umowy wypowiedziane", "umów wypowiedzianych"),
      note: names(notice),
      tab: "konsultanci",
    });
  }
  return items;
}

function reportItems(definitions: readonly ReportDefinition[]): OverviewAttentionItem[] {
  const open = definitions.filter(
    (definition) =>
      definition.status === "active" &&
      definition.next.state !== null &&
      definition.next.state !== undefined &&
      OPEN_REPORT_STATES.has(definition.next.state),
  );
  if (open.length > MAX_SEPARATE) {
    return [
      {
        key: "reports",
        tone: open.some((definition) => definition.next.state === "overdue") ? "danger" : "warning",
        label: `${countPl(open.length, "raport", "raporty", "raportów")} do przygotowania albo po terminie`,
        note: open
          .slice(0, 3)
          .map((definition) => definition.name)
          .join(", "),
        tab: "raporty",
      },
    ];
  }
  return open.map((definition) => {
    const state = definition.next.state as ReportState;
    return {
      key: `report-${definition.id}`,
      tone: REPORT_TONE[state],
      label: `Raport: ${STATE_LABELS[state].toLocaleLowerCase("pl")}`,
      note: definition.name,
      tab: "raporty" as const,
    };
  });
}

function contactItems(contacts: readonly OverviewContact[], today: string): OverviewAttentionItem[] {
  const stale = contacts
    .filter((contact) => contact.is_decision_maker || contact.is_key_relationship)
    .map((contact) => ({
      contact,
      days: contact.last_personal_touchpoint_at
        ? daysSince(contact.last_personal_touchpoint_at, today)
        : null,
    }))
    .filter(({ days }) => days === null || days > STALE_TOUCHPOINT_DAYS);
  if (stale.length > MAX_SEPARATE) {
    return [
      {
        key: "contacts",
        tone: "neutral",
        label: `${countPl(stale.length, "kluczowa osoba", "kluczowe osoby", "kluczowych osób")} bez kontaktu od ponad 30 dni`,
        note: stale
          .slice(0, 3)
          .map(({ contact }) => contact.name)
          .join(", "),
        tab: "kontakty",
      },
    ];
  }
  return stale.map(({ contact, days }) => {
    const who = contact.is_decision_maker ? "Decydent" : "Kluczowa relacja";
    return {
      key: `contact-${contact.id}`,
      tone: "neutral" as const,
      label:
        days === null
          ? `${who} bez zapisanego kontaktu`
          : `${who}: ${countPl(days, "dzień", "dni", "dni")} bez kontaktu`,
      note: contact.name,
      tab: "kontakty" as const,
    };
  });
}

export function buildOverviewAttention(input: {
  profile: ClientProfileResponse | undefined;
  frameworks: readonly FrameworkContractRead[] | undefined;
  reports: readonly ReportDefinition[] | undefined;
  contacts: readonly OverviewContact[] | undefined;
  today?: string;
}): OverviewAttentionItem[] {
  const today = input.today ?? warsawToday();
  const framework = input.frameworks ? frameworkItem(input.frameworks) : null;
  const unpriced = input.profile?.summary.active_mrr_unpriced_contracts ?? 0;
  return [
    ...(framework ? [framework] : []),
    ...consultantItems(input.profile?.active_consultants ?? []),
    ...(unpriced > 0
      ? [
          {
            key: "unpriced",
            tone: "neutral" as const,
            label: `${countPl(unpriced, "kontrakt", "kontrakty", "kontraktów")} bez stawki`,
            note: "marża miesięczna jest przez to niepełna",
            tab: "konsultanci" as const,
          },
        ]
      : []),
    ...reportItems(input.reports ?? []),
    ...contactItems(input.contacts ?? [], today),
  ];
}

/**
 * Sprawy klienta z czterech zapytań — tych samych kluczy co zakładki i karty
 * Przeglądu, więc przejście do zakładki niczego nie pobiera drugi raz.
 * `ready` = profil (konsultanci) już przyszedł; reszta dochodzi, gdy przyjdzie.
 */
export function useClientOverviewAttention(
  clientId: number,
  { showContracts }: { showContracts: boolean },
): { items: OverviewAttentionItem[]; ready: boolean; contactsCount: number | null } {
  const profile = useClientProfile(clientId);
  const frameworks = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => (await dlPortalApi.listFrameworkContracts(clientId)).data,
    enabled: showContracts,
  });
  const reports = useQuery({
    queryKey: ["client-reports", clientId],
    queryFn: () => getClientCatalog(clientId),
  });
  const contacts = useQuery<OverviewContact[]>({
    queryKey: ["client-contacts", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/contacts`).then((r) => r.data),
  });
  const items = useMemo(
    () =>
      buildOverviewAttention({
        profile: profile.data,
        frameworks: showContracts ? frameworks.data?.items : undefined,
        reports: reports.data?.definitions,
        contacts: Array.isArray(contacts.data) ? contacts.data : undefined,
      }),
    [profile.data, showContracts, frameworks.data, reports.data, contacts.data],
  );
  return {
    items,
    ready: profile.isSuccess,
    // Liczba przy grupie „Ludzie klienta”; `null`, dopóki kontakty nie przyszły.
    contactsCount: Array.isArray(contacts.data) ? contacts.data.length : null,
  };
}
