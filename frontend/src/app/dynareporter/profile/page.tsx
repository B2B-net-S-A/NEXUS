"use client";

/**
 * DynaReporter Profile page (Faza B.1 — walidacja wzorca).
 *
 * Pierwszy moduł migracji — readonly endpoint pokazujący info o zalogowanym
 * userze + listę przyznanych sekcji DynaReportera. Walidacja end-to-end
 * pipeline'u: middleware → JWT → backend dependency → DB query → response →
 * React Query → Card UI.
 *
 * Po sukcesie tego smoke-test'a (manual click + Playwright) zaczynamy
 * migrację konkretnych dashboardów w B.2 (KPI Body Leasing → Sales → ...).
 */

import { useQuery } from "@tanstack/react-query";
import { dynareporterApi } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const SECTION_LABELS: Record<string, string> = {
  "body-leasing": "KPI Body Leasing",
  sales: "KPI Sales",
  "delivery-lead": "KPI Delivery Lead",
  placements: "Placementy",
  "clients-mrr": "Klienci + MRR",
  competitions: "Liga Mistrzów",
  przetargi: "Przetargi",
  board: "Rada Nadzorcza",
  "sales-mgmt": "Sales — Zarządzanie",
  mindy: "MINDY AI",
  admin: "Admin — DynaReporter",
};

export default function DynaReporterProfilePage() {
  const { hydrated, user } = useAuthStore();

  const profileQuery = useQuery({
    queryKey: ["dynareporter", "profile"],
    queryFn: dynareporterApi.profile,
    enabled: hydrated && !!user,
  });

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
        Zaloguj się żeby zobaczyć profil DynaReportera.
      </div>
    );
  }

  if (profileQuery.isLoading) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie profilu DynaReportera…
      </div>
    );
  }

  if (profileQuery.isError) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4 text-sm">
          <h2 className="font-semibold text-destructive">Błąd ładowania</h2>
          <p className="mt-1 text-muted-foreground">
            Nie udało się pobrać profilu DynaReportera. Spróbuj odświeżyć
            stronę. Jeśli problem występuje nadal — skontaktuj się z adminem.
          </p>
        </div>
      </div>
    );
  }

  const profile = profileQuery.data!;

  return (
    <div className="container mx-auto max-w-3xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">
          Profil DynaReporter
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Informacje o Twoim koncie + lista sekcji DynaReportera do których
          masz dostęp.
        </p>
      </header>

      <div className="rounded-lg border border-border bg-card p-5 space-y-4">
        <Field label="Nexus user ID" value={String(profile.user_id)} />
        <Field label="Email" value={profile.email} />
        <Field label="Pełna nazwa" value={profile.full_name} />
        <Field label="Rola w Nexusie" value={profile.role} />
        <Field
          label="DynaReporter legacy ID"
          value={
            profile.dynareporter_legacy_id !== null
              ? String(profile.dynareporter_legacy_id)
              : "(brak — konto utworzone w Nexusie, nigdy w DynaReporterze)"
          }
        />

        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Dostęp do modułów ({profile.allowed_sections.length})
          </p>
          {profile.allowed_sections.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Brak przyznanych sekcji. Skontaktuj się z adminem żeby otrzymać
              dostęp do konkretnych modułów DynaReportera.
            </p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-2">
              {profile.allowed_sections.map((section) => (
                <li
                  key={section}
                  className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                >
                  {SECTION_LABELS[section] ?? section}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <p className="mt-4 text-xs text-muted-foreground">
        Faza B.1 — walidacja wzorca przed migracją konkretnych dashboardów
        (B.2 KPI Body Leasing → Sales → Liga → ...). Stara wersja systemu:{" "}
        <a
          className="underline"
          href="https://reports.dynaminds.pl"
          target="_blank"
          rel="noreferrer"
        >
          reports.dynaminds.pl
        </a>{" "}
        (live podczas migracji).
      </p>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {label}
      </p>
      <p className="mt-1 text-sm">{value}</p>
    </div>
  );
}
