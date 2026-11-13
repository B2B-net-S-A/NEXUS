"use client";

// Finanse → Rozliczenia (roadmapa E1.6, E5): klient i miesiąc, podzakładki
// „RCP i faktury kontraktorów”, „Do faktury dla klienta”, „Plan miesiąca”
// (estymacja) i „Reguły klienta”, karta osoby w miejscu listy. Klient z regułą
// „Raport godzin od klienta (T4T)” ma też „Raport klienta (T4T)” i „Kartotekę”
// (plan Nordei N1.5), a klient z fakturami do odbiorcy w sieci Peppol —
// „E-faktury (Peppol)” (plan Nordei N2).
// Stan w adresie przez History API, jak reszta /finance.
import { useEffect, useMemo, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import { useEinvoiceClients } from "@/lib/api/client-einvoices";
import { useSettlementClients } from "@/lib/api/client-settlements";
import { useTimeReportClients } from "@/lib/api/client-time-reports";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { ClientInvoiceView } from "./ClientInvoiceView";
import { ClientRulesEditor } from "./ClientRulesEditor";
import { EinvoicesView } from "./EinvoicesView";
import { EstimatesView } from "./EstimatesView";
import { SettlementCard } from "./SettlementCard";
import { SettlementMonthView } from "./SettlementMonthView";
import { TimeReportIdsPanel } from "./TimeReportIdsPanel";
import { TimeReportPersonCard } from "./TimeReportPersonCard";
import { TimeReportView } from "./TimeReportView";
import { defaultMonth, monthLabel, nextMonths, recentMonths } from "./format";

/** Parametry adresu należące do tej zakładki (czyści je zmiana zakładki /finance). */
export const SETTLEMENTS_URL_KEYS = ["stClient", "stMonth", "stSub", "stContract", "stVersion", "stPerson"] as const;

type Sub = "month" | "t4t" | "ids" | "invoice" | "einvoices" | "plan" | "rules";
const SUBS: readonly Sub[] = ["month", "t4t", "ids", "invoice", "einvoices", "plan", "rules"];
const T4T_SUBS: readonly Sub[] = ["t4t", "ids"];

function readParam(key: (typeof SETTLEMENTS_URL_KEYS)[number]): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

function writeParams(next: Partial<Record<(typeof SETTLEMENTS_URL_KEYS)[number], string | null>>) {
  const params = new URLSearchParams(window.location.search);
  Object.entries(next).forEach(([k, v]) => (v == null ? params.delete(k) : params.set(k, v)));
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

export function SettlementsTab({ canWrite }: { canWrite: boolean }) {
  const today = warsawToday();
  const months = useMemo(() => recentMonths(today, 6), [today]);
  // Reguły mogą działać od rozliczanego miesiąca: pierwsze ustawienie klienta
  // musi objąć miesiąc, który Finanse właśnie zamykają.
  const ruleMonths = useMemo(() => [defaultMonth(today), ...nextMonths(today, 3)], [today]);
  const clients = useSettlementClients();
  const [clientId, setClientId] = useState<number | null>(null);
  const [month, setMonth] = useState(defaultMonth(today));
  const [sub, setSub] = useState<Sub>("month");
  const [contractId, setContractId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [personKey, setPersonKey] = useState<string | null>(null);
  const timeReportClients = useTimeReportClients(month);
  const einvoiceClients = useEinvoiceClients();

  useEffect(() => {
    const c = Number(readParam("stClient"));
    if (c) setClientId(c);
    const m = readParam("stMonth");
    if (m && /^\d{4}-\d{2}$/.test(m)) setMonth(m);
    const s = readParam("stSub") as Sub | null;
    if (s && SUBS.includes(s)) setSub(s);
    const k = Number(readParam("stContract"));
    if (k) setContractId(k);
    const v = Number(readParam("stVersion"));
    if (v) setVersionId(v);
    const p = readParam("stPerson");
    if (p && /^[A-Za-z0-9]{2,16}$/.test(p)) setPersonKey(p);
  }, []);

  // Domyślnie klient z największą liczbą rzeczy do zrobienia.
  useEffect(() => {
    if (clientId != null || !clients.data?.length) return;
    const first = [...clients.data].sort((a, b) => b.todo - a.todo || b.active_contracts - a.active_contracts)[0];
    setClientId(first.client_id);
  }, [clients.data, clientId]);

  if (clients.isError) {
    return <QueryStateNotice state="error" description={apiErrorMessage(clients.error, "Nie udało się pobrać klientów do rozliczeń.")} onRetry={() => clients.refetch()} />;
  }
  if (!clients.isSuccess || clientId == null) {
    return clients.isSuccess && clients.data.length === 0 ? (
      <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">Żaden klient nie ma aktywnych kontraktów.</p>
    ) : (
      <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>
    );
  }
  const current = clients.data.find((c) => c.client_id === clientId);
  const hasTimeReport = timeReportClients.data?.client_ids.includes(clientId) ?? false;
  const hasEinvoices = einvoiceClients.data?.client_ids.includes(clientId) ?? false;
  const visibleSub: Sub = T4T_SUBS.includes(sub) && !hasTimeReport ? "month" : sub;

  function pickClient(id: number) {
    setClientId(id);
    setContractId(null);
    setVersionId(null);
    setPersonKey(null);
    writeParams({ stClient: String(id), stContract: null, stVersion: null, stPerson: null });
  }
  function pickMonth(m: string) {
    setMonth(m);
    setContractId(null);
    setVersionId(null);
    setPersonKey(null);
    writeParams({ stMonth: m, stContract: null, stVersion: null, stPerson: null });
  }
  function pickVersion(id: number | null) {
    setVersionId(id);
    writeParams({ stVersion: id == null ? null : String(id) });
  }
  function openPerson(key: string | null) {
    setPersonKey(key);
    writeParams({ stPerson: key });
  }
  function pickSub(s: Sub) {
    setSub(s);
    setContractId(null);
    setPersonKey(null);
    // Plan dotyczy miesiąca, który jeszcze trwa.
    const planMonth = s === "plan" ? months[0] : null;
    if (planMonth) setMonth(planMonth);
    writeParams({ stSub: s === "month" ? null : s, stContract: null, stPerson: null, ...(planMonth ? { stMonth: planMonth } : {}) });
  }
  function openContract(id: number | null) {
    setContractId(id);
    writeParams({ stContract: id == null ? null : String(id) });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Klient"
          value={clientId}
          onChange={(e) => pickClient(Number(e.target.value))}
          className="h-8 max-w-80 rounded-md border border-border bg-background px-2 text-sm font-medium pointer-coarse:h-10"
        >
          {clients.data.map((c) => (
            <option key={c.client_id} value={c.client_id}>
              {c.name}{c.todo ? ` · ${c.todo} do zrobienia` : ""}
            </option>
          ))}
        </select>
        {visibleSub !== "rules" ? (
          <select
            aria-label="Miesiąc rozliczenia"
            value={month}
            onChange={(e) => pickMonth(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-sm font-medium pointer-coarse:h-10"
          >
            {months.map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
        ) : null}
        <div role="tablist" aria-label="Widok rozliczeń" className="inline-flex rounded-lg bg-muted p-0.5">
          {(
            [
              ["month", "RCP i faktury kontraktorów"],
              ["t4t", "Raport klienta (T4T)"],
              ["ids", "Kartoteka"],
              ["invoice", "Do faktury dla klienta"],
              ["einvoices", "E-faktury (Peppol)"],
              ["plan", "Plan miesiąca"],
              ["rules", "Reguły klienta"],
            ] as const
          )
            .filter(([key]) => hasTimeReport || !T4T_SUBS.includes(key))
            .filter(([key]) => key !== "einvoices" || hasEinvoices || sub === "einvoices")
            .map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={visibleSub === key}
              onClick={() => pickSub(key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-9",
                visibleSub === key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {current && !current.rules_set ? (
          <StatusDot tone="warning" className="ml-auto">
            Bez reguł: pliki wchodzą bez kontroli
          </StatusDot>
        ) : null}
      </div>
      {visibleSub === "t4t" ? (
        personKey ? (
          <TimeReportPersonCard clientId={clientId} month={month} personKey={personKey} versionId={versionId} onBack={() => openPerson(null)} />
        ) : (
          <TimeReportView clientId={clientId} month={month} canWrite={canWrite} versionId={versionId} onVersion={pickVersion} onOpen={openPerson} />
        )
      ) : visibleSub === "ids" ? (
        <TimeReportIdsPanel clientId={clientId} month={month} canWrite={canWrite} />
      ) : visibleSub === "rules" ? (
        <ClientRulesEditor clientId={clientId} clients={clients.data} month={month} months={ruleMonths} canWrite={canWrite} />
      ) : visibleSub === "invoice" ? (
        <ClientInvoiceView clientId={clientId} month={month} />
      ) : visibleSub === "einvoices" ? (
        <EinvoicesView clientId={clientId} month={month} canWrite={canWrite} />
      ) : contractId != null ? (
        <SettlementCard
          contractId={contractId}
          month={month}
          canWrite={canWrite}
          kind={visibleSub === "plan" ? "estimate" : "actual"}
          onBack={() => openContract(null)}
        />
      ) : visibleSub === "plan" ? (
        <EstimatesView clientId={clientId} month={month} canWrite={canWrite} onOpen={openContract} />
      ) : (
        <SettlementMonthView clientId={clientId} month={month} canWrite={canWrite} onOpen={openContract} />
      )}
    </div>
  );
}
