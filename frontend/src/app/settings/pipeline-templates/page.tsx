"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { PipelineTemplatesTab } from "@/components/settings/PipelineTemplatesTab";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

/**
 * Edytor procesów rekrutacyjnych — lustro bramki z middleware
 * (`/settings/pipeline-templates`: admin/Delivery Lead z zapisem sekcji
 * Pipeline) i z zakładki „Procesy" w /settings.
 *
 * UAT A-B04: w podglądzie jako użytkownik (i przy nieaktualnym claimie
 * sekcji) rola bez prawa zapisu dostawała pełny edytor, choć każda mutacja
 * kończy się 403. Odmowa ma wyglądać jak odmowa.
 */
export default function PipelineTemplatesPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  const canManage =
    hasRole(user, "admin", "delivery_lead") &&
    hasSectionAccess(user, "pipeline", "write");

  return (
    <div className="min-h-screen bg-muted dark:bg-card">
      <div className="max-w-7xl mx-auto px-0 py-2 md:px-4 md:py-8">
        {canManage ? (
          <PipelineTemplatesTab />
        ) : (
          <QueryStateNotice
            state="forbidden"
            description="Procesy rekrutacyjne konfiguruje administrator albo Delivery Lead z prawem zapisu sekcji Pipeline."
          />
        )}
      </div>
    </div>
  );
}
