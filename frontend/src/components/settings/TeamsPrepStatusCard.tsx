"use client";

import { useQuery } from "@tanstack/react-query";
import { Video } from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";

type TeamsPrepHealth = "unconfigured" | "misconfigured" | "degraded" | "healthy";

const LABELS: Record<TeamsPrepHealth, { text: string; className: string }> = {
  unconfigured: { text: "Nieskonfigurowane", className: "bg-muted text-muted-foreground" },
  misconfigured: { text: "Brak poświadczeń", className: "bg-destructive/15 text-destructive" },
  degraded: { text: "Problemy z dostępem", className: "bg-warning-muted text-warning-muted-foreground" },
  healthy: { text: "Działa", className: "bg-success-muted text-success-muted-foreground" },
};

/**
 * Stan integracji „Prepy w Teams” (0355) — zastępuje kartę Fireflies.
 * Czyta `checks.teams_prep` z `/api/health` (sonda informacyjna).
 */
export function TeamsPrepStatusCard() {
  const health = useQuery({
    queryKey: ["health", "teams-prep"],
    queryFn: () =>
      api
        .get<{ checks?: Record<string, string> }>("/api/health")
        .then((r) => r.data.checks?.teams_prep as TeamsPrepHealth | undefined),
    staleTime: 60_000,
  });
  const status = health.data ? LABELS[health.data] : null;

  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Video className="h-6 w-6 text-primary" aria-hidden />
        </div>
        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-bold text-foreground">Prepy w Teams</h3>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                status ? status.className : "bg-muted text-muted-foreground",
              )}
            >
              {health.isPending
                ? "Sprawdzanie…"
                : health.isError
                  ? "Nie udało się sprawdzić"
                  : (status?.text ?? "Nieznany stan")}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            Prep 1 i Prep 2 z kandydatem zakładane z NEXUSA w kalendarzu „Rozmowy u klienta”
            powstają jako spotkania Teams z automatyczną transkrypcją. Po spotkaniu NEXUS pobiera
            transkrypt, zapisuje notatkę u kandydata i ocenia prep.
          </p>
          <p className="text-xs text-muted-foreground">
            Włączenie wymaga jednorazowej konfiguracji aplikacji „NEXUS Teams Prep” w Azure
            (uprawnienia, polityka dostępu do grupy DL i rekruterów) przez administratora Microsoft 365.
          </p>
        </div>
      </div>
    </div>
  );
}
