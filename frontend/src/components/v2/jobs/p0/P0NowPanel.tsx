"use client";

import Link from "next/link";
import { Flame } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useP0Jobs, type P0Job } from "@/lib/api/jobP0";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import { isP0Active } from "@/lib/job-p0";

import { P0Chip } from "./P0Chip";
import { useNow } from "./useNow";

/** Ile wierszy panel pokazuje od razu (bez limitu P0 naraz, decyzja 27.10.2026). */
export const P0_PANEL_VISIBLE = 3;

function people(item: P0Job): string {
  const names = item.recruiters.map((name) => shortenPersonName(name) ?? name);
  if (names.length === 0) return "bez rekrutera";
  return names.join(", ");
}

/**
 * Panel „P0 — ultrapilne teraz” (27.10.2026) — na górze pulpitu KAŻDEJ osoby,
 * nad kafelkami i niezależnie od własnego układu (decyzja Artura), oraz na
 * Daily. Znika, gdy nie ma żadnego P0; błąd zapytania (np. konto bez sekcji
 * Rekrutacje) też go chowa, bo panel nie jest jedynym miejscem P0.
 */
export function P0NowPanel({ className }: { className?: string }) {
  const now = useNow();
  const query = useP0Jobs();
  const items = (query.data?.items ?? []).filter((item) =>
    isP0Active({ is_p0: true, p0_until: item.p0_until }, now),
  );
  if (!query.isSuccess || items.length === 0) return null;
  const shown = items.slice(0, P0_PANEL_VISIBLE);
  const hidden = items.length - shown.length;
  return (
    <section
      aria-label="P0 — ultrapilne teraz"
      className={
        "grid gap-2 rounded-xl border border-destructive/35 bg-destructive-muted p-3 " +
        (className ?? "")
      }
      data-testid="p0-now-panel"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-destructive-muted-foreground">
        <h2 className="flex items-center gap-1.5 text-base font-bold">
          <Flame className="h-4 w-4" aria-hidden="true" />
          P0 — ultrapilne teraz · {items.length}
        </h2>
        <p className="text-xs">Najpierw te rekrutacje, potem reszta.</p>
        <p className="text-xs sm:ml-auto">Ustawia Head of Recruitment · znika samo po terminie</p>
      </div>
      <ul className="grid gap-2">
        {shown.map((item) => (
          <li
            key={item.job_id}
            className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 rounded-lg border border-destructive/25 bg-card px-3 py-2 sm:grid-cols-[auto_minmax(0,1fr)_auto]"
            data-testid="p0-now-row"
          >
            <P0Chip until={item.p0_until} reason={item.p0_reason} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold" title={item.title}>
                {item.title}
                {item.client_name ? (
                  <span className="font-normal text-muted-foreground"> · {item.client_name}</span>
                ) : null}
              </p>
              <p className="break-words text-xs text-muted-foreground">
                {item.p0_reason ? `„${item.p0_reason}”` : null}
                {item.p0_set_by_name ? ` — ${shortenPersonName(item.p0_set_by_name) ?? item.p0_set_by_name}` : null}
                {" · "}
                {people(item)}
                {item.delivery_lead_name
                  ? ` · DL: ${shortenPersonName(item.delivery_lead_name) ?? item.delivery_lead_name}`
                  : null}
              </p>
            </div>
            <Button asChild size="sm" variant="outline" className="col-span-2 justify-self-start bg-card sm:col-span-1">
              <Link href={`/jobs/${item.job_id}`}>Otwórz tablicę</Link>
            </Button>
          </li>
        ))}
      </ul>
      {hidden > 0 ? (
        <p className="text-xs text-destructive-muted-foreground">
          I jeszcze {hidden} — wszystkie są na górze listy rekrutacji i w górnym pasku.
        </p>
      ) : null}
    </section>
  );
}
