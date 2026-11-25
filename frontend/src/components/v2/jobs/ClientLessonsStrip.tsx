"use client";

/**
 * „Zasady klienta ze spotkań” na stronie otwartej rekrutacji (Insights →
 * Przegrane, 25.11.2026): wnioski „ten klient” i „wszyscy klienci” z przeglądu
 * przegranych z DL. Jedna linia — przy 1280 × 720 nie spycha Tablicy.
 * Bez zasad pasek się nie pokazuje; błąd odczytu też nic nie pokazuje, bo pasek
 * to podpowiedź, nie dane rekrutacji.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";

import { LOST_REVIEW_ROLES } from "@/lib/insights-roles";
import { lostReviewApi, lostReviewKeys } from "@/lib/lost-review";
import { hasRole, useAuthStore } from "@/store/auth";

export function ClientLessonsStrip({ clientId }: { clientId: number | null }) {
  const user = useAuthStore((s) => s.user);
  const allowed = Boolean(user) && hasRole(user, ...LOST_REVIEW_ROLES);
  const query = useQuery({
    queryKey: lostReviewKeys.clientRules(clientId ?? 0),
    queryFn: () => lostReviewApi.clientRules(clientId as number),
    enabled: allowed && clientId != null,
    staleTime: 5 * 60_000,
  });
  const rules = query.isSuccess ? query.data : [];
  if (!allowed || rules.length === 0) return null;
  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-info/40 bg-info-muted px-3 py-1.5 text-xs text-info-muted-foreground"
      data-testid="client-lessons-strip"
    >
      <Lightbulb className="size-4 shrink-0" aria-hidden="true" />
      <span className="shrink-0 font-semibold">Zasady ze spotkań:</span>
      <span className="min-w-0 truncate" title={rules.map((r) => r.text).join(" · ")}>
        {rules.map((r) => r.text).join(" · ")}
      </span>
      <Link href="/insights?tab=przegrane" className="ml-auto shrink-0 font-semibold hover:underline">
        Przegrane
      </Link>
    </div>
  );
}
