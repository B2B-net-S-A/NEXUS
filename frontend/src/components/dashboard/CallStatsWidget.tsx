"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, PhoneCall } from "lucide-react";

import { callsApi } from "@/lib/api";

interface StatBoxProps {
  label: string;
  value: string;
  hint?: string;
}

function StatBox({ label, value, hint }: StatBoxProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-bold text-foreground mt-0.5">{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}

/**
 * Compact 3-column "rozmowy w tym tygodniu" widget. Renders nothing when
 * CloudTalk is disabled (stats endpoint returns `cloudtalk_status: "disabled"`
 * and the team-week counter stays at 0).
 */
export default function CallStatsWidget() {
  const { data, isLoading } = useQuery({
    queryKey: ["call-stats"],
    queryFn: () => callsApi.getStats(),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Ładowanie statystyk rozmów...
      </div>
    );
  }

  if (!data) return null;

  // Stay invisible when CloudTalk is disabled AND there are no historical
  // calls anyway – keeps the dashboard tidy for accounts pre-activation.
  if (
    data.cloudtalk_status === "disabled" &&
    data.user.total_calls === 0 &&
    data.global.calls_this_week === 0
  ) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <PhoneCall className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold text-foreground">Rozmowy</h3>
        {data.cloudtalk_status === "disabled" && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
            CloudTalk off
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3">
        <StatBox
          label="Moje w tym tygodniu"
          value={String(data.user.calls_this_week)}
          hint={`Łącznie: ${data.user.total_calls}`}
        />
        <StatBox
          label="Średni czas (mój)"
          value={data.user.avg_duration_formatted}
        />
        <StatBox
          label="Zespół (tydzień)"
          value={String(data.global.calls_this_week)}
          hint={`śr. ${data.global.avg_duration_formatted}`}
        />
      </div>
    </div>
  );
}
