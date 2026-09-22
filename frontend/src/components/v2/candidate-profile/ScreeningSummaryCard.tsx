"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronUp, Gauge, ShieldAlert, Star, Target } from "lucide-react";
import api from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

/**
 * Wynik screeningów (motywacja, gotowość, ryzyko kontroferty, wrażenie,
 * red flags). Na zakładce Rekrutacje, bo screening dotyczy procesu —
 * podsumowanie AI zawiera te dane tylko po ręcznym odświeżeniu, więc
 * bez tej karty dane strukturalne byłyby niewidoczne.
 * Współdzieli zapytanie `ai-profile` z sekcją Umiejętności (cache).
 */
const MOTIVATION_LABEL_PL: Record<string, string> = {
  money: "Pieniądze",
  growth: "Rozwój",
  project: "Projekt",
  team: "Zespół",
  work_mode: "Tryb pracy",
  stability: "Stabilność",
  technology: "Technologia",
  location: "Lokalizacja",
};

const RISK_LABEL_PL: Record<string, string> = {
  low: "niskie",
  medium: "średnie",
  high: "wysokie",
};

const RISK_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  low: "success",
  medium: "warning",
  high: "danger",
};

interface AiProfile {
  screening_count: number;
  motivation_top?: string | null;
  readiness_avg?: number | null;
  overall_impression_avg?: number | null;
  counteroffer_risk_dominant?: string | null;
  red_flags_unique?: string[];
  motivation_trend?: Array<{ primary?: string | null }>;
  last_screening?: { created_at: string } | null;
}

function pluralScreenings(n: number): string {
  if (n === 1) return "screening";
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "screeningi";
  return "screeningów";
}

export function ScreeningSummaryCard({ candidateId }: { candidateId: number }) {
  const [expanded, setExpanded] = useState(false);
  const { data } = useQuery<AiProfile>({
    queryKey: candidateQueryKeys.aiProfile(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/ai-profile`, { signal }).then((r) => r.data),
    enabled: !!candidateId,
    staleTime: 60_000,
  });
  if (!data || !data.screening_count) return null;

  const redFlags = data.red_flags_unique ?? [];
  const trend = data.motivation_trend ?? [];
  const hasDetails = redFlags.length > 0 || trend.length > 1;

  return (
    <section
      aria-labelledby="candidate-screening-summary"
      className="space-y-2.5 rounded-xl border border-border bg-card p-4"
    >
      <div className="flex items-baseline gap-2">
        <h2 id="candidate-screening-summary" className="text-sm font-semibold text-foreground">
          Screeningi
        </h2>
        <span className="text-xs text-muted-foreground">
          {data.screening_count} {pluralScreenings(data.screening_count)}
          {data.last_screening?.created_at
            ? ` · ostatni ${formatRelativeTime(data.last_screening.created_at)}`
            : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {data.motivation_top && (
          <Badge variant="soft" size="sm">
            <Target className="h-3 w-3" aria-hidden />
            Motywacja: {MOTIVATION_LABEL_PL[data.motivation_top] ?? data.motivation_top}
          </Badge>
        )}
        {data.readiness_avg != null && (
          <Badge variant="soft" size="sm">
            <Gauge className="h-3 w-3" aria-hidden />
            Gotowość: {data.readiness_avg}/5
          </Badge>
        )}
        {data.counteroffer_risk_dominant && (
          <Badge variant={RISK_VARIANT[data.counteroffer_risk_dominant] ?? "neutral"} size="sm">
            <ShieldAlert className="h-3 w-3" aria-hidden />
            Ryzyko kontroferty:{" "}
            {RISK_LABEL_PL[data.counteroffer_risk_dominant] ?? data.counteroffer_risk_dominant}
          </Badge>
        )}
        {data.overall_impression_avg != null && (
          <Badge variant="soft" size="sm">
            <Star className="h-3 w-3" aria-hidden />
            Wrażenie: {data.overall_impression_avg}/5
          </Badge>
        )}
        {redFlags.length > 0 && (
          <Badge variant="danger" size="sm">
            <AlertTriangle className="h-3 w-3" aria-hidden />
            {redFlags.length} {redFlags.length === 1 ? "red flag" : "red flags"}
          </Badge>
        )}
      </div>
      {hasDetails && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="inline-flex min-h-8 items-center gap-1 text-xs text-muted-foreground hover:text-primary"
        >
          {expanded ? "Zwiń szczegóły" : "Pokaż szczegóły"}
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      )}
      {expanded && (
        <div className="space-y-2.5 border-t border-border pt-2.5">
          {redFlags.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Red flags</div>
              <div className="flex flex-wrap gap-1.5">
                {redFlags.map((rf, i) => (
                  <Badge key={i} variant="danger" size="sm">
                    {rf}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {trend.length > 1 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Trend motywacji</div>
              <div className="flex flex-wrap gap-1.5">
                {trend.map((m, i) => (
                  <Badge key={i} variant="outline" size="sm">
                    {MOTIVATION_LABEL_PL[m.primary ?? ""] ?? m.primary ?? "—"}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
