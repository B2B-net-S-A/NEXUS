"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Briefcase,
  CalendarClock,
  FileSignature,
  Receipt,
  Users,
} from "lucide-react";

import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { ReportStateDot } from "@/components/client-reports/ReportStateDot";
import { defaultPeriod, splitPeriod } from "@/components/clients/invoicing/invoicing-format";
import { MonthStepsList, useMonthRcp } from "@/components/clients/invoicing/MonthSteps";
import { monthSteps } from "@/components/clients/invoicing/month-steps";
import { api } from "@/lib/api";
import { getClientCatalog, type ReportDefinition } from "@/lib/api/client-reports";
import { useClientInvoicing } from "@/lib/api/client-invoicing";
import { dlPortalApi, type FrameworkContractRead } from "@/lib/api/dlPortal";
import type { ClientTab } from "@/lib/client-tab";
import { formatIsoDatePl, monthTitlePl, monthYearPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import type { ClientProfileResponse, OpenJobItem } from "@/types/client-profile";

import type { OverviewContact } from "./overview-attention";

/**
 * Karty „Przeglądu” klienta (makieta 19.11.2026, wariant A): u góry cztery
 * liczby (nasi ludzie, rekrutacje, rozliczenie miesiąca, umowa ramowa), pod
 * nimi najnowsze rekrutacje, ludzie klienta i raporty. Te same zapytania
 * (klucze) co zakładki, więc przejście do nich nie pobiera danych drugi raz.
 */
type OpenTab = (tab: ClientTab) => void;

export function OverviewCard({
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

/** Umowa ramowa jako liczba u góry Przeglądu: do kiedy, od kiedy, ile aneksów. */
export function FrameworkStatCard({ clientId, onOpen }: { clientId: number; onOpen: OpenTab }) {
  const query = useQuery({
    queryKey: ["framework-contracts", clientId],
    queryFn: async () => (await dlPortalApi.listFrameworkContracts(clientId)).data,
  });
  const items = query.data?.items ?? [];
  const live = items.filter((item) => LIVE_STATUSES.has(item.status));
  // Najdłużej obowiązująca (bezterminowa wygrywa) — na niej klient dziś stoi.
  const current = [...live].sort((a, b) =>
    (b.expiry_date ?? "9999-12-31").localeCompare(a.expiry_date ?? "9999-12-31"),
  )[0];
  const expiry = current ? expiryText(current) : null;

  return (
    <StatCard
      icon={<FileSignature className="h-3.5 w-3.5" />}
      title="Umowa ramowa"
      action="Umowy"
      onAction={() => onOpen("umowy-ramowe")}
      value={
        query.isLoading
          ? "…"
          : query.isError
            ? "—"
            : current
              ? current.expiry_date
                ? `do ${formatIsoDatePl(current.expiry_date)}`
                : "bezterminowa"
              : "brak"
      }
      tone={expiry && expiry.tone !== "success" ? expiry.tone : undefined}
      sub={
        query.isError
          ? "Nie udało się wczytać umów."
          : current
            ? [
                current.effective_date ? `od ${formatIsoDatePl(current.effective_date)}` : null,
                countPl(current.amendments_count, "aneks", "aneksy", "aneksów"),
                current.has_file ? null : "bez pliku",
                live.length > 1 ? `+${countPl(live.length - 1, "umowa", "umowy", "umów")}` : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : query.isLoading
              ? undefined
              : "Brak umowy ramowej w NEXUSIE — dodasz ją w „Umowach”."
      }
    />
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

export function ReportsCard({ clientId, onOpen }: { clientId: number; onOpen: OpenTab }) {
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

/**
 * Rozliczenie poprzedniego miesiąca jako cztery kroki: RCP → do faktury →
 * KSeF → zapłata (makieta 20.11.2026, wariant A, decyzja Artura). Krok mówi
 * tylko to, co potwierdzają dane: bez przyjętego RCP „brak w NEXUSIE”, termin
 * za sobą bez dowodu z wyciągów „brak danych o zapłacie”, „po terminie” tylko
 * z dowodem z ciągłych wyciągów (#3623). Szczegół kroku w dymku i w pasku
 * „Faktur i rozliczenia”; te same klucze zapytań co zakładka.
 */
export function InvoicingStatCard({ clientId, onOpen }: { clientId: number; onOpen: OpenTab }) {
  const period = defaultPeriod();
  const { year, month } = splitPeriod(period);
  const query = useClientInvoicing(clientId, year, month);
  const rcp = useMonthRcp(clientId, period);
  const steps = query.data ? monthSteps(query.data, rcp) : [];

  return (
    // Kotwica nowości „Rozliczenie miesiąca w czterech krokach” (novelties.json).
    <section
      data-tour="client.overview.settlement"
      className="flex min-w-0 flex-col gap-1 rounded-xl border border-border bg-card px-4 py-3 shadow-xs"
    >
      <StatCardHeader
        icon={<Receipt className="h-3.5 w-3.5" />}
        title="Rozliczenie"
        action="Faktury"
        onAction={() => onOpen("faktury")}
      />
      {steps.length ? (
        <>
          <p className="text-xs text-muted-foreground">{monthTitlePl(period)}</p>
          <MonthStepsList steps={steps} />
        </>
      ) : (
        <StatCardBody
          value={query.isLoading ? "…" : query.data ? "0" : "—"}
          sub={
            query.isLoading
              ? undefined
              : query.data
                ? `${monthYearPl(period)}: nie ma zamówień do zafakturowania.`
                : "Nie udało się wczytać rozliczenia."
          }
        />
      )}
    </section>
  );
}

function StatCardHeader({
  icon,
  title,
  action,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <header className="flex items-center justify-between gap-2">
      <h3 className="flex min-w-0 items-center gap-1.5 truncate text-xs font-medium text-muted-foreground">
        <span aria-hidden>{icon}</span>
        {title}
      </h3>
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
  );
}

/**
 * „Ludzie klienta”: osoby decyzyjne i kluczowe relacje z kontaktów TEGO
 * klienta (te same dane co „Ludzie klienta › Kontakty”) i opiekun po naszej
 * stronie. Do 19.11.2026 karta nazywała się „Kluczowe osoby”.
 */
export function PeopleCard({
  clientId,
  onOpen,
  deliveryLead,
}: {
  clientId: number;
  onOpen: OpenTab;
  deliveryLead?: string | null;
}) {
  const query = useQuery<OverviewContact[]>({
    queryKey: ["client-contacts", clientId],
    queryFn: () => api.get(`/api/clients/${clientId}/contacts`).then((r) => r.data),
  });
  // Odpowiedź z sieci: lista albo nic (granica systemu, nie zgadujemy kształtu).
  const contacts = Array.isArray(query.data) ? query.data : [];
  const key = contacts.filter((contact) => contact.is_decision_maker || contact.is_key_relationship);

  return (
    <OverviewCard
      icon={<Users className="h-4 w-4" />}
      title="Ludzie klienta"
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
      {deliveryLead ? (
        <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground">
          Po naszej stronie: <span className="font-medium text-foreground">{deliveryLead}</span> (Delivery Lead)
        </p>
      ) : null}
    </OverviewCard>
  );
}

/** Jedna liczba u góry Przeglądu z podpisem i przejściem do zakładki. */
export function StatCard({
  icon,
  title,
  value,
  sub,
  tone,
  action,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  value: string;
  sub?: string;
  tone?: StatusDotTone;
  action: string;
  onAction: () => void;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-1 rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
      <StatCardHeader icon={icon} title={title} action={action} onAction={onAction} />
      <StatCardBody value={value} sub={sub} tone={tone} />
    </section>
  );
}

function StatCardBody({ value, sub, tone }: { value: string; sub?: string; tone?: StatusDotTone }) {
  return (
    <>
      <p
        className={cn(
          // Kwoty w kilku walutach („9475,20 EUR · 8 600 000,00 zł”) się zawijają.
          "break-words font-semibold tabular-nums text-foreground",
          value.length > 16 ? "text-base leading-snug" : "text-xl",
          tone === "warning" && "text-warning",
          tone === "danger" && "text-destructive",
        )}
      >
        {value}
      </p>
      {sub ? <p className="text-xs text-muted-foreground">{sub}</p> : null}
    </>
  );
}

/** Nasi ludzie u klienta: obecni, kto i kiedy zaczyna, ilu zakończyło. */
export function PeopleStatCard({ data, onOpen }: { data: ClientProfileResponse; onOpen: OpenTab }) {
  const planned = data.planned_consultants ?? [];
  const firstStart = planned
    .map((row) => row.start_date)
    .filter(Boolean)
    .sort()[0];
  const ended = data.historical.placements_total ?? data.historical.placements.length;
  return (
    <StatCard
      icon={<Users className="h-3.5 w-3.5" />}
      title="Nasi ludzie"
      action="Konsultanci"
      onAction={() => onOpen("konsultanci")}
      value={String(data.summary.active_consultants)}
      sub={[
        planned.length > 0
          ? `+${planned.length} zaczyna${firstStart ? ` od ${formatIsoDatePl(firstStart)}` : ""}`
          : null,
        countPl(ended, "zakończony", "zakończonych", "zakończonych"),
      ]
        .filter(Boolean)
        .join(" · ")}
    />
  );
}

function openedInLastDays(jobs: readonly OpenJobItem[], days: number, today: string): number {
  const limit = Date.parse(`${today}T00:00:00Z`) - days * 86_400_000;
  return jobs.filter((job) => Date.parse(job.created_at) >= limit).length;
}

/** Otwarte rekrutacje klienta (`published`) i ile ruszyło w ostatnim tygodniu. */
export function JobsStatCard({ data, onOpen }: { data: ClientProfileResponse; onOpen: OpenTab }) {
  const fresh = openedInLastDays(data.open_jobs, 7, warsawToday());
  return (
    <StatCard
      icon={<Briefcase className="h-3.5 w-3.5" />}
      title="Otwarte rekrutacje"
      action="Projekty"
      onAction={() => onOpen("projekty")}
      value={String(data.summary.open_jobs)}
      sub={fresh > 0 ? `${countPl(fresh, "nowa", "nowe", "nowych")} w ostatnich 7 dniach` : "nic nowego w ostatnich 7 dniach"}
    />
  );
}

const LATEST_JOBS = 4;

/** Najnowsze otwarte rekrutacje — czego klient teraz szuka. */
export function LatestJobsCard({ data, onOpen }: { data: ClientProfileResponse; onOpen: OpenTab }) {
  const latest = [...data.open_jobs]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, LATEST_JOBS);
  return (
    <OverviewCard
      icon={<Briefcase className="h-4 w-4" />}
      title="Najnowsze rekrutacje"
      action="Projekty"
      onAction={() => onOpen("projekty")}
    >
      {latest.length === 0 ? (
        <Muted>Klient nie ma teraz otwartych rekrutacji.</Muted>
      ) : (
        <ul className="divide-y divide-border">
          {latest.map((job) => (
            <li key={job.id} className="flex min-w-0 items-baseline justify-between gap-3 py-1.5 text-[13px]">
              <span className="min-w-0 truncate font-medium text-foreground" title={job.title}>
                {job.title}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                {/* Bez rekrutera: pole właściciela rekrutacji nie zgadza się
                    z „Bez rekrutera” w Projektach (przypisania) — 19.11.2026. */}
                {formatIsoDatePl(job.created_at)} · {job.candidate_count} kand.
              </span>
            </li>
          ))}
        </ul>
      )}
    </OverviewCard>
  );
}
