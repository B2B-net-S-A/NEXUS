"use client";

import * as React from "react";
import { useEffect, useState } from "react";
import { Briefcase, CheckCircle2, Sparkles } from "lucide-react";
import { recommendationsApi, type JobMatch } from "@/lib/api";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function scoreVariant(
  score: number
): "success" | "soft" | "warning" | "neutral" {
  if (score >= 75) return "success";
  if (score >= 60) return "soft";
  if (score >= 40) return "warning";
  return "neutral";
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
  onAssigned?: (jobId: number) => void;
}

export function QuickAssignV2({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  onAssigned,
}: Props) {
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await recommendationsApi.forCandidate(candidateId, {
          top_k: 10,
          include_breakdown: true,
        });
        if (!cancelled) setMatches(res.data.matches);
      } catch (e: unknown) {
        if (cancelled) return;
        const msg =
          e && typeof e === "object" && "response" in e
            ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
            : "Błąd";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [candidateId, open]);

  const handleAssign = async (jobId: number) => {
    setAssigning(jobId);
    try {
      await recommendationsApi.assignToJob(candidateId, jobId);
      setAssignedIds((prev) => new Set(prev).add(jobId));
      onAssigned?.(jobId);
    } finally {
      setAssigning(null);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="md">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[hsl(var(--accent))]" />
            <SheetTitle>AI rekomendacje ofert</SheetTitle>
          </div>
          <SheetDescription>
            Dopasowania dla <strong>{candidateName}</strong> · top 10.
          </SheetDescription>
        </SheetHeader>

        <SheetBody>
          {loading ? (
            <div className="text-sm text-[hsl(var(--text-muted))] py-8 text-center">
              Analizuję dopasowania…
            </div>
          ) : error ? (
            <div className="text-sm text-[hsl(var(--accent))] bg-[hsl(var(--accent-soft))] px-3 py-2 rounded-v2-s">
              {error}
            </div>
          ) : matches.length === 0 ? (
            <div className="text-sm text-[hsl(var(--text-muted))] py-8 text-center">
              <Briefcase className="h-10 w-10 mx-auto mb-2 opacity-40" />
              Brak pasujących ofert. Upewnij się, że CV kandydata zostało wgrane.
            </div>
          ) : (
            <div className="space-y-2">
              {matches.map((m) => {
                const jobId = m.job.id;
                const assigned = assignedIds.has(jobId);
                const isAssigning = assigning === jobId;
                const score = m.total_score;
                return (
                  <div
                    key={jobId}
                    className="flex items-start gap-3 p-3 rounded-v2-m border border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]/40 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm text-[hsl(var(--text-title))] truncate">
                          {m.job.title ?? `Oferta #${jobId}`}
                        </span>
                        <Badge variant={scoreVariant(score)} size="sm">
                          {Math.round(score)}%
                        </Badge>
                      </div>
                      {m.job.location && (
                        <div className="text-xs text-[hsl(var(--text-muted))] mt-0.5">
                          {m.job.location}
                          {m.job.seniority ? ` · ${m.job.seniority}` : ""}
                        </div>
                      )}
                    </div>
                    {assigned ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#1d5e31] shrink-0">
                        <CheckCircle2 className="h-3.5 w-3.5" /> Przypisano
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleAssign(jobId)}
                        loading={isAssigning}
                      >
                        Przypisz
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </SheetBody>

        <SheetFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
