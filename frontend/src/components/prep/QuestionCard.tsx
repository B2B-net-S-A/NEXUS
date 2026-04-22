"use client";

import { useState } from "react";
import { Card, Badge, Button } from "@/components/ui";
import {
  interviewQuestionsApi,
  type SuggestedQuestion,
  type SuggestionTier,
  type QuestionRating,
} from "@/lib/api";

const TIER_LABELS: Record<SuggestionTier, { label: string; variant: "soft" | "info" | "warning" | "outline" | "success" }> = {
  pinned: { label: "Przypięte", variant: "success" },
  legacy_champion: { label: "Champion profile", variant: "soft" },
  tier_1_same_cc: { label: "Z podobnego projektu (ta sama CC)", variant: "info" },
  tier_2_secondary_cc: { label: "Z podobnego projektu (secondary CC)", variant: "info" },
  tier_3_client_knowledge: { label: "Baza wiedzy o kliencie", variant: "soft" },
  tier_4_auto_generated: { label: "Auto-wygenerowane", variant: "outline" },
};

const TYPE_LABELS: Record<string, string> = {
  technical: "Techniczne",
  behavioral: "Behawioralne",
  motivation: "Motywacja",
  experience: "Doświadczenie",
};

interface QuestionCardProps {
  question: SuggestedQuestion;
  jobId: number;
  candidateId?: number;
  onPin?: (questionId: number) => void;
  onRated?: () => void;
}

export function QuestionCard({
  question,
  jobId,
  candidateId,
  onPin,
  onRated,
}: QuestionCardProps) {
  const [rated, setRated] = useState<QuestionRating | null>(null);
  const [pinning, setPinning] = useState(false);
  const [pinned, setPinned] = useState(question.source_tier === "pinned");
  const [error, setError] = useState<string | null>(null);

  const tierMeta = TIER_LABELS[question.source_tier];
  const cosine =
    question.cosine_score !== null
      ? ` · ${Math.round(question.cosine_score * 100)}% podobny`
      : "";

  const handlePin = async () => {
    if (!question.question_id || pinned) return;
    setPinning(true);
    setError(null);
    try {
      await interviewQuestionsApi.pinToJob(jobId, {
        question_id: question.question_id,
      });
      setPinned(true);
      onPin?.(question.question_id);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Nie udało się przypiąć";
      setError(message);
    } finally {
      setPinning(false);
    }
  };

  const handleRate = async (rating: QuestionRating) => {
    if (!question.question_id || rated) return;
    try {
      await interviewQuestionsApi.rate(question.question_id, {
        rating,
        job_id: jobId,
        candidate_id: candidateId,
      });
      setRated(rating);
      onRated?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Nie udało się ocenić";
      setError(message);
    }
  };

  return (
    <Card variant="default" size="md" className="print:shadow-none print:border-gray-300">
      <div className="flex items-start justify-between gap-3 mb-2 print:mb-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={tierMeta.variant} size="sm">
            {tierMeta.label}
            {cosine}
          </Badge>
          {question.question_type && (
            <Badge variant="outline" size="sm">
              {TYPE_LABELS[question.question_type] ?? question.question_type}
            </Badge>
          )}
          {question.seniority && (
            <Badge variant="neutral" size="sm">
              {question.seniority}
            </Badge>
          )}
          {question.deal_breaker && (
            <Badge variant="danger" size="sm">
              deal-breaker
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0 print:hidden">
          <button
            type="button"
            aria-label="Oceń pozytywnie"
            onClick={() => handleRate("up")}
            disabled={rated !== null || !question.question_id}
            className={`px-2 py-1 rounded text-sm transition-colors ${
              rated === "up"
                ? "bg-green-100 text-green-700"
                : "hover:bg-[hsl(var(--border-subtle))] text-[hsl(var(--text-muted))]"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👍
          </button>
          <button
            type="button"
            aria-label="Oceń negatywnie"
            onClick={() => handleRate("down")}
            disabled={rated !== null || !question.question_id}
            className={`px-2 py-1 rounded text-sm transition-colors ${
              rated === "down"
                ? "bg-red-100 text-red-700"
                : "hover:bg-[hsl(var(--border-subtle))] text-[hsl(var(--text-muted))]"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            👎
          </button>
        </div>
      </div>

      <p className="text-[hsl(var(--text-body))] leading-relaxed">
        {question.text}
      </p>

      {question.ideal_answer && (
        <div className="mt-3 p-3 bg-[hsl(var(--accent-soft))] rounded-v2-s print:border print:border-gray-200 print:bg-transparent">
          <p className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))] mb-1">
            Odpowiedź idealna
          </p>
          <p className="text-sm text-[hsl(var(--text-body))] whitespace-pre-wrap">
            {question.ideal_answer}
          </p>
        </div>
      )}

      {question.skill_tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {question.skill_tags.map((tag) => (
            <span
              key={tag}
              className="text-xs text-[hsl(var(--text-muted))] px-1.5 py-0.5 bg-[hsl(var(--border-subtle))] rounded-sm"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      {question.source_tier !== "pinned" && question.question_id && (
        <div className="mt-3 flex items-center gap-2 print:hidden">
          <Button
            variant="outline"
            size="sm"
            onClick={handlePin}
            disabled={pinning || pinned}
          >
            {pinned ? "✓ Przypięte" : pinning ? "Przypinam..." : "Przypnij do projektu"}
          </Button>
          {question.source_job_id && (
            <span className="text-xs text-[hsl(var(--text-muted))]">
              z projektu #{question.source_job_id}
            </span>
          )}
        </div>
      )}

      {error && (
        <p className="mt-2 text-sm text-red-600 print:hidden">{error}</p>
      )}
    </Card>
  );
}
