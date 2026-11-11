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
  | "calling"
  | "summary"
  | "opportunities"
  | "offers"
  | "companies"
  | "contacts"
  | "meetings"
  | "leads"
  | "tasks";

// Makieta 11.11.2026: siedem zakładek zamiast dziesięciu. Kontakty, Zadania i Podsumowanie
// zostają pod swoimi adresami, ale wchodzi się do nich przełącznikiem w zakładce-rodzicu.
const SECTIONS: { value: SalesSection; label: string; href: string }[] = [
  { value: "my-day", label: "Mój dzień", href: "/sales/my-day" },
  { value: "calling", label: "Dzwonienie", href: "/sales/calling" },
  { value: "opportunities", label: "Szanse", href: "/sales/opportunities" },
  { value: "offers", label: "Oferty", href: "/sales/offers" },
  { value: "companies", label: "Firmy", href: "/sales/companies" },
  { value: "meetings", label: "Spotkania", href: "/sales/meetings" },
  { value: "leads", label: "Leady", href: "/sales/leads" },
];

const SUB_VIEWS: Partial<Record<SalesSection, { label: string; href: string }[]>> = {
  "my-day": [
    { label: "Dziś", href: "/sales/my-day" },
    { label: "Wszystkie zadania", href: "/sales/tasks" },
  ],
  opportunities: [
    { label: "Lejek", href: "/sales/opportunities" },
    { label: "Podsumowanie", href: "/sales/summary" },
  ],
  companies: [
    { label: "Firmy", href: "/sales/companies" },
    { label: "Osoby", href: "/sales/contacts" },
  ],
};

/** Zakładka-rodzic na pasku: Kontakty pod Firmami, Zadania pod „Moim dniem”, Podsumowanie pod Szansami. */
function tabOf(section: SalesSection): SalesSection {
  if (section === "contacts") return "companies";
  if (section === "tasks") return "my-day";
  if (section === "summary") return "opportunities";
  return section;
}

function SubViews({ pathname }: { pathname: string }) {
  const router = useRouter();
  const views = SUB_VIEWS[tabOf(activeSection(pathname))];
  if (!views) return null;
  return (
    <div role="tablist" aria-label="Widok" className="inline-flex rounded-md border border-border bg-card p-0.5 text-xs">
      {views.map((view) => {
        const active = pathname.startsWith(view.href);
        return (
          <button
            key={view.href}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => router.push(view.href)}
            className={`rounded px-2 py-1 ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            {view.label}
          </button>
        );
      })}
    </div>
  );
}

export function activeSection(pathname: string): SalesSection {
  if (pathname.startsWith("/sales/my-day")) return "my-day";
  if (pathname.startsWith("/sales/calling")) return "calling";
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
            <div className="flex flex-col gap-1 xl:flex-row xl:items-end xl:gap-4">
              <h1 className="shrink-0 pb-1 text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
              <div data-tour="sales.tabs" className="min-w-0 flex-1">
                <TabbedNav
                  ariaLabel="Sprzedaż"
                  // Dziesięć zakładek w jednym rzędzie przy 1280 px: węższe odstępy,
                  // bo drugi rząd zabiera listom wysokość na ekranie 720 px.
                  listClassName="[&>button]:px-2.5"
                  tabs={SECTIONS.map(({ value, label }) => ({ value, label }))}
                  value={tabOf(activeSection(pathname))}
                  onValueChange={(value) => {
                    const target = SECTIONS.find((section) => section.value === value);
                    if (target) router.push(target.href);
                  }}
                />
              </div>
            </div>
            {(description || actions || SUB_VIEWS[tabOf(activeSection(pathname))]) && (
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <div className="flex min-w-0 items-center gap-3">
                  <SubViews pathname={pathname} />
                  {description && <p className="min-w-0 text-xs text-muted-foreground">{description}</p>}
                </div>
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
