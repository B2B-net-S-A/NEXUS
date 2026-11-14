"use client";

import { useState } from "react";

import { SegmentedRadio } from "@/components/ui/segmented-radio";

import { useAccounting } from "../AccountingShell";
import { PayrollFilesView } from "./PayrollFilesView";
import { PayrollListView } from "./PayrollListView";
import { PayrollParametersView } from "./PayrollParametersView";
import { PayrollPeopleView } from "./PayrollPeopleView";

export type PayrollViewKey = "list" | "people" | "parameters" | "files";

const VIEWS: readonly { value: PayrollViewKey; label: string }[] = [
  { value: "list", label: "Lista płac" },
  { value: "people", label: "Dane osób" },
  { value: "parameters", label: "Parametry" },
  { value: "files", label: "Pliki ZUS i PIT" },
];

/** Widok z adresu (`?view=people`); domyślnie lista płac. */
export function readView(search: string): PayrollViewKey {
  const value = new URLSearchParams(search).get("view");
  return VIEWS.some((view) => view.value === value) ? (value as PayrollViewKey) : "list";
}

function writeView(view: PayrollViewKey) {
  const params = new URLSearchParams(window.location.search);
  if (view === "list") params.delete("view");
  else params.set("view", view);
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

/**
 * Zakładka „Lista płac” Księgowości (K7a): lista płac miesiąca z nagłówka,
 * dane płacowe osób, parametry płac i pliki ZUS i PIT. Moduł `payroll`
 * i uprawnienie „Rozliczenia” sprawdza serwer; zakładka chowa się bez nich
 * (`visibleTabs`).
 */
export function PayrollView() {
  const { config, period } = useAccounting();
  // Treść obszaru renderuje się dopiero po konfiguracji z API (tylko w przeglądarce).
  const [view, setView] = useState<PayrollViewKey>(() =>
    typeof window === "undefined" ? "list" : readView(window.location.search),
  );
  const payrollModule = config.modules.find((item) => item.key === "payroll");

  if (!payrollModule?.open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Moduł „{payrollModule?.label ?? "Lista płac"}” jest wyłączony — włącza go administrator w Ustawieniach Księgowości.
      </p>
    );
  }
  if (!config.me.payroll) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Listy płac widzą osoby z uprawnieniem „Rozliczenia” i administrator.
      </p>
    );
  }

  const choose = (next: PayrollViewKey) => {
    setView(next);
    writeView(next);
  };

  return (
    <div className="space-y-3">
      <SegmentedRadio label="Widok listy płac" size="sm" value={view} onChange={choose} options={VIEWS} />
      {view === "list" ? <PayrollListView year={period.year} month={period.month} /> : null}
      {view === "people" ? <PayrollPeopleView /> : null}
      {view === "parameters" ? <PayrollParametersView today={config.today} /> : null}
      {view === "files" ? <PayrollFilesView year={period.year} month={period.month} today={config.today} /> : null}
    </div>
  );
}
