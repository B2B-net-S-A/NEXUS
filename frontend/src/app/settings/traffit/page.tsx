"use client";

import { TraffitIntegrationPanel } from "@/components/settings/TraffitIntegrationPanel";
import { hasRole, useAuthStore } from "@/store/auth";

export default function TraffitSettingsPage() {
  const { user, hydrated } = useAuthStore();

  if (!hydrated) {
    return (
      <div className="mx-auto max-w-[1180px] space-y-4">
        <div className="h-24 animate-pulse rounded-lg bg-muted" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-36 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  return <TraffitIntegrationPanel isAdmin={hasRole(user, "admin")} />;
}
