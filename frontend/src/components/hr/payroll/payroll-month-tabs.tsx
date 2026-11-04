"use client";

import type { ReactNode } from "react";

import type { HrConfig, HrModuleKey } from "@/lib/api/hr";

import { KsefInvoicesTab } from "./ksef/KsefInvoicesTab";
import { PayrollPaymentsTab } from "./payments/PayrollPaymentsTab";
import { SettlementsQueue } from "./SettlementsQueue";

/** Zakładka ekranu miesiąca Płac (etap 4): „Miesiąc · Rozliczenia · Faktury z KSeF · Przelewy”. */
export interface PayrollMonthTab {
  /** Wartość w adresie (`?view=`). */
  value: string;
  label: string;
  /** Zakładka jest widoczna, gdy moduł jest otwarty (admin widzi zawsze). */
  module: HrModuleKey;
  render: (props: { config: HrConfig; year: number; month: number }) => ReactNode;
}

/** Pierwsza zakładka — istniejący widok miesiąca (osoby, premie, zamknięcie). */
export const MONTH_VIEW = "month";

/**
 * Zakładki modułów w kolejności na pasku (po „Miesiącu”). Wyłącznie dla Płac —
 * przełożony widzi sam miesiąc swojego zespołu.
 */
export const PAYROLL_MONTH_TABS: PayrollMonthTab[] = [
  {
    value: "settlements",
    label: "Rozliczenia",
    module: "settlements",
    render: ({ year, month }) => <SettlementsQueue year={year} month={month} />,
  },
  {
    value: "ksef",
    label: "Faktury z KSeF",
    module: "settlements",
    render: ({ year, month }) => <KsefInvoicesTab year={year} month={month} />,
  },
  {
    value: "payments",
    label: "Przelewy",
    module: "settlements",
    render: ({ year, month }) => <PayrollPaymentsTab year={year} month={month} />,
  },
];

/** Pasek zakładek widoczny dla Płac; pusta lista = bez paska (sam miesiąc). */
export function payrollMonthTabs(
  config: Pick<HrConfig, "open_modules">,
  payroll: boolean,
  tabs: readonly PayrollMonthTab[] = PAYROLL_MONTH_TABS,
): { value: string; label: string }[] {
  if (!payroll) return [];
  const open = tabs.filter((tab) => config.open_modules[tab.module]);
  if (open.length === 0) return [];
  return [{ value: MONTH_VIEW, label: "Miesiąc" }, ...open.map(({ value, label }) => ({ value, label }))];
}
