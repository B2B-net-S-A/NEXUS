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

// 2026-07-20: kafelki raportowe kierują teraz WPROST do modułu Insights.
// Wcześniej wskazywały na /dynareporter/*, których katalogi zostały usunięte —
// działałyby przez przekierowanie 308, ale to zbędny przeskok i mylący adres
// w pasku. MINDY zostaje na własnej ścieżce: to czat AI, nie raport, i Insights
// nie ma dla niego następcy.
const MODULES: ModuleCard[] = [
  {
    section: "body-leasing",
    label: "KPI Body Leasing",
    description:
      "Weryfikacje, rekomendacje, interview, placementy tygodniowo per rekruter",
    href: "/insights?tab=rekrutacja",
    enabled: true, // B.2.1 deployed
  },
  {
    section: "sales",
    label: "KPI Sales",
    description: "Leady, oferty, wygrane / przegrane per sprzedawca",
    href: "/insights?tab=klienci",
    enabled: true, // B.2.2 deployed
  },
  {
    section: "delivery-lead",
    label: "KPI Delivery Lead",
    description: "Requesty, placementy, vacancy per DL miesięcznie",
    href: "/insights?tab=klienci",
    enabled: true, // B.2.3 deployed
  },
  {
    section: "placements",
    label: "Placementy",
    description: "Szczegółowe placementy per user × klient",
    href: "/insights?tab=rekrutacja",
    enabled: true, // B.2.4 deployed
  },
  {
    section: "clients-mrr",
    label: "Klienci + MRR",
    description: "Konsultanci u klientów + miesięczny MRR + finanse",
    href: "/insights?tab=klienci",
    enabled: true, // B.2.5 deployed
  },
  {
    section: "competitions",
    label: "Liga Mistrzów",
    description: "Kwartalny ranking + nagrody miesięczne",
    href: "/insights?tab=rekrutacja",
    enabled: true, // B.2.6 deployed
  },
  {
    section: "przetargi",
    label: "Przetargi",
    description: "Projekty publiczne — allocations, koszty, margin",
    href: "/insights?tab=zarzad",
    enabled: true, // B.2.7 deployed
  },
  {
    section: "board",
    label: "Rada Nadzorcza",
    description: "Miesięczny raport — placementy, MRR, P&L",
    href: "/insights?tab=zarzad",
    enabled: true, // B.2.8 deployed
  },
  {
    section: "sales-mgmt",
    label: "Sales — Zarządzanie",
    description: "Projekty, leady, oferty, aktywność tygodniowa",
    href: "/insights?tab=klienci",
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
    label: "Admin — Upload XLSX",
    description: "Wgrywanie Excel z KPI/MRR/finansów + historia uploadów",
    href: "/dynareporter/admin/upload",
    enabled: true, // B.2.11 deployed
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
          DynaReporter — archiwum. Raporty KPI są liczone automatycznie
          i dostępne w module Insights.
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

      {/* Link do reports.dynaminds.pl usunięty 2026-07-20 — domena zwraca 503
          (samodzielny DynaReporter padł przy awarii dysku 2026-07-17 i nie jest
          wskrzeszany, bo jego funkcje przejął NEXUS). Zostawienie odnośnika
          prowadziło zalogowanego użytkownika prosto w błąd. */}
      <p className="mt-6 text-xs text-muted-foreground">
        Moduły wyszarzone = brak uprawnień do sekcji. Admin nadaje dostęp
        w panelu administracyjnym. Bieżące raporty znajdziesz w{" "}
        <Link className="underline" href="/insights">
          Insights
        </Link>
        .
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
