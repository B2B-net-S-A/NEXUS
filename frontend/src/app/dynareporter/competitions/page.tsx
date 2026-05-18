"use client";

/**
 * DynaReporter B.2.6 — Liga Mistrzów.
 *
 * Aktualne podium (top 3) + historia podiów + powiadomienia kompetycyjne.
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface Winner {
  id: number;
  competition_type: string;
  period: string;
  user_id: number;
  user_name?: string;
  rank: number;
  points: number;
  metric_value: number;
  prize?: string;
}
interface Notification {
  id: number;
  notification_type: string;
  competition_type: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export default function CompetitionsPage() {
  const { user, hydrated } = useAuthStore();

  const podiumQ = useQuery({
    queryKey: ["dr", "podium"],
    queryFn: () =>
      api
        .get<Winner[]>("/api/dynareporter/competitions/podium", {
          params: { competition_type: "quarterly" },
        })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "competitions"),
  });
  const historyQ = useQuery({
    queryKey: ["dr", "history"],
    queryFn: () =>
      api.get<Winner[]>("/api/dynareporter/competitions/winners").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "competitions"),
  });
  const notifQ = useQuery({
    queryKey: ["dr", "competitions", "notif"],
    queryFn: () =>
      api.get<Notification[]>("/api/dynareporter/competitions/my-notifications").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "competitions"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "competitions")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>competitions</code>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">🏆 Liga Mistrzów</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Aktualne podium kwartalne + historia + powiadomienia kompetycyjne.
        </p>
      </header>

      {/* Podium */}
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="font-semibold mb-4">
          Podium {podiumQ.data?.[0]?.period ?? "(brak ogłoszonego)"}
        </h2>
        {podiumQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (podiumQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Brak ogłoszonych podiów. Po `--apply` ETL historia będzie widoczna.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {[1, 2, 3].map((rank) => {
              const w = (podiumQ.data ?? []).find((p) => p.rank === rank);
              return (
                <PodiumCard
                  key={rank}
                  rank={rank}
                  winner={w}
                  isCurrentUser={w?.user_id === user.id}
                />
              );
            })}
          </div>
        )}
      </div>

      {/* Notifications */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Powiadomienia ({notifQ.data?.length ?? 0})</h2>
        {notifQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (notifQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak powiadomień.</p>
        ) : (
          <ul className="space-y-1.5">
            {(notifQ.data ?? []).slice(0, 10).map((n) => (
              <li
                key={n.id}
                className={cn(
                  "rounded border border-border p-2.5 text-xs",
                  !n.is_read && "bg-primary/5 border-primary/30"
                )}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <strong>{n.title}</strong>
                  <span className="text-[10px] text-muted-foreground">
                    {new Date(n.created_at).toLocaleDateString("pl-PL")}
                  </span>
                </div>
                <p className="text-muted-foreground">{n.message}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* History */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Historia podiów</h2>
        {historyQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (historyQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak historii.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Period</th>
                  <th className="pb-2 font-medium">Typ</th>
                  <th className="pb-2 font-medium">Rank</th>
                  <th className="pb-2 font-medium">Zwycięzca</th>
                  <th className="pb-2 font-medium text-right">Pkt</th>
                  <th className="pb-2 font-medium text-right">Metric</th>
                  <th className="pb-2 font-medium">Nagroda</th>
                </tr>
              </thead>
              <tbody>
                {(historyQ.data ?? []).slice(0, 30).map((w) => (
                  <tr key={w.id} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">{w.period}</td>
                    <td className="py-2 text-muted-foreground">{w.competition_type}</td>
                    <td className="py-2 tabular-nums">{w.rank}</td>
                    <td className="py-2">{w.user_name || `User #${w.user_id}`}</td>
                    <td className="py-2 text-right tabular-nums">{w.points}</td>
                    <td className="py-2 text-right tabular-nums">{w.metric_value}</td>
                    <td className="py-2 text-muted-foreground">{w.prize ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function PodiumCard({
  rank,
  winner,
  isCurrentUser,
}: {
  rank: number;
  winner?: Winner;
  isCurrentUser: boolean;
}) {
  const medalEmoji = rank === 1 ? "🥇" : rank === 2 ? "🥈" : "🥉";
  const medalBg =
    rank === 1
      ? "bg-yellow-400/10 border-yellow-400"
      : rank === 2
      ? "bg-zinc-300/10 border-zinc-400"
      : "bg-orange-400/10 border-orange-400";
  return (
    <div
      className={cn(
        "rounded-lg border-2 p-4 text-center",
        medalBg,
        isCurrentUser && "ring-2 ring-primary"
      )}
    >
      <div className="text-3xl mb-1">{medalEmoji}</div>
      <p className="text-xs font-medium uppercase text-muted-foreground">
        Miejsce {rank}
      </p>
      {winner ? (
        <>
          <p className="mt-2 font-semibold text-sm truncate">
            {winner.user_name || `User #${winner.user_id}`}
          </p>
          <p className="text-2xl font-bold tabular-nums mt-1">{winner.points}</p>
          <p className="text-[10px] text-muted-foreground">punktów</p>
          {winner.prize && (
            <p className="mt-2 text-xs font-medium text-primary">{winner.prize}</p>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground py-4">–</p>
      )}
    </div>
  );
}
