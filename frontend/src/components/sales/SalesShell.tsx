"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { RequirePermission } from "@/components/RequirePermission";
import { permissionLabel } from "@/lib/permissions";

import { SalesMailboxStatus } from "./SalesMailboxStatus";

export type SalesSection =
  | "my-day"
  | "summary"
  | "opportunities"
  | "offers"
  | "companies"
  | "contacts"
  | "meetings"
  | "leads"
  | "tasks";

const SECTIONS: { value: SalesSection; label: string; href: string }[] = [
  { value: "my-day", label: "Mój dzień", href: "/sales/my-day" },
  { value: "summary", label: "Podsumowanie", href: "/sales/summary" },
  { value: "opportunities", label: "Szanse", href: "/sales/opportunities" },
  { value: "offers", label: "Oferty", href: "/sales/offers" },
  { value: "companies", label: "Firmy", href: "/sales/companies" },
  { value: "contacts", label: "Kontakty", href: "/sales/contacts" },
  { value: "meetings", label: "Spotkania", href: "/sales/meetings" },
  { value: "leads", label: "Leady", href: "/sales/leads" },
  { value: "tasks", label: "Zadania", href: "/sales/tasks" },
];

export function activeSection(pathname: string): SalesSection {
  if (pathname.startsWith("/sales/my-day")) return "my-day";
  if (pathname.startsWith("/sales/summary")) return "summary";
  if (pathname.startsWith("/sales/offers")) return "offers";
  if (pathname.startsWith("/sales/contacts")) return "contacts";
  if (pathname.startsWith("/sales/meetings")) return "meetings";
  if (pathname.startsWith("/sales/companies")) return "companies";
  if (pathname.startsWith("/sales/tasks")) return "tasks";
  if (pathname.startsWith("/sales/leads")) return "leads";
  return "opportunities";
}

export const NO_SALES_ACCESS = `Brakuje Ci uprawnienia „${permissionLabel(
  "sales_view",
)}”. Poproś administratora o dostęp (Ustawienia → Zespół i dostęp → Osoby i role).`;

interface SalesShellProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  /** Karta firmy albo szansy — bez zakładek obszaru. */
  hideNav?: boolean;
  children: ReactNode;
}

/**
 * Wspólna rama ekranów Sprzedaży (Atlas → NEXUS, 26.10.2026): bramka
 * „Sprzedaż: podgląd”, nagłówek i zakładki. O dostępie i tak decyduje backend
 * (403 z nazwą uprawnienia). Tytuł i zakładki stoją w jednym rzędzie, bo ekran
 * docelowy ma 720 px wysokości; opis i akcje dostają własną, niską linię.
 */
export function SalesShell({ title, description, actions, hideNav, children }: SalesShellProps) {
  const router = useRouter();
  const pathname = usePathname() ?? "/sales";
  return (
    <RequirePermission
      permissions={["sales_view"]}
      fallback={<QueryStateNotice state="forbidden" description={NO_SALES_ACCESS} />}
      pending={<p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>}
    >
      {hideNav ? (
        <div className="space-y-4">
          <PageHeader title={title} description={description} density="compact" actions={actions} />
          {children}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="flex flex-col gap-1 xl:flex-row xl:items-end xl:gap-8">
              <h1 className="shrink-0 pb-1 text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
              <div data-tour="sales.tabs" className="min-w-0 flex-1">
                <TabbedNav
                  ariaLabel="Sprzedaż"
                  tabs={SECTIONS.map(({ value, label }) => ({ value, label }))}
                  value={activeSection(pathname)}
                  onValueChange={(value) => {
                    const target = SECTIONS.find((section) => section.value === value);
                    if (target) router.push(target.href);
                  }}
                />
              </div>
            </div>
            {(description || actions) && (
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                {description && <p className="min-w-0 text-xs text-muted-foreground">{description}</p>}
                {actions && <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
              </div>
            )}
          </div>
          <SalesMailboxStatus />
          {children}
        </div>
      )}
    </RequirePermission>
  );
}
