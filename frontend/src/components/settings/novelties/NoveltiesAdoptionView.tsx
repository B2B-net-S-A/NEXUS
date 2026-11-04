"use client";

/**
 * Ustawienia → „Nowości — kto już umie” (decyzja Artura 28.10.2026).
 * Widok bez zapytań; kontener: `app/settings/nowosci/page.tsx`.
 *
 * Zaliczenie liczy się z pracy (użycie funkcji albo przeklikanie). Imienną
 * listę widzą tylko admin i Head of Recruitment.
 */

import { useState } from "react";
import {
  Bell,
  CheckCircle2,
  Eye,
  EyeOff,
  MousePointerClick,
} from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AdoptionState, NoveltyAdoption } from "@/lib/novelties/api";

export type AdoptionLoad =
  | { status: "loading" }
  | { status: "error"; forbidden: boolean; message: string }
  | { status: "success"; items: NoveltyAdoption[] };

const TIER_LABEL: Record<NoveltyAdoption["tier"], string> = {
  dot: "Drobiazg",
  tour: "Do przeklikania",
  process: "Zmiana procesu",
};

const STATE_LABEL: Record<AdoptionState, string> = {
  used: "Użył(a) w pracy",
  tour: "Przeklikał(a)",
  dot: "Kliknął(a)",
  seen: "Widział(a) kropkę",
  untouched: "Jeszcze nie był(a) na tym ekranie",
};

const KNOWS: readonly AdoptionState[] = ["used", "tour", "dot"];

function StateIcon({ state }: { state: AdoptionState }) {
  if (state === "used" || state === "dot")
    return <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />;
  if (state === "tour")
    return (
      <MousePointerClick className="h-4 w-4 text-success" aria-hidden="true" />
    );
  if (state === "seen")
    return <Eye className="h-4 w-4 text-warning" aria-hidden="true" />;
  return (
    <EyeOff className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
  );
}

function knowCount(item: NoveltyAdoption): number {
  return KNOWS.reduce((sum, s) => sum + item.counts[s], 0);
}

function formatDay(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}`;
}

export interface NoveltiesAdoptionViewProps {
  load: AdoptionLoad;
  onRetry: () => void;
  onRemind: (noveltyId: string, userIds: number[]) => void;
  remindingId: string | null;
}

export function NoveltiesAdoptionView({
  load,
  onRetry,
  onRemind,
  remindingId,
}: NoveltiesAdoptionViewProps) {
  const [selected, setSelected] = useState<string | null>(null);

  const header = (
    <PageHeader
      title="Nowości — kto już umie"
      description="Zaliczenie liczy się z pracy: użycie funkcji albo przeklikanie. Przypomnienie przywraca kartę przy kropce, bez maila."
    />
  );

  if (load.status === "loading") {
    return (
      <div className="mx-auto max-w-7xl space-y-5">
        {header}
        <p className="text-sm text-muted-foreground">Wczytuję nowości…</p>
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div className="mx-auto max-w-7xl space-y-5">
        {header}
        <QueryStateNotice
          state={load.forbidden ? "forbidden" : "error"}
          description={load.message}
          onRetry={load.forbidden ? undefined : onRetry}
        />
      </div>
    );
  }
  if (load.items.length === 0) {
    return (
      <div className="mx-auto max-w-7xl space-y-5">
        {header}
        <EmptyState
          title="Brak nowości z ostatnich 90 dni"
          description="Nowość pojawia się tu, gdy PR z funkcją doda wpis do rejestru nowości."
        />
      </div>
    );
  }

  const current = load.items.find((i) => i.id === selected) ?? load.items[0];
  const notYet = current.people.filter((p) => !KNOWS.includes(p.state));

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      {header}
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Nowość</th>
              <th className="px-3 py-2 font-medium">Rodzaj</th>
              <th className="px-3 py-2 font-medium">Umie</th>
              <th className="w-[240px] px-3 py-2 font-medium">Skąd wiadomo</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {load.items.map((item) => {
              const knows = knowCount(item);
              const pct = (n: number) =>
                item.audience ? (n / item.audience) * 100 : 0;
              return (
                <tr
                  key={item.id}
                  className={`cursor-pointer ${item.id === current.id ? "bg-primary/5" : "hover:bg-muted/40"}`}
                  onClick={() => setSelected(item.id)}
                  aria-selected={item.id === current.id}
                  data-testid={`adoption-row-${item.id}`}
                >
                  <td className="px-4 py-2.5">
                    <p className="font-semibold">{item.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatDay(item.shipped_on)}
                      {item.pr ? ` · #${item.pr}` : ""} · {item.where}
                      {item.active ? "" : " · już nie pokazujemy"}
                    </p>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge
                      size="sm"
                      variant={
                        item.start || item.tier === "process"
                          ? "warning"
                          : item.tier === "tour"
                            ? "soft"
                            : "neutral"
                      }
                    >
                      {item.start ? "Start" : TIER_LABEL[item.tier]}
                    </Badge>
                  </td>
                  <td className="px-3 py-2.5 tabular-nums">
                    <span className="font-semibold">{knows}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      / {item.audience}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <div
                      className="flex h-2 overflow-hidden rounded-full bg-muted"
                      aria-hidden="true"
                    >
                      <span
                        className="bg-success"
                        style={{
                          width: `${pct(item.counts.used + item.counts.dot)}%`,
                        }}
                      />
                      <span
                        className="bg-success/60"
                        style={{ width: `${pct(item.counts.tour)}%` }}
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground tabular-nums">
                      w pracy {item.counts.used + item.counts.dot} · przeklikali{" "}
                      {item.counts.tour} · widzieli {item.counts.seen}
                    </p>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section
        className="rounded-xl border border-border bg-card"
        aria-label={`Kto umie: ${current.title}`}
      >
        <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold">{current.title}</p>
            <p className="text-xs text-muted-foreground">
              {notYet.length === 0
                ? "Wszyscy z grupy docelowej już umieją."
                : `${notYet.length} z ${current.audience} osób jeszcze nie umie.`}
            </p>
          </div>
          {current.active && notYet.length > 0 ? (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              loading={remindingId === current.id}
              onClick={() =>
                onRemind(
                  current.id,
                  notYet.map((p) => p.user_id),
                )
              }
            >
              <Bell className="h-3.5 w-3.5" aria-hidden="true" />
              Przypomnij {notYet.length}{" "}
              {notYet.length === 1 ? "osobie" : "osobom"}
            </Button>
          ) : null}
        </header>
        <ul className="grid gap-x-6 px-4 py-2 sm:grid-cols-2 lg:grid-cols-3">
          {current.people.map((p) => (
            <li
              key={p.user_id}
              className="flex min-w-0 items-start gap-2 border-b border-border/60 py-2 text-sm"
            >
              <span className="mt-0.5 shrink-0">
                <StateIcon state={p.state} />
              </span>
              <span className="min-w-0">
                <span className="block truncate font-medium">{p.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {STATE_LABEL[p.state]}
                  {p.reminded_at && !KNOWS.includes(p.state)
                    ? " · przypomniano"
                    : ""}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
