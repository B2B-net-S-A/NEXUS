"use client";

// Finanse → Przychody → „Przebieg miesiąca”. Makiety 24.11.2026 (po makietach
// z 23.11): cztery odpowiedzi na górze — co zrobił automat, co jest źle, czego
// brakuje, faktury do klientów — a pod nimi jedna tabela „gdzie jest każdy”
// z pięcioma krokami, ta sama dla kontraktorów u klientów i dla biura (nasi
// ludzie na B2B: klientem jesteśmy my, więc bez faktury do klienta).
// Dane: GET /api/finance/settlements/overview (`month_close.stage_counts`),
// biuro: GET /api/finance/settlements/team (kontrakt makiety).

import { useEffect, useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { apiErrorMessage } from "@/lib/api-error";
import { useMonthCheck, useMonthCloseOverview, useTeamMonth, type MonthCloseClient } from "@/lib/api/client-settlements";
import { useReminderOverview, type ReminderClient } from "@/lib/api/settlement-reminders";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

import { defaultMonth, monthLabel, pln, recentMonths, shortDay } from "../settlements/format";
import { issueHref } from "./ClientMonthStrip";
import { ClosingPanel } from "./ClosingPanel";
import { IssuesByLevel, levelOf } from "./IssuesByLevel";
import { MonthAnswers } from "./MonthAnswers";
import { MonthCheckPanel } from "./MonthCheckPanel";
import { problemTotal, stagesOf } from "./month-model";
import { StageTable } from "./StageTable";

export { issueHref };

/** Parametry adresu tego widoku (czyści je zmiana widoku /finance). */
export const MONTH_CLOSE_URL_KEYS = ["mcMonth", "mcTab"] as const;

type Tab = "clients" | "reasons" | "closing" | "diff";

function readParam(key: (typeof MONTH_CLOSE_URL_KEYS)[number]): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

function writeParam(key: (typeof MONTH_CLOSE_URL_KEYS)[number], value: string | null) {
  const params = new URLSearchParams(window.location.search);
  if (value == null) params.delete(key);
  else params.set(key, value);
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

export function settlementsHref(clientId: number, month: string, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ view: "settlements", stClient: String(clientId), stMonth: month, ...extra });
  return `/finance?${params.toString()}`;
}

