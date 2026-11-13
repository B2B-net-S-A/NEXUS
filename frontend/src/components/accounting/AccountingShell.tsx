"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { RequirePermission } from "@/components/RequirePermission";
import { useLedgerConfig, type LedgerConfig } from "@/lib/api/accounting";
import { cn } from "@/lib/utils";

import {
  activeTab,
  findPeriod,
  monthTitle,
  readPeriod,
  shiftPeriod,
  visibleTabs,
  type PeriodRef,
} from "./ledger-model";

interface AccountingContextValue {
  config: LedgerConfig;
  period: PeriodRef;
  setPeriod: (next: PeriodRef) => void;
}

const AccountingContext = createContext<AccountingContextValue | null>(null);

/** Konfiguracja i wybrany miesiąc obszaru (tylko wewnątrz `AccountingShell`). */
export function useAccounting(): AccountingContextValue {
  const value = useContext(AccountingContext);
  if (!value) throw new Error("useAccounting poza AccountingShell");
  return value;
}

const MODE_DOT: Record<string, string> = {
  symfonia: "bg-warning",
  parallel: "bg-info",
  nexus: "bg-success",
};

function writePeriod(period: PeriodRef) {
  const params = new URLSearchParams(window.location.search);
  params.set("year", String(period.year));
  params.set("month", String(period.month));
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

function ShellBody({ config, children }: { config: LedgerConfig; children: ReactNode }) {
  const pathname = usePathname();
  const [period, setPeriodState] = useState<PeriodRef>(() =>
    typeof window === "undefined"
      ? readPeriod("", config.today)
      : readPeriod(window.location.search, config.today),
  );
  useEffect(() => {
    setPeriodState(readPeriod(window.location.search, config.today));
  }, [pathname, config.today]);
  const setPeriod = useCallback((next: PeriodRef) => {
    setPeriodState(next);
    writePeriod(next);
  }, []);
  const tabs = visibleTabs(config);
  const current = activeTab(pathname);
  const { year } = findPeriod(config, period);
  const value = useMemo(() => ({ config, period, setPeriod }), [config, period, setPeriod]);
  const query = `?year=${period.year}&month=${period.month}`;

  return (
    <AccountingContext.Provider value={value}>
      <div className="space-y-3.5">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="font-display text-xl font-semibold leading-tight tracking-tight">Księgowość</h1>
            <p className="min-w-0 text-[13px] text-muted-foreground">{current.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-8 items-center rounded-md border border-border bg-background text-sm">
              <button
                type="button"
                aria-label="Poprzedni miesiąc"
                onClick={() => setPeriod(shiftPeriod(period, -1))}
                className="grid h-8 w-7 place-items-center text-muted-foreground hover:text-foreground"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="min-w-[9.5rem] px-1.5 text-center font-medium tabular-nums">
                {monthTitle(period.year, period.month)}
              </span>
              <button
                type="button"
                aria-label="Następny miesiąc"
                onClick={() => setPeriod(shiftPeriod(period, 1))}
                className="grid h-8 w-7 place-items-center text-muted-foreground hover:text-foreground"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            <span
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 text-xs text-muted-foreground"
              title={year ? year.mode_label : "Rok obrotowy nie jest założony — zrobisz to w Ustawieniach"}
            >
              <span className={cn("h-1.5 w-1.5 rounded-full", year ? MODE_DOT[year.mode] : "bg-muted-foreground/50")} aria-hidden />
              {year ? `Księga ${year.year}: ${year.mode_label}` : `Brak roku ${period.year}`}
            </span>
          </div>
        </header>
        <nav aria-label="Księgowość" className="flex max-w-full gap-0.5 overflow-x-auto border-b border-border">
          {tabs.map((tab) => {
            const active = tab.href === current.href;
            return (
              <Link
                key={tab.href}
                href={`${tab.href}${query}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex shrink-0 items-center whitespace-nowrap border-b-2 px-3 py-1.5 text-[13px] transition-colors pointer-coarse:min-h-10",
                  active
                    ? "border-primary font-semibold text-foreground"
                    : "border-transparent font-medium text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
        {children}
      </div>
    </AccountingContext.Provider>
  );
}

/**
 * Obszar „Księgowość” (K1): nagłówek z miesiącem w adresie (`?year=&month=`),
 * znacznik trybu księgi roku i zakładki modułów, które są otwarte dla osoby.
 * Wyłączony moduł widzi tylko administrator (bramką jest serwer).
 */
export function AccountingShell({ children }: { children: ReactNode }) {
  const config = useLedgerConfig();
  return (
    <RequirePermission
      permissions={["finance_module"]}
      fallback={
        <QueryStateNotice
          state="forbidden"
          description="Księgowość wymaga uprawnienia „Moduł Finanse”. Poproś administratora o dostęp."
        />
      }
    >
      {config.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie Księgowości…</p>
      ) : config.isError ? (
        <QueryStateNotice state="error" onRetry={() => config.refetch()} />
      ) : config.isSuccess && !config.data.open ? (
        <div role="status" className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium">Księgowość jest wyłączona</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
            Moduł włącza administrator w Ustawieniach Księgowości, gdy Finanse zaczną w nim pracę.
          </p>
        </div>
      ) : config.data ? (
        <ShellBody config={config.data}>{children}</ShellBody>
      ) : null}
    </RequirePermission>
  );
}

export function SectionCard({
  title,
  aside,
  children,
  className,
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-border bg-card", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border/70 px-3.5 py-2">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {aside ? <div className="text-xs text-muted-foreground">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}
