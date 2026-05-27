"use client";

/**
 * DynaReporter B.2.4 — Placements (lista + stats per user/client).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";

interface Placement {
  id: number;
  user_id: number;
  user_name?: string;
  client_id: number;
  placement_date: string;
  week_number?: number | null;
  notes?: string | null;
}
interface StatByUser {
  user_id: number;
  user_name: string;
  total_placements: number;
}
interface StatByClient {
  client_id: number;
  total_placements: number;
}

export default function PlacementsPage() {
  const { user, hydrated } = useAuthStore();

  const myQ = useQuery({
    queryKey: ["dr", "placements", "my"],
    queryFn: () => api.get<Placement[]>("/api/dynareporter/placements/my").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "placements"),
  });
  const byUserQ = useQuery({
    queryKey: ["dr", "placements", "byuser"],
    queryFn: () =>
      api
        .get<StatByUser[]>("/api/dynareporter/placements/stats/by-user", { params: { days: 90 } })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "placements"),
  });
  const byClientQ = useQuery({
    queryKey: ["dr", "placements", "byclient"],
    queryFn: () =>
      api
        .get<StatByClient[]>("/api/dynareporter/placements/stats/by-client", { params: { days: 90 } })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "placements"),
  });

  if (!hydrated) return <Loading text="Ładowanie…" />;
  if (!user) return <Loading text="Zaloguj się." />;
  if (!hasSection(user, "placements")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Brak sekcji <code>placements</code>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Placementy</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Szczegółowe placementy: kto, kiedy, u kogo. Statsy z ostatnich 90 dni.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">Moje placementy</h2>
          {myQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : (myQ.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">
              Brak placementów. Po `--apply` ETL zobaczysz historyczne.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground border-b border-border">
                    <th className="pb-2 font-medium">Data</th>
                    <th className="pb-2 font-medium">Tydzień</th>
                    <th className="pb-2 font-medium">Klient</th>
                    <th className="pb-2 font-medium">Notatki</th>
                  </tr>
                </thead>
                <tbody>
                  {(myQ.data ?? []).slice(0, 30).map((p) => (
                    <tr key={p.id} className="border-b border-border last:border-0">
                      <td className="py-2 tabular-nums">{p.placement_date}</td>
                      <td className="py-2 tabular-nums">{p.week_number ?? "–"}</td>
                      <td className="py-2 tabular-nums">#{p.client_id}</td>
                      <td className="py-2 text-muted-foreground truncate max-w-[200px]">
                        {p.notes ?? "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="font-semibold text-sm mb-3">Top 10 — User (90 dni)</h2>
            <RankingList rows={byUserQ.data ?? []} loading={byUserQ.isLoading} keyName="user" />
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="font-semibold text-sm mb-3">Top 10 — Klienci (90 dni)</h2>
            <RankingList rows={byClientQ.data ?? []} loading={byClientQ.isLoading} keyName="client" />
          </div>
        </div>
      </div>
    </div>
  );
}

function Loading({ text }: { text: string }) {
  return <div className="p-8 text-sm text-muted-foreground">{text}</div>;
}

function RankingList({
  rows,
  loading,
  keyName,
}: {
  rows: Array<{ user_name?: string; client_name?: string; client_id?: number; user_id?: number; total_placements: number }>;
  loading: boolean;
  keyName: "user" | "client";
}) {
  if (loading) return <p className="text-xs text-muted-foreground">Ładowanie…</p>;
  if (rows.length === 0) return <p className="text-xs text-muted-foreground py-2">Brak danych.</p>;
  return (
    <ol className="space-y-1">
      {rows.slice(0, 10).map((r, i) => (
        <li key={i} className="flex items-center text-xs">
          <span className="w-5 text-muted-foreground tabular-nums">{i + 1}.</span>
          <span className="flex-1 truncate">
            {keyName === "user"
              ? r.user_name || `User #${r.user_id}`
              : r.client_name || `Klient #${r.client_id}`}
          </span>
          <span className="font-semibold tabular-nums">{r.total_placements}</span>
        </li>
      ))}
    </ol>
  );
}