export function MonthCloseView() {
  const today = warsawToday();
  const months = useMemo(() => recentMonths(today, 6), [today]);
  const [month, setMonth] = useState(defaultMonth(today));
  const [tab, setTab] = useState<Tab>("clients");

  useEffect(() => {
    const m = readParam("mcMonth");
    if (m && /^\d{4}-\d{2}$/.test(m)) setMonth(m);
    const t = readParam("mcTab");
    if (t === "reasons" || t === "closing" || t === "diff") setTab(t);
  }, []);

  const query = useMonthCloseOverview(month);
  const team = useTeamMonth(month);
  const monthCheck = useMonthCheck(month);
  const reminders = useReminderOverview(month, null);
  const reminderByClient = useMemo(
    () => new Map((reminders.data?.clients ?? []).map((r) => [r.client_id, r] as const)),
    [reminders.data],
  );

  function pickMonth(m: string) {
    setMonth(m);
    writeParam("mcMonth", m);
  }
  function pickTab(t: Tab) {
    setTab(t);
    writeParam("mcTab", t === "clients" ? null : t);
  }
  const clientHref = (clientId: number, extra: Record<string, string> = {}) => settlementsHref(clientId, month, extra);
  const teamData = team.isSuccess && team.data.people.length > 0 ? team.data : null;
  const teamError = team.isError ? apiErrorMessage(team.error, "Nie udało się pobrać biura.") : null;

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać przebiegu miesiąca.")}
        onRetry={() => query.refetch()}
      />
    );
  }

  const data = query.isSuccess ? query.data : null;
  const s = data ? stagesOf(data) : null;
  const byPerson = data ? data.clients.filter((c) => !c.client_report) : [];
  const t4t = data ? data.clients.filter((c) => c.client_report) : [];
  const issues = data ? data.reasons.filter((r) => levelOf(r) !== "missing") : [];
  const closingCount = data?.closing
    ? data.closing.ksef_not_accepted + data.closing.reserve_count + data.closing.sales_waiting
    : 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <select
          aria-label="Miesiąc rozliczeń"
          value={month}
          onChange={(e) => pickMonth(e.target.value)}
          className="h-8 rounded-md border bg-card px-2 text-sm font-medium"
        >
          {(months.includes(month) ? months : [month, ...months]).map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
            </option>
          ))}
        </select>
        {data && s ? (
          <p className="text-[12px] text-muted-foreground">
            <span className="font-medium text-foreground tabular-nums">{s.people}</span> kontraktorów u{" "}
            <span className="tabular-nums">{byPerson.length}</span> klientów
            {teamData ? (
              <>
                {" · "}
                <span className="font-medium text-foreground tabular-nums">{teamData.people.length}</span> os. biura
              </>
            ) : null}
            {t4t.length ? (
              <>
                {" · "}
                {t4t.map((c) => `${c.name} z raportu klienta (${c.client_report?.all ?? c.people} os.)`).join(", ")}
              </>
            ) : null}
          </p>
        ) : null}
      </div>

      {!data ? (
        <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>
      ) : data.clients.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          W {monthLabel(month)} żaden klient nie ma kontraktów do rozliczenia.
        </p>
      ) : (
        <>
          <MonthAnswers
            data={data}
            month={month}
            team={teamData}
            teamError={teamError}
            reminders={reminders.isSuccess ? reminders.data.clients : null}
            onShowIssues={() => pickTab("reasons")}
          />
          <div className="flex items-center gap-1">
            {/* Kotwica lekcji nowości: data-tour="finance.month-close.reasons" (przycisk „Błędy i uwagi”). */}
            {(
              [
                ["clients", "Gdzie są rozliczenia", null],
                // `stagesOf` daje zera, gdy API nie przysłało etapów (starsza odpowiedź) —
                // wtedy licznik bierze powody z listy pod zakładką.
                ["reasons", "Błędy i uwagi", s && data.stages ? problemTotal(s) : issues.length],
                ["closing", "Dla księgowej", closingCount],
                // Kontrola miesiąca (0784): otwarte rozbieżności faktur klient ↔ konsultant.
                ["diff", "Rozbieżności", monthCheck.isSuccess ? monthCheck.data.summary.open : null],
              ] as const
            ).map(([key, label, n]) => (
              <button
                key={key}
                type="button"
                aria-pressed={tab === key}
                data-tour={key === "reasons" ? "finance.month-close.reasons" : undefined}
                onClick={() => pickTab(key)}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-md border px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10",
                  tab === key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
                )}
              >
                {label}
                {n != null ? <span className="ml-1 tabular-nums">{n}</span> : null}
              </button>
            ))}
            {tab === "clients" ? (
              <span className="ml-auto hidden text-[11px] text-muted-foreground lg:inline">
                Kliknij klienta albo biuro, żeby zobaczyć osoby
              </span>
            ) : null}
          </div>
          {tab === "clients" ? (
            <StageTable
              data={data}
              month={month}
              team={teamData}
              teamError={teamError}
              reminders={reminderByClient}
              clientHref={clientHref}
              reminderNote={reminderNote}
            />
          ) : tab === "reasons" ? (
            <IssuesByLevel reasons={issues} month={month} clientHref={clientHref} />
          ) : tab === "closing" ? (
            <ClosingPanel closing={data.closing} month={month} />
          ) : (
            <MonthCheckPanel month={month} />
          )}
        </>
      )}
    </div>
  );
}

export function clientInvoiceState(c: MonthCloseClient, amounts: boolean): { tone: StatusDotTone; label: string; note?: string } {
  const open = c.decide + c.unread + c.missing;
  if (c.client_invoice_issued > 0 && c.client_invoice_issued >= c.people)
    return { tone: "success", label: "Wystawiona", note: `${c.client_invoice_issued} osób` };
  if (c.client_invoice_issued > 0)
    return { tone: "info", label: "Wystawiona częściowo", note: `${c.client_invoice_issued} z ${c.people} osób` };
  if (c.client_invoice_ready > 0)
    return { tone: "info", label: "Do wystawienia", note: `${c.client_invoice_ready} osób przyjętych` };
  if (open === 0 && c.clean > 0)
    return { tone: "neutral", label: "Po przyjęciu RCP", note: amounts && c.revenue_ready ? pln(c.revenue_ready) : `${c.clean} bez uwag` };
  return { tone: "neutral", label: "Czeka", note: `na ${open} os.` };
}

/** Notka pod liczbą brakujących raportów: adresat i ostatnie przypomnienie (#3805). */
export function reminderNote(r: ReminderClient | undefined): string | undefined {
  if (!r) return undefined;
  if (r.without_recipient) return `bez adresata: ${r.without_recipient}`;
  if (r.last_reminder_on) return `przypomniano ${shortDay(r.last_reminder_on)}`;
  return r.automatic ? "przypomni automat" : "bez przypomnienia";
}

