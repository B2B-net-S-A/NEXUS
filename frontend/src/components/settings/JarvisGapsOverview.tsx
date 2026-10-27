"use client";

/** „Czego Jarvis nie umie” (Ustawienia → AI): karty braku z 30 dni.
 *  Ranking rodzajów na górze, pod nim prośby — z niej wybieramy kolejne narzędzia. */

import { useQuery } from "@tanstack/react-query";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { fetchJarvisGaps } from "@/lib/jarvis/api";
import type { GapKind, JarvisGapReportRow } from "@/lib/jarvis/types";

const KIND_LABEL: Record<GapKind, string> = {
  no_access: "Rola tego nie widzi",
  not_supported: "Jarvis jeszcze nie umie",
  no_data: "NEXUS tego nie przechowuje",
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function Summary({ rows }: { rows: JarvisGapReportRow[] }) {
  const reported = rows.filter((r) => r.reported).length;
  const byKind = (Object.keys(KIND_LABEL) as GapKind[]).map((kind) => [
    KIND_LABEL[kind],
    rows.filter((r) => r.kind === kind).length,
  ]);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[["Zgłoszone przez ludzi", reported], ...byKind].map(([label, value]) => (
        <div key={label as string} className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-lg font-semibold tabular-nums text-foreground">{value}</div>
        </div>
      ))}
    </div>
  );
}

export function JarvisGapsOverview() {
  const query = useQuery({ queryKey: ["jarvis", "gaps", 30], queryFn: () => fetchJarvisGaps(30) });

  if (query.isLoading) return <p className="text-sm text-muted-foreground">Wczytuję…</p>;
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać listy braków Jarvisa."
        onRetry={() => query.refetch()}
      />
    );
  }
  const rows = query.data ?? [];

  return (
    <div className="space-y-4" data-testid="jarvis-gaps-overview">
      <p className="text-sm text-muted-foreground">
        Karty „Tego nie zrobię” z ostatnich 30 dni (tyle żyją rozmowy). Każda to coś, czego ktoś chciał od
        Jarvisa. „Zgłoszone” znaczy, że osoba kliknęła „Zgłoś, że tego potrzebuję”.
      </p>
      <Summary rows={rows} />
      {query.isSuccess && rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">W tym okresie Jarvis nie pokazał żadnej karty braku.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-foreground">{row.need}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{formatDateTime(row.created_at)}</span>
              </div>
              <span className="text-xs text-muted-foreground">
                {KIND_LABEL[row.kind] ?? row.kind} · rola: {row.role}
                {row.reported ? " · zgłoszone" : ""}
              </span>
              <span className="text-xs text-muted-foreground">{row.why}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
