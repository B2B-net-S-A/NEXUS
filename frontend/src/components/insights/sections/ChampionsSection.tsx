"use client";

import { useQuery } from "@tanstack/react-query";
import { Award } from "lucide-react";
import { ChampionsPodium } from "@/components/v2/gamification/ChampionsPodium";
import { api } from "@/lib/api";

interface ChampionsPayload {
  period: string;
  top3: unknown[];
  target_pct?: number;
}

export function ChampionsSection() {
  const { data: dl } = useQuery<ChampionsPayload>({
    queryKey: ["insights-champions", "dl"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_dl")
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const { data: recruiter } = useQuery<ChampionsPayload>({
    queryKey: ["insights-champions", "recruiter"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_recruiter")
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Award className="w-5 h-5 text-amber-500" />
        Liga Mistrzów — kwartalni championi
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChampionsPodium
          title="Liga Mistrzów DL"
          subtitle="Kwartalny podium Delivery Leadów"
          period={dl?.period ?? ""}
          top3={(dl?.top3 ?? []) as never[]}
          metricLabel="placementów"
          targetPct={dl?.target_pct ?? 30}
        />
        <ChampionsPodium
          title="Liga Mistrzów Rekrutacja"
          subtitle="Kwartalny ranking punktowy (150/15/5)"
          period={recruiter?.period ?? ""}
          top3={(recruiter?.top3 ?? []) as never[]}
          // Ranking rekruterów liczy PUNKTY (placement=150, interview=15,
          // rekomendacja=5), nie liczbę placementów — label „placementów"
          // kłamał przy metric_value będącym sumą punktów.
          metricLabel="pkt"
        />
      </div>
    </section>
  );
}
