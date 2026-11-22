"use client";

import { useQuery } from "@tanstack/react-query";

import { SectionNav, type SectionNavGroup, type SectionNavItem } from "@/components/ds/SectionNav";
import { visibleTabs } from "@/components/accounting/ledger-model";
import { useLedgerConfig } from "@/lib/api/accounting";
import { useInvoicingModule } from "@/lib/api/client-invoicing";
import { useSettlementsModule } from "@/lib/api/client-settlements";
import { ORDER_CHANGES_SUMMARY_KEY, financeApi } from "@/lib/api/finance";
import { useAccountingModule } from "@/lib/api/finance-ledger";
import { useHrConfig } from "@/lib/api/hr";
import type { FinanceViewMode } from "@/lib/finance-view";
import { hasPermission } from "@/lib/permissions";
import { ORDER_CHANGES_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/** Klucz pozycji: widok `/finance?view=` albo trasa Księgi. */
export function financeItemKey(view: FinanceViewMode): string {
  return `fin:${view}`;
}

export function ledgerItemKey(href: string): string {
  return `acc:${href}`;
}

/**
 * Zawsze z `?view=`: samo `/finance` to wejście do modułu, które przy otwartej
 * Księdze prowadzi na Przegląd miesiąca (`FinancePage`).
 */
function financeHref(view: FinanceViewMode): string {
  return `/finance?view=${view}`;
}

/** Nazwy zakładek Księgi w Finansach — krótsze tam, gdzie grupa mówi resztę. */
const LEDGER_LABELS: Record<string, string> = {
  "/accounting": "Miesiąc",
  "/accounting/bank": "Wyciągi bankowe",
  "/accounting/payroll": "Lista płac",
};

/**
 * Jedna nawigacja modułu „Finanse” (makieta 18.11.2026) dla dwóch dzisiejszych
 * modułów: Finansów (`/finance?view=`, plan eBI24 E0–E5) i Księgowości
 * (`/accounting/*`, księga K1–K9). Grupy idą za miesiącem pracy: przychody,
 * zamówienia, koszty, księga, raporty. Widoczność pozycji to te same
 * przełączniki i uprawnienia co dotąd — bramką dalej jest serwer.
 */
export function FinanceAreaNav({
  active,
  ledgerQuery = "",
}: {
  active: string;
  /** `?year=&month=` Księgi — przejście między jej ekranami trzyma miesiąc. */
  ledgerQuery?: string;
}) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const hasModule = hasPermission(user, "finance_module");
  const ordersWork = hasPermission(user, "orders_work");
  const canImportMd = !impersonating && ordersWork;

  const invoicingOpen = useInvoicingModule(hasModule).data?.open === true;
  const settlementsOpen = useSettlementsModule(hasModule).data?.open === true;
  const approvalsOpen = useHrConfig(hasModule).data?.open_modules?.approvals === true;
  const accountingOpen = useAccountingModule(hasModule).data?.open === true;
  const ledger = useLedgerConfig(hasModule).data;
  const ledgerTabs = ledger?.open ? visibleTabs(ledger) : [];
  const ledgerHrefs = new Set(ledgerTabs.map((tab) => tab.href));

  const summary = useQuery({
    queryKey: ORDER_CHANGES_SUMMARY_KEY,
    queryFn: async () => (await financeApi.getOrderChangesSummary()).data,
    enabled: hasModule || ordersWork,
    refetchInterval: ORDER_CHANGES_POLL_MS,
  });

  const fin = (
    view: FinanceViewMode,
    label: string,
    show = true,
    count?: number,
    tourId?: string,
  ): SectionNavItem | null =>
    show ? { key: financeItemKey(view), label, href: financeHref(view), count, tourId } : null;
  const acc = (href: string, label?: string): SectionNavItem | null => {
    const tab = ledgerTabs.find((item) => item.href === href);
    if (!tab || !ledgerHrefs.has(href)) return null;
    return { key: ledgerItemKey(href), label: label ?? LEDGER_LABELS[href] ?? tab.label, href: `${href}${ledgerQuery}` };
  };
  const items = (...list: (SectionNavItem | null)[]): SectionNavItem[] =>
    list.filter((item): item is SectionNavItem => item !== null);

  const groups: SectionNavGroup[] = [
    { key: "overview", label: "Przegląd", items: items(acc("/accounting")) },
    {
      key: "revenue",
      label: "Przychody",
      items: items(
        fin("settlements", "Rozliczenia klientów", settlementsOpen),
        fin("sales-invoices", "Faktury do klientów", invoicingOpen),
      ),
    },
    {
      key: "orders",
      label: "Zamówienia",
      items: items(
        {
          ...fin("order-changes", "Zmiany w zamówieniach", true, summary.data?.todo ?? 0)!,
          countLabel: `${summary.data?.todo ?? 0} do zrobienia w bieżącym miesiącu`,
        },
        fin("order-pdfs", "Zamówienia PDF"),
        fin("md", "Import zużycia MD", canImportMd),
        fin("rate-divergences", "Rozjazdy stawek", hasModule, 0, "finance.rate-divergences"), // data-tour="finance.rate-divergences"
      ),
    },
    {
      key: "costs",
      label: "Koszty",
      items: items(
        fin("costs", "Faktury kosztowe", accountingOpen, 0, "finance.costs"), // data-tour="finance.costs"
        fin("approved-expenses", "Wydatki ze zgodą", approvalsOpen),
        fin("booking", "Księgowanie faktur", accountingOpen),
        fin("payments", "Przelewy", accountingOpen),
        fin("counterparties", "Kontrahenci", accountingOpen),
        acc("/accounting/payroll"),
      ),
    },
    {
      key: "ledger",
      label: "Księga",
      items: items(
        acc("/accounting/sources"),
        acc("/accounting/documents"),
        acc("/accounting/bank"),
        acc("/accounting/settlements"),
        acc("/accounting/automations"),
        acc("/accounting/vat"),
        acc("/accounting/assets"),
        acc("/accounting/symfonia"),
      ),
    },
    {
      key: "reports",
      label: "Raporty",
      items: items(
        fin("results", "Wyniki miesięczne", hasModule),
        acc("/accounting/trial-balance"),
        acc("/accounting/reports"),
        fin("archive", "Archiwum wyników", hasModule),
        fin("ebi24-archive", "Archiwum eBI24", accountingOpen),
      ),
    },
    {
      key: "settings",
      label: "Ustawienia",
      items: items(
        acc("/accounting/chart", "Plan kont"),
        fin("accounts", "Reguły dekretu", accountingOpen),
        acc("/accounting/settings", "Ustawienia księgi"),
      ),
    },
  ];

  // `finance.modes` = kotwica przewodnika Jarvisa i Startu dla Finansów.
  return (
    <div data-help="finance.modes" data-tour="finance.sections">
      <SectionNav label="Sekcje modułu Finanse" groups={groups} activeItem={active} />
    </div>
  );
}
