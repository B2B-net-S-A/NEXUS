"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, FileSignature, Receipt, Users } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { ReportStateDot } from "@/components/client-reports/ReportStateDot";
import {
  defaultPeriod,
  splitPeriod,
  summaryStats,
} from "@/components/clients/invoicing/invoicing-format";
import { api } from "@/lib/api";
import { getClientCatalog, type ReportDefinition } from "@/lib/api/client-reports";
import { useClientInvoicing } from "@/lib/api/client-invoicing";
import { dlPortalApi, type FrameworkContractRead } from "@/lib/api/dlPortal";
import type { ClientTab } from "@/lib/client-tab";
import { formatIsoDatePl, monthYearPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

/**
 * Prawa kolumna „Przeglądu” klienta (makieta 18.11.2026): to, co dziś trzeba
 * zbierać z trzech zakładek i dwóch modułów — umowa ramowa, raporty, których
 * wymaga umowa, i rozliczenie ostatniego miesiąca. Te same zapytania (klucze)
 * co zakładki, więc przejście do nich nie pobiera danych drugi raz.
 */
export function ClientOverviewCards({
  clientId,
  showContracts,
  showInvoicing,
  onOpen,
}: {
  clientId: number;
  showContracts: boolean;
  showInvoicing: boolean;
  onOpen: (tab: ClientTab) => void;
}) {
  return (
    <div className="grid min-w-0 gap-3">
      {showContracts ? <FrameworkCard clientId={clientId} onOpen={onOpen} /> : null}
      <ReportsCard clientId={clientId} onOpen={onOpen} />
      {showInvoicing ? <InvoicingCard clientId={clientId} onOpen={onOpen} /> : null}
      <PeopleCard clientId={clientId} onOpen={onOpen} />
    </div>
  );
}

function OverviewCard({
  icon,
  title,
  action,
  onAction,
  children,
}: {
  icon: ReactNode;
  title: string;
  action: string;
  onAction: () => void;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 rounded-xl border border-border bg-card shadow-xs">
      <header className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="text-muted-foreground" aria-hidden>
          {icon}
        </span>
        <h3 className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground">{title}</h3>
        <button
          type="button"
          onClick={onAction}
          aria-label={`${title}: otwórz „${action}”`}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {action}
          <ArrowRight className="h-3 w-3" aria-hidden />
        </button>
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-muted-foreground">{children}</p>;
}

const LIVE_STATUSES = new Set(["active", "pending_signature"]);

function expiryText(contract: FrameworkContractRead): { text: string; tone: StatusDotTone } {
  if (!contract.expiry_date) return { text: "bezterminowa", tone: "success" };
  const days = contract.days_to_expiry;
  if (days !== null && days < 0) return { text: `wygasła ${formatIsoDatePl(contract.expiry_date)}`, tone: "danger" };
  if (days !== null && days <= 90) {
    return { text: `do ${formatIsoDatePl(contract.expiry_date)} · za ${countPl(days, "dzień", "dni", "dni")}`, tone: "warning" };
  }
  return { text: `do ${formatIsoDatePl(contract.expiry_date)}`, tone: "success" };
}

function FrameworkCard({ clientId, onOpen }: { clientId: number; onOpen: (tab: ClientTab) => void }) {
  const query = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => (await dlPortalApi.listFrameworkContracts(clientId)).data,
  });
  const items = query.data?.items ?? [];
  const live = items.filter((item) => LIVE_STATUSES.has(item.status));
  const shown = (live.length ? live : items).slice(0, 2);

  return (
    <OverviewCard
      icon={<FileSignature className="h-4 w-4" />}
      title="Umowa ramowa"
      action="Umowy"
      onAction={() => onOpen("umowy-ramowe")}
    >
      {query.isLoading ? (
        <Muted>Wczytywanie umów…</Muted>
      ) : query.isError ? (
        <Muted>Nie udało się wczytać umów.</Muted>
      ) : shown.length === 0 ? (
        <Muted>Brak umowy ramowej w NEXUSIE — dodasz ją w „Umowach”.</Muted>
      ) : (
        <ul className="space-y-2.5">
          {shown.map((contract) => {
            const expiry = expiryText(contract);
            return (
              <li key={contract.id} className="min-w-0">
                <p className="truncate text-[13px] font-medium text-foreground" title={contract.name}>
                  {contract.name}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <StatusDot tone={expiry.tone}>{expiry.text}</StatusDot>
                  {contract.effective_date ? <span>od {formatIsoDatePl(contract.effective_date)}</span> : null}
                  <span>{countPl(contract.amendments_count, "aneks", "aneksy", "aneksów")}</span>
                  {!contract.has_file ? <span className="text-warning">bez pliku</span> : null}
                </div>
              </li>
            );
          })}
          {items.length > shown.length ? (
            <li className="text-xs text-muted-foreground">
              + {countPl(items.length - shown.length, "starsza umowa", "starsze umowy", "starszych umów")}
            </li>
          ) : null}
        </ul>
      )}
    </OverviewCard>
  );
}

const OPEN_STATES = new Set(["overdue", "today", "todo", "no_date"]);

function nextReport(definitions: ReportDefinition[]): ReportDefinition | null {
  const open = definitions.filter(
    (item) => item.status === "active" && item.next.state && OPEN_STATES.has(item.next.state),
  );
  open.sort((a, b) => (a.next.due ?? "9999").localeCompare(b.next.due ?? "9999"));
  return open[0] ?? null;
}

