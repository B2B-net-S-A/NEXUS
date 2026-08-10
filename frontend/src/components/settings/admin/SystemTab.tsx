"use client";

import { useQuery } from "@tanstack/react-query";
import { Database, Clock } from "lucide-react";
import { adminApi } from "@/lib/api";
import { cn } from "@/lib/utils";

export function SystemTab() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["admin-system"],
    queryFn: () => adminApi.systemStats().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 animate-pulse">
            <div className="h-4 bg-muted rounded w-1/2 mb-3" />
            <div className="h-8 bg-muted rounded w-1/3" />
          </div>
        ))}
      </div>
    );
  }

  if (!stats) return null;

  const statCards = [
    { label: "Kandydaci", value: stats.counts.candidates, icon: "👥" },
    { label: "Rekrutacje", value: stats.counts.jobs, icon: "💼" },
    { label: "Klienci", value: stats.counts.clients, icon: "🏢" },
    { label: "Kontrakty", value: stats.counts.contracts, icon: "📄" },
    { label: "Użytkownicy", value: stats.counts.users, icon: "🔑" },
  ];

  // R0 (plan analytics 2026-07-16): koniec z fałszywym „Redis OK" i zawsze
  // zieloną kropką — pokazujemy tylko wartości realnie zwrócone przez API,
  // a wskaźnik świeci na zielono wyłącznie gdy metryka istnieje.
  const healthMetrics = [
    { label: "Rozmiar bazy danych", value: stats.database?.size || null, icon: Database, color: "bg-primary/10 dark:bg-primary/30 text-primary" },
    { label: "Uptime serwera", value: stats.uptime || null, icon: Clock, color: "bg-green-50 dark:bg-green-900/30 text-green-600" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {healthMetrics.map((m) => (
          <div key={m.label} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-4 flex items-center gap-3">
            <div className={cn("p-2 rounded-lg", m.color)}>
              <m.icon className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted-foreground dark:text-muted-foreground">{m.label}</div>
              <div className="text-sm font-semibold text-foreground dark:text-foreground">{m.value ?? "—"}</div>
            </div>
            <div
              className={cn(
                "w-2 h-2 rounded-full",
                m.value ? "bg-green-500" : "bg-[hsl(var(--border))]"
              )}
              title={m.value ? "Dostępne" : "Brak danych"}
            />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {statCards.map(({ label, value, icon }) => (
          <div key={label} className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5">
            <div className="flex items-center gap-2 text-sm text-muted-foreground dark:text-muted-foreground mb-1">
              <span>{icon}</span>
              <span>{label}</span>
            </div>
            <p className="text-3xl font-bold text-foreground dark:text-foreground">{value?.toLocaleString() ?? "—"}</p>
          </div>
        ))}
      </div>

      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 space-y-3">
        <h3 className="font-semibold text-foreground dark:text-foreground">Szczegóły bazy danych</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Nazwa</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.database.name}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Rozmiar</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.database.size}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Czas działania serwera</p>
            <p className="font-medium text-foreground dark:text-foreground">{stats.uptime}</p>
          </div>
          <div>
            <p className="text-muted-foreground dark:text-muted-foreground">Czas serwera (UTC)</p>
            <p className="font-medium text-foreground dark:text-foreground">{new Date(stats.server_time).toLocaleString("pl-PL")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default SystemTab;
