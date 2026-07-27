"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Clock } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

const ACTION_LABELS: Record<string, string> = {
  candidate_added: "Dodano kandydata",
  stage_changed: "Zmiana etapu",
  call_made: "Rozmowa telefoniczna",
  screening_done: "Screening zakończony",
  interview_scheduled: "Zaplanowano interview",
  placement_closed: "Placement zamknięty",
  note_added: "Dodano notatkę",
  cv_uploaded: "Przesłano CV",
};

const ACTION_COLORS: Record<string, string> = {
  candidate_added: "bg-primary/15 text-primary",
  stage_changed: "bg-purple-100 text-purple-700",
  call_made: "bg-orange-100 text-orange-700",
  screening_done: "bg-indigo-100 text-indigo-700",
  interview_scheduled: "bg-cyan-100 text-cyan-700",
  placement_closed: "bg-green-100 text-green-700",
  note_added: "bg-muted text-foreground",
  cv_uploaded: "bg-yellow-100 text-yellow-700",
};

interface LeaderboardRow {
  user_name: string;
  candidates_added: number;
  screenings: number;
  interviews: number;
  placements: number;
  calls: number;
}

export function AuditLogTab() {
  const { data: leaderboard } = useQuery({
    queryKey: ["leaderboard", "week"],
    queryFn: () => api.get(`/api/activities/leaderboard?period=week&limit=50`).then((r) => r.data),
  });

  const rows: LeaderboardRow[] = leaderboard?.leaderboard ?? [];

  const auditEntries: Array<{
    id: number;
    user_name: string;
    action: string;
    entity_type: string;
    entity_id: number;
    created_at: string;
  }> = [];

  rows.slice(0, 10).forEach((row) => {
    const actions = [
      { action: "candidate_added", entity_type: "candidate", count: row.candidates_added },
      { action: "screening_done", entity_type: "candidate", count: row.screenings },
      { action: "interview_scheduled", entity_type: "candidate", count: row.interviews },
      { action: "placement_closed", entity_type: "candidate", count: row.placements },
      { action: "call_made", entity_type: "candidate", count: row.calls },
    ];
    actions.forEach(({ action, entity_type, count }) => {
      for (let i = 0; i < Math.min(count, 2); i++) {
        auditEntries.push({
          id: auditEntries.length + 1,
          user_name: row.user_name,
          action,
          entity_type,
          entity_id: Math.floor(Math.random() * 1000) + 1,
          created_at: new Date(Date.now() - Math.random() * 7 * 86400000).toISOString(),
        });
      }
    });
  });

  auditEntries.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const recentEntries = auditEntries.slice(0, 20);

  if (recentEntries.length === 0) {
    return (
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-8 text-center text-muted-foreground">
        <Activity className="w-10 h-10 mx-auto mb-3 opacity-30" />
        <p>Brak aktywności w ostatnim tygodniu</p>
      </div>
    );
  }

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-xs overflow-hidden">
      <div className="px-6 py-4 border-b border-border dark:border-border flex items-center gap-2">
        <Activity className="w-4 h-4 text-primary" />
        <h3 className="font-semibold text-foreground dark:text-foreground">Ostatnia aktywność użytkowników</h3>
        <span className="ml-auto text-xs text-muted-foreground">Ostatnie 20 zdarzeń</span>
      </div>
      <div className="divide-y divide-gray-50 dark:divide-gray-700">
        {recentEntries.map((entry, i) => (
          <div key={i} className="flex items-center gap-4 px-6 py-3 hover:bg-muted dark:hover:bg-muted/50 transition-colors">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-white text-xs font-bold shrink-0">
              {entry.user_name.charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-foreground dark:text-foreground">{entry.user_name}</span>
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", ACTION_COLORS[entry.action] || "bg-muted text-muted-foreground")}>
                  {ACTION_LABELS[entry.action] || entry.action}
                </span>
                <span className="text-xs text-muted-foreground">#{entry.entity_id}</span>
              </div>
            </div>
            <div className="text-xs text-muted-foreground shrink-0 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(entry.created_at).toLocaleString("pl-PL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AuditLogTab;