function ReportsCard({ clientId, onOpen }: { clientId: number; onOpen: (tab: ClientTab) => void }) {
  const query = useQuery({ queryKey: ["client-reports", clientId], queryFn: () => getClientCatalog(clientId) });
  const definitions = query.data?.definitions ?? [];
  const active = definitions.filter((item) => item.status === "active");
  const proposals = definitions.filter((item) => item.status === "proposal").length;
  const next = nextReport(definitions);

  return (
    <OverviewCard
      icon={<CalendarClock className="h-4 w-4" />}
      title="Raporty dla klienta"
      action="Raporty"
      onAction={() => onOpen("raporty")}
    >
      {query.isLoading ? (
        <Muted>Wczytywanie raportów…</Muted>
      ) : query.isError ? (
        <Muted>Nie udało się wczytać raportów.</Muted>
      ) : active.length === 0 ? (
        <Muted>
          Katalog jest pusty.
          {proposals ? ` ${countPl(proposals, "propozycja czeka", "propozycje czekają", "propozycji czeka")} na zatwierdzenie.` : " „Znajdź w umowach” podpowie, czego wymaga umowa."}
        </Muted>
      ) : (
        <div className="space-y-2">
          {next ? (
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium text-foreground">{next.name}</p>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                {next.next.state ? <ReportStateDot state={next.next.state} /> : null}
                {next.next.period_label ? <span>{next.next.period_label}</span> : null}
                {next.next.due ? <span>termin {formatIsoDatePl(next.next.due)}</span> : null}
                <span>przygotowuje: {next.preparer_label}</span>
              </div>
            </div>
          ) : (
            <Muted>Wszystkie raporty wysłane.</Muted>
          )}
          <p className="text-xs text-muted-foreground">
            {countPl(active.length, "raport w katalogu", "raporty w katalogu", "raportów w katalogu")}
            {proposals ? ` · ${countPl(proposals, "propozycja", "propozycje", "propozycji")} do zatwierdzenia` : ""}
          </p>
        </div>
      )}
    </OverviewCard>
  );
}

function InvoicingCard({ clientId, onOpen }: { clientId: number; onOpen: (tab: ClientTab) => void }) {
  const period = defaultPeriod();
  const { year, month } = splitPeriod(period);
  const query = useClientInvoicing(clientId, year, month);
  const data = query.data;

  return (
    <OverviewCard
      icon={<Receipt className="h-4 w-4" />}
      title={`Rozliczenie · ${monthYearPl(period)}`}
      action="Faktury"
      onAction={() => onOpen("faktury")}
    >
      {query.isLoading ? (
        <Muted>Wczytywanie rozliczenia…</Muted>
      ) : query.isError || !data ? (
        <Muted>Nie udało się wczytać rozliczenia.</Muted>
      ) : data.summary.rows === 0 && data.invoices.length === 0 ? (
        <Muted>Za {monthYearPl(period)} nie ma zamówień do zafakturowania.</Muted>
      ) : (
        <InlineStats stats={summaryStats(data.summary, period, data.summary.overdue)} className="gap-x-4" />
      )}
    </OverviewCard>
  );
}

interface OverviewContact {
  id: number;
  name: string;
  position: string | null;
  is_decision_maker: boolean;
  is_key_relationship?: boolean;
  last_personal_touchpoint_at: string | null;
}

/**
 * „Kluczowe osoby” (makieta 18.11.2026, wersja „prościej”): osoby decyzyjne
 * i kluczowe relacje z kontaktów TEGO klienta — zamiast osobnego trybu
 * „Kluczowe relacje” na liście klientów. Te same dane co „Ludzie › Kontakty”.
 */
function PeopleCard({ clientId, onOpen }: { clientId: number; onOpen: (tab: ClientTab) => void }) {
  const query = useQuery<OverviewContact[]>({
    queryKey: ["client-contacts", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/contacts`).then((r) => r.data),
  });
  const contacts = query.data ?? [];
  const key = contacts.filter((contact) => contact.is_decision_maker || contact.is_key_relationship);

  return (
    <OverviewCard
      icon={<Users className="h-4 w-4" />}
      title="Kluczowe osoby"
      action="Kontakty"
      onAction={() => onOpen("kontakty")}
    >
      {query.isLoading ? (
        <Muted>Wczytywanie kontaktów…</Muted>
      ) : query.isError ? (
        <Muted>Nie udało się wczytać kontaktów.</Muted>
      ) : key.length === 0 ? (
        <Muted>
          {contacts.length
            ? `${countPl(contacts.length, "kontakt", "kontakty", "kontaktów")}, żaden nie jest oznaczony jako decyzyjny ani kluczowy.`
            : "Brak kontaktów klienta."}
        </Muted>
      ) : (
        <div className="space-y-2">
          <ul className="space-y-1.5">
            {key.slice(0, 3).map((contact) => (
              <li key={contact.id} className="min-w-0 text-[13px]">
                <span className="font-medium text-foreground">{contact.name}</span>
                {contact.position ? <span className="text-muted-foreground"> · {contact.position}</span> : null}
                <span className="block text-xs text-muted-foreground">
                  {[
                    contact.is_decision_maker ? "decyduje" : null,
                    contact.is_key_relationship ? "kluczowa relacja" : null,
                    contact.last_personal_touchpoint_at
                      ? `ostatni kontakt ${formatIsoDatePl(contact.last_personal_touchpoint_at)}`
                      : "bez zapisanego kontaktu",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            {countPl(contacts.length, "kontakt", "kontakty", "kontaktów")} u klienta
          </p>
        </div>
      )}
    </OverviewCard>
  );
}
