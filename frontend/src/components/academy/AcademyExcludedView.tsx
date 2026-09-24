"use client";

/**
 * Akademia — wykluczeni na stałe (decyzja Artura 24.09.2026: „nie” jest
 * pamiętane na zawsze). Osoba, która zgłosi się znowu, nie wraca do
 * telefonów — dostaje tu plakietkę „aplikował ponownie”. „Przywróć” cofa
 * decyzję człowieka. Osobno ci, którzy zrezygnowali sami (ci wracają przy
 * kolejnym zgłoszeniu automatycznie).
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { STATUS_LABELS, shortDate } from "@/lib/academy-flow";
import type { AcademyApplication, AcademyStatus } from "@/lib/api/academy";

import type { ActFn } from "./AcademyShared";

export function AcademyExcludedView({
  apps,
  onAct,
  busyIds,
}: {
  apps: readonly AcademyApplication[];
  onAct: ActFn;
  busyIds: ReadonlySet<number>;
}) {
  const [query, setQuery] = React.useState("");
  const needle = query.trim().toLocaleLowerCase("pl");
  const match = (a: AcademyApplication) =>
    !needle ||
    a.full_name.toLocaleLowerCase("pl").includes(needle) ||
    (a.closed_reason ?? "").toLocaleLowerCase("pl").includes(needle);
  const rejected = apps
    .filter((a) => a.status === "rejected" && match(a))
    .sort((a, b) => (b.reapplied_at ?? b.closed_at ?? "").localeCompare(a.reapplied_at ?? a.closed_at ?? ""));
  const withdrew = apps.filter((a) => a.status === "withdrew" && match(a));
  const searchId = React.useId();

  return (
    <div className="space-y-5">
      <label htmlFor={searchId} className="flex max-w-sm flex-col gap-1 text-xs font-medium text-muted-foreground">
        Szukaj po nazwisku albo powodzie
        <input
          id={searchId}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
        />
      </label>
      <Section
        title={`Wykluczeni na stałe (${rejected.length})`}
        hint="Kolejne zgłoszenia tych osób nie trafiają do telefonów, a Luna nie czyta ich CV."
        apps={rejected}
        onAct={onAct}
        busyIds={busyIds}
      />
      <Section
        title={`Zrezygnowali sami (${withdrew.length})`}
        hint="Przy kolejnym zgłoszeniu wracają na początek automatycznie."
        apps={withdrew}
        onAct={onAct}
        busyIds={busyIds}
      />
    </div>
  );
}

function Section({
  title,
  hint,
  apps,
  onAct,
  busyIds,
}: {
  title: string;
  hint: string;
  apps: readonly AcademyApplication[];
  onAct: ActFn;
  busyIds: ReadonlySet<number>;
}) {
  return (
    <section className="rounded-xl border border-border bg-card">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </header>
      {apps.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">Nikogo.</p>
      ) : (
        <ul className="divide-y divide-border">
          {apps.map((app) => (
            <li key={app.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <div className="w-52 min-w-0">
                <a className="font-medium underline-offset-4 hover:underline" href={`/candidates/${app.candidate_id}`}>
                  {app.full_name}
                </a>
                <p className="text-xs text-muted-foreground">
                  {app.closed_stage
                    ? `na etapie „${STATUS_LABELS[app.closed_stage as AcademyStatus] ?? app.closed_stage}”`
                    : ""}
                  {app.closed_at ? ` · ${shortDate(app.closed_at)}` : ""}
                </p>
              </div>
              <p className="min-w-0 flex-1">{app.closed_reason ?? "—"}</p>
              {app.reapplied_at ? (
                <Badge variant="warning">aplikował ponownie {shortDate(app.reapplied_at)}</Badge>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                disabled={busyIds.has(app.id)}
                onClick={() => void onAct(app, { action: "restore" })}
              >
                Przywróć
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
