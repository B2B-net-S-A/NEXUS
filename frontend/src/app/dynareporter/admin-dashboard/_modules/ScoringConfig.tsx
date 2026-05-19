"use client";

/**
 * Scoring Config — admin konfiguracja Liga Mistrzów punktacji.
 * Port `ScoringConfig.tsx` z artur-t-96/InfraReporter.
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Settings, CheckCircle, AlertCircle, RefreshCw } from "lucide-react";
import { dynareporterAdminConfigApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function ScoringConfig() {
  const queryClient = useQueryClient();
  const [placement, setPlacement] = useState(150);
  const [interview, setInterview] = useState(15);
  const [recommendation, setRecommendation] = useState(5);
  const [verification, setVerification] = useState(0);
  const [saveStatus, setSaveStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const scoringQuery = useQuery({
    queryKey: ["dr-admin-scoring"],
    queryFn: () => dynareporterAdminConfigApi.getScoring(),
    staleTime: 60_000,
  });

  // Sync state z server response
  useEffect(() => {
    if (scoringQuery.data) {
      setPlacement(scoringQuery.data.placement);
      setInterview(scoringQuery.data.interview);
      setRecommendation(scoringQuery.data.recommendation);
      setVerification(scoringQuery.data.verification);
    }
  }, [scoringQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      dynareporterAdminConfigApi.updateScoring({
        placement,
        interview,
        recommendation,
        verification,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-scoring"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-dashboard"] });
      setSaveStatus({ type: "success", msg: "Punktacja zapisana — Liga Mistrzów zaktualizowana" });
      setTimeout(() => setSaveStatus(null), 4000);
    },
    onError: (e: unknown) => {
      setSaveStatus({ type: "error", msg: `Błąd: ${String(e)}` });
    },
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Settings className="w-5 h-5 text-gray-600" />
          Liga Mistrzów — System punktowy
        </h3>
        <p className="text-sm text-muted-foreground mb-4">
          Każda akcja rekrutera daje określoną liczbę punktów. Zmiany działają natychmiast
          po zapisie (Rekrutacja dashboard się odświeży automatycznie).
        </p>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <PointsInput
            label="Placement"
            value={placement}
            onChange={setPlacement}
            color="emerald"
            hint="Najwyżej punktowane"
          />
          <PointsInput
            label="Interview"
            value={interview}
            onChange={setInterview}
            color="amber"
            hint="Interview z klientem"
          />
          <PointsInput
            label="Recommendation"
            value={recommendation}
            onChange={setRecommendation}
            color="purple"
            hint="Rekomendacja CV"
          />
          <PointsInput
            label="Verification"
            value={verification}
            onChange={setVerification}
            color="blue"
            hint="Najczęściej 0 (nie liczy się)"
          />
        </div>

        <div className="mt-4 flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            <Save className="w-4 h-4" aria-hidden="true" />
            <span className="ml-1">Zapisz punktację</span>
          </Button>
          <Button variant="outline" size="sm" onClick={() => scoringQuery.refetch()}>
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
          </Button>
          {saveStatus && (
            <div className={`text-sm flex items-center gap-1 ${saveStatus.type === "success" ? "text-emerald-600" : "text-rose-600"}`}>
              {saveStatus.type === "success" ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              {saveStatus.msg}
            </div>
          )}
        </div>

        <div className="mt-4 p-3 bg-muted/40 rounded text-sm">
          <p className="font-semibold mb-1">Aktualna formuła:</p>
          <code className="text-xs">
            punkty = placements × {placement} + interviews × {interview} + recommendations × {recommendation}
            {verification > 0 && ` + verifications × ${verification}`}
          </code>
        </div>
      </CardContent>
    </Card>
  );
}

function PointsInput({
  label,
  value,
  onChange,
  color,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  color: "emerald" | "amber" | "purple" | "blue";
  hint: string;
}) {
  const colorClasses = {
    emerald: "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30",
    amber: "border-amber-500 bg-amber-50 dark:bg-amber-950/30",
    purple: "border-purple-500 bg-purple-50 dark:bg-purple-950/30",
    blue: "border-blue-500 bg-blue-50 dark:bg-blue-950/30",
  };
  return (
    <div className={`rounded-lg border-t-4 ${colorClasses[color]} p-3`}>
      <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
        {label}
      </label>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full px-2 py-1.5 text-lg font-bold tabular-nums bg-background border border-input rounded-md"
      />
      <p className="text-[10px] text-muted-foreground mt-1">{hint}</p>
    </div>
  );
}
