"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, Clock, Loader2 } from "lucide-react";
import { phase3Api } from "@/lib/api";

interface SlaAlert {
  candidate_stage_id: number;
  candidate_id: number;
  job_id: number;
  stage_name: string;
  days_in_stage: number;
  sla_max_days: number;
  overdue_by_days: number;
}

export function SLAAlertsSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["insights-sla"],
    queryFn: () =>
      phase3Api.slaAlerts().then(
        (r) =>
          r.data as { count: number; alerts: SlaAlert[]; configured?: boolean },
      ),
  });

  const alerts = data?.alerts ?? [];
  // `configured === false` = żaden etap nie ma ustawionego `sla_max_days`, więc
  // ten panel z definicji nie ma czego pilnować. Do 2026-08-13 renderował z tego
  // „wszystko w normie 🎉" — czyli brak konfiguracji wyglądał jak zdrowie.
  const notConfigured = data?.configured === false;

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <AlertTriangle
          className={`w-5 h-5 ${alerts.length > 0 ? "text-destructive" : "text-muted-foreground"}`}
        />
        Alerty SLA ({alerts.length})
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          Kandydaci przekraczający czas maksymalny w etapie
        </span>
      </h2>

      {isLoading ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Alerty SLA: dane chwilowo niedostępne (to NIE jest zero).
        </p>
      ) : notConfigured ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          SLA nie jest ustawione na żadnym etapie — ten panel niczego nie
          pilnuje. Ustaw maksymalny czas w etapie szablonu, żeby zaczął działać.
        </p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak alertów — wszystko w normie 🎉
        </p>
      ) : (
        <ul className="space-y-1 text-sm">
          {alerts.slice(0, 10).map((a) => (
            <li
              key={a.candidate_stage_id}
              className="flex items-center gap-2 rounded bg-destructive/10 border border-destructive/20 px-3 py-2"
            >
              <Clock className="w-3.5 h-3.5 text-destructive shrink-0" />
              <Link
                href={`/candidates/${a.candidate_id}`}
                className="font-medium hover:underline text-foreground"
              >
                kandydat #{a.candidate_id}
              </Link>
              <span className="text-muted-foreground">w etapie</span>
              <span className="font-medium text-foreground">{a.stage_name}</span>
              <span className="flex-1 text-right text-destructive">
                {a.days_in_stage}d (limit {a.sla_max_days}d, spóźnienie {a.overdue_by_days}d)
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
