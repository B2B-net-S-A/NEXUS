"use client";

/**
 * DynaReporter landing page (B.1).
 *
 * Lista modułów DynaReportera + status dostępu per user. Klikalne karty
 * prowadzą do każdego dashboardu (póki co tylko `/dynareporter/profile`
 * jest zaimplementowany — reszta w B.2).
 */

import Link from "next/link";
import { useAuthStore, hasSection, DynaReporterSection } from "@/store/auth";
import { cn } from "@/lib/utils";

interface ModuleCard {
  section: DynaReporterSection;
  label: string;
  description: string;
  href: string;
  enabled: boolean;
}

const MODULES: ModuleCard[] = [
  {
    section: "body-leasing",
    label: "KPI Body Leasing",
    description:
      "Weryfikacje, rekomendacje, interview, placementy tygodniowo per rekruter",
    href: "/dynareporter/body-leasing",
    enabled: true, // B.2.1 deployed
  },
  {
    section: "sales",
    label: "KPI Sales",
    description: "Leady, oferty, wygrane / przegrane per sprzedawca",
    href: "/dynareporter/sales",
    enabled: true, // B.2.2 deployed
  },
  {
    section: "delivery-lead",
    label: "KPI Delivery Lead",
    description: "Requesty, placementy, vacancy per DL miesięcznie",
    href: "/dynareporter/delivery-lead",
    enabled: true, // B.2.3 deployed
  },
  {
    section: "placements",
    label: "Placementy",
    description: "Szczegółowe placementy per user × klient",
    href: "/dynareporter/placements",
    enabled: true, // B.2.4 deployed
  },
  {
    section: "clients-mrr",
    label: "Klienci + MRR",
    description: "Konsultanci u klientów + miesięczny MRR + finanse",
    href: "/dynareporter/clients-mrr",
    enabled: true, // B.2.5 deployed
  },
  {
    section: "competitions",
    label: "Liga Mistrzów",
    description: "Kwartalny ranking + nagrody miesięczne",
    href: "/dynareporter/competitions",
    enabled: true, // B.2.6 deployed
  },
  {
    section: "przetargi",
    label: "Przetargi",
    description: "Projekty publiczne — allocations, koszty, margin",
    href: "/dynareporter/przetargi",
    enabled: true, // B.2.7 deployed
  },
  {
    section: "board",
    label: "Rada Nadzorcza",
    description: "Miesięczny raport — placementy, MRR, P&L",
    href: "/dynareporter/board",
    enabled: true, // B.2.8 deployed
  },
  {
    section: "sales-mgmt",
    label: "Sales — Zarządzanie",
    description: "Projekty, leady, oferty, aktywność tygodniowa",
    href: "/dynareporter/sales-mgmt",
    enabled: true, // B.2.9 deployed
  },
  {
    section: "mindy",
    label: "MINDY AI",
    description: "Asystent AI z kontekstem KPI",
    href: "/dynareporter/mindy",
    enabled: true, // B.2.10 deployed
  },
  {
    section: "admin",
    label: "Admin — DynaReporter",
    description: "Zarządzanie dostępem do sekcji per user",
    href: "/dynareporter/admin",
    enabled: false,
  },
];

export default function DynaReporterLandingPage() {
  const { user, hydrated } = useAuthStore();

  if (!hydrated) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie sesji…
      </div>
    );
  }

  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć raporty.
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-6xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Raporty KPI</h1>
        <p className="text-sm text-muted-foreground mt-1">
          DynaReporter — system raportowania KPI DynaMinds. Migracja
          z reports.dynaminds.pl (Faza B w toku).
        </p>
      </header>

      <div className="mb-4">
        <Link
          href="/dynareporter/profile"
          className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-accent"
        >
          Twój profil + lista dostępnych modułów →
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {MODULES.map((m) => {
          const hasAccess = hasSection(user, m.section);
          const clickable = m.enabled && hasAccess;
          return (
            <div
              key={m.section}
              className={cn(
                "rounded-lg border bg-card p-4 transition-colors",
                clickable
                  ? "border-border hover:border-primary cursor-pointer"
                  : "border-border opacity-60"
              )}
            >
              {clickable ? (
                <Link href={m.href} className="block">
                  <ModuleCardContent module={m} hasAccess={hasAccess} />
                </Link>
              ) : (
                <ModuleCardContent module={m} hasAccess={hasAccess} />
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-6 text-xs text-muted-foreground">
        Moduły wyszarzone = jeszcze nie zmigrowane (B.2 w toku) lub brak
        uprawnień. Admin nadaje dostęp do sekcji w panelu administracyjnym.
        Stara wersja: <a className="underline" href="https://reports.dynaminds.pl" target="_blank" rel="noreferrer">reports.dynaminds.pl</a> (live podczas migracji).
      </p>
    </div>
  );
}

function ModuleCardContent({
  module: m,
  hasAccess,
}: {
  module: ModuleCard;
  hasAccess: boolean;
}) {
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-sm">{m.label}</h3>
        <div className="flex flex-col gap-1 items-end">
          {!m.enabled && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
              Wkrótce
            </span>
          )}
          {!hasAccess && m.enabled && (
            <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-destructive">
              Brak dostępu
            </span>
          )}
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
        {m.description}
      </p>
    </>
  );
}
