"use client";

// Finanse → Rozliczenia (roadmapa E1.6, E5): klient i miesiąc, podzakładki
// „RCP i faktury kontraktorów”, „Do faktury dla klienta”, „Plan miesiąca”
// (estymacja) i „Reguły klienta”, karta osoby w miejscu listy.
// Stan w adresie przez History API, jak reszta /finance.
import { useEffect, useMemo, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import { useSettlementClients } from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { ClientInvoiceView } from "./ClientInvoiceView";
import { ClientRulesEditor } from "./ClientRulesEditor";
import { EstimatesView } from "./EstimatesView";
import { SettlementCard } from "./SettlementCard";
import { SettlementMonthView } from "./SettlementMonthView";
import { defaultMonth, monthLabel, nextMonths, recentMonths } from "./format";

/** Parametry adresu należące do tej zakładki (czyści je zmiana zakładki /finance). */
export const SETTLEMENTS_URL_KEYS = ["stClient", "stMonth", "stSub", "stContract"] as const;

type Sub = "month" | "invoice" | "plan" | "rules";
const SUBS: readonly Sub[] = ["month", "invoice", "plan", "rules"];

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

  useEffect(() => {
    const c = Number(readParam("stClient"));
    if (c) setClientId(c);
    const m = readParam("stMonth");
    if (m && /^\d{4}-\d{2}$/.test(m)) setMonth(m);
    const s = readParam("stSub") as Sub | null;
    if (s && SUBS.includes(s)) setSub(s);
    const k = Number(readParam("stContract"));
    if (k) setContractId(k);
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

  function pickClient(id: number) {
    setClientId(id);
    setContractId(null);
    writeParams({ stClient: String(id), stContract: null });
  }
  function pickMonth(m: string) {
    setMonth(m);
    setContractId(null);
    writeParams({ stMonth: m, stContract: null });
  }
  function pickSub(s: Sub) {
    setSub(s);
    setContractId(null);
    // Plan dotyczy miesiąca, który jeszcze trwa.
    const planMonth = s === "plan" ? months[0] : null;
    if (planMonth) setMonth(planMonth);
    writeParams({ stSub: s === "month" ? null : s, stContract: null, ...(planMonth ? { stMonth: planMonth } : {}) });
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
        {sub !== "rules" ? (
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
              ["invoice", "Do faktury dla klienta"],
              ["plan", "Plan miesiąca"],
              ["rules", "Reguły klienta"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={sub === key}
              onClick={() => pickSub(key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-9",
                sub === key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
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
      {sub === "rules" ? (
        <ClientRulesEditor clientId={clientId} clients={clients.data} month={month} months={ruleMonths} canWrite={canWrite} />
      ) : sub === "invoice" ? (
        <ClientInvoiceView clientId={clientId} month={month} />
      ) : contractId != null ? (
        <SettlementCard
          contractId={contractId}
          month={month}
          canWrite={canWrite}
          kind={sub === "plan" ? "estimate" : "actual"}
          onBack={() => openContract(null)}
        />
      ) : sub === "plan" ? (
        <EstimatesView clientId={clientId} month={month} canWrite={canWrite} onOpen={openContract} />
      ) : (
        <SettlementMonthView clientId={clientId} month={month} canWrite={canWrite} onOpen={openContract} />
      )}
    </div>
  );
}
