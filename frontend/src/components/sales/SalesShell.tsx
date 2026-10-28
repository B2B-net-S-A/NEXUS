"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { RequirePermission } from "@/components/RequirePermission";
import { permissionLabel } from "@/lib/permissions";

export type SalesSection = "summary" | "opportunities" | "companies" | "contacts" | "leads" | "tasks";

const SECTIONS: { value: SalesSection; label: string; href: string }[] = [
  { value: "summary", label: "Podsumowanie", href: "/sales/summary" },
  { value: "opportunities", label: "Szanse", href: "/sales" },
  { value: "companies", label: "Firmy", href: "/sales/companies" },
  { value: "contacts", label: "Kontakty", href: "/sales/contacts" },
  { value: "leads", label: "Leady", href: "/sales/leads" },
  { value: "tasks", label: "Zadania", href: "/sales/tasks" },
];

export function activeSection(pathname: string): SalesSection {
  if (pathname.startsWith("/sales/summary")) return "summary";
  if (pathname.startsWith("/sales/contacts")) return "contacts";
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
 * „Sprzedaż: podgląd”, nagłówek i zakładki Szanse · Firmy · Zadania.
 * O dostępie i tak decyduje backend (403 z nazwą uprawnienia).
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
      <div className="space-y-4">
        <PageHeader title={title} description={description} density="compact" actions={actions} />
        {!hideNav && (
          <TabbedNav
            ariaLabel="Sprzedaż"
            tabs={SECTIONS.map(({ value, label }) => ({ value, label }))}
            value={activeSection(pathname)}
            onValueChange={(value) => {
              const target = SECTIONS.find((section) => section.value === value);
              if (target) router.push(target.href);
            }}
          />
        )}
        {children}
      </div>
    </RequirePermission>
  );
}
