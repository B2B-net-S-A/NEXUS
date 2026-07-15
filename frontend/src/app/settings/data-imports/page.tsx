"use client";

import { PageHeader } from "@/components/ds";
import { ImportTab } from "@/components/settings/admin/ImportTab";
import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary";
import { hasRole, useAuthStore } from "@/store/auth";

export default function DataImportsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return (
      <StatsBoundary isLoading>
        <span />
      </StatsBoundary>
    );
  }

  if (!hasRole(user, "admin")) {
    return (
      <StatsBoundary isError error={{ response: { status: 403 } }}>
        <span />
      </StatsBoundary>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 md:p-6">
      <PageHeader
        eyebrow="Ustawienia"
        title="Importy danych"
        description="Kontrolowane importy i backfille danych ATS. Operacje są dostępne wyłącznie administratorom."
      />
      <ImportTab />
    </div>
  );
}
