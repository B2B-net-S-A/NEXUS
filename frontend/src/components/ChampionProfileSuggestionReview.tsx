"use client";

/**
 * Modal reviewing an AI-generated Champion Profile suggestion.
 *
 * Shows a side-by-side diff of every section the AI wants to change with:
 *   - confidence badge (🟢 / 🟡 / 🔴)
 *   - rationale (if provided, e.g. quote from meeting transcript)
 *   - "accept" checkbox per section
 *
 * On submit, POSTs `accepted_sections` to /apply; on discard POSTs /reject.
 */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, ThumbsDown, ThumbsUp, X } from "lucide-react";
import {
  CHAMPION_SECTIONS,
  championSuggestionsApi,
  type ChampionProfile,
  type ChampionProfileSuggestion,
  type ChampionSectionName,
  type ChampionSectionPatch,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SECTION_LABELS: Record<ChampionSectionName, string> = {
  basics: "1. Podstawowe informacje",
  project_context: "2. Kontekst projektu",
  screening_questions: "3. Pytania screeningowe",
  historical_client_questions: "4. Historyczne pytania klienta",
  internal_consultant_insight: "5. Insight konsultanta",
  sourcing: "6. Strategia sourcingowa",
};

interface ChampionProfileSuggestionReviewProps {
  jobId: number;
  suggestion: ChampionProfileSuggestion;
  currentProfile: ChampionProfile;
  onClose: () => void;
  onApplied?: (suggestion: ChampionProfileSuggestion) => void;
}

export function ChampionProfileSuggestionReview({
  jobId,
  suggestion,
  currentProfile,
  onClose,
  onApplied,
}: ChampionProfileSuggestionReviewProps) {
  const qc = useQueryClient();

  // Only list sections that the AI actually touched.
  const patches = useMemo<ChampionSectionPatch[]>(
    () => suggestion.patches.filter((p) => p.value !== null && p.value !== undefined),
    [suggestion.patches],
  );

  const defaultAccepted: Record<ChampionSectionName, boolean> = useMemo(() => {
    const acc = Object.fromEntries(
      CHAMPION_SECTIONS.map((s) => [s, false]),
    ) as Record<ChampionSectionName, boolean>;
    // Check sections with confidence >= 0.5 by default — DL can uncheck.
    for (const p of patches) {
      if (p.confidence >= 0.5) acc[p.section] = true;
    }
    return acc;
  }, [patches]);

  const [accepted, setAccepted] = useState<Record<ChampionSectionName, boolean>>(
    defaultAccepted,
  );

  const applyMutation = useMutation({
    mutationFn: async () => {
      const sections = (Object.keys(accepted) as ChampionSectionName[]).filter(
        (s) => accepted[s],
      );
      const res = await championSuggestionsApi.apply(suggestion.id, sections);
      return res.data;
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["champion-profile", jobId] });
      qc.invalidateQueries({ queryKey: ["champion-suggestions", jobId] });
      onApplied?.(result);
      onClose();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: async () => {
      const res = await championSuggestionsApi.reject(suggestion.id);
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-suggestions", jobId] });
      onClose();
    },
  });

  const acceptedCount = Object.values(accepted).filter(Boolean).length;
  const busy = applyMutation.isPending || rejectMutation.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 overflow-y-auto">
      <div className="bg-card dark:bg-card w-full max-w-5xl rounded-xl shadow-2xl my-8 overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 py-4 border-b border-border dark:border-border">
          <div>
            <h2 className="text-lg font-bold text-foreground dark:text-foreground flex items-center gap-2">
              <span>✨ Draft Profilu Championa</span>
              <SourceBadge source={suggestion.source_type} />
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              Przejrzyj sekcje i zaznacz te, które chcesz zastosować. Aktualna
              zawartość profilu zostanie zachowana dla pozostałych sekcji.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="p-1 rounded hover:bg-muted dark:hover:bg-muted"
            aria-label="Zamknij"
          >
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 max-h-[70vh]">
          {suggestion.error_message ? (
            <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
              Błąd generowania: {suggestion.error_message}
            </div>
          ) : patches.length === 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              AI nie zaproponował żadnych zmian.
            </div>
          ) : (
            patches.map((p) => (
              <SectionDiff
                key={p.section}
                patch={p}
                current={currentProfile[p.section]}
                accepted={accepted[p.section]}
                onToggle={(v) =>
                  setAccepted((prev) => ({ ...prev, [p.section]: v }))
                }
              />
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-3 border-t border-border dark:border-border bg-muted dark:bg-gray-950">
          <div className="text-xs text-muted-foreground">
            Wybrano: <span className="font-semibold">{acceptedCount}</span> /{" "}
            {patches.length} sekcji
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => rejectMutation.mutate()}
              disabled={busy || suggestion.status !== "pending"}
              className="px-3 py-1.5 text-sm rounded-lg bg-card dark:bg-card border border-border dark:border-border text-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted disabled:opacity-60"
            >
              {rejectMutation.isPending ? "Odrzucam…" : "Odrzuć całość"}
            </button>
            <button
              type="button"
              onClick={() => applyMutation.mutate()}
              disabled={
                busy ||
                acceptedCount === 0 ||
                suggestion.status !== "pending"
              }
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-primary hover:bg-primary/90 text-white font-medium disabled:opacity-60"
            >
              {applyMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4" />
              )}
              {applyMutation.isPending ? "Zastosowuję…" : "Zastosuj wybrane"}
            </button>
          </div>
        </div>

        {applyMutation.error ? (
          <div className="px-6 py-2 text-xs text-destructive border-t border-destructive/20 bg-destructive/10">
            Błąd zastosowania: {(applyMutation.error as Error).message}
          </div>
        ) : null}

        {/* Phase 15 / Phase C: rating buttons appear only after terminal status */}
        {suggestion.status !== "pending" && (
          <RatingBar suggestion={suggestion} />
        )}
      </div>
    </div>
  );
}

// ── Rating bar (Phase 15 / Phase C) ────────────────────────────────────────

function RatingBar({ suggestion }: { suggestion: ChampionProfileSuggestion }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState(suggestion.rating_comment ?? "");
  const [showCommentBox, setShowCommentBox] = useState(false);
  const rateMutation = useMutation({
    mutationFn: async (rating: -1 | 0 | 1) => {
      const res = await championSuggestionsApi.rate(
        suggestion.id,
        rating,
        comment || undefined,
      );
      return res.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["champion-suggestions", suggestion.job_id] });
    },
  });

  const currentRating = rateMutation.data?.rating ?? suggestion.rating ?? null;

  return (
    <div className="px-6 py-3 border-t border-border dark:border-border bg-muted dark:bg-gray-950 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">
          Czy draft był pomocny?
          {currentRating !== null && (
            <span className="ml-2 text-foreground dark:text-muted-foreground">
              Oceniłeś:{" "}
              {currentRating === 1
                ? "trafione"
                : currentRating === -1
                ? "nietrafione"
                : "nijak"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <RatingButton
            icon={<ThumbsUp className="w-3.5 h-3.5" />}
            label="Trafione"
            active={currentRating === 1}
            disabled={rateMutation.isPending}
            onClick={() => rateMutation.mutate(1)}
            tone="green"
          />
          <RatingButton
            icon={<ThumbsDown className="w-3.5 h-3.5" />}
            label="Nietrafione"
            active={currentRating === -1}
            disabled={rateMutation.isPending}
            onClick={() => rateMutation.mutate(-1)}
            tone="red"
          />
          <button
            type="button"
            className="text-xs text-muted-foreground underline"
            onClick={() => setShowCommentBox((v) => !v)}
          >
            {showCommentBox ? "Schowaj komentarz" : "Dodaj komentarz"}
          </button>
        </div>
      </div>
      {showCommentBox && (
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="np. trzeba było mocno przeredagować project_context"
          className="w-full px-2 py-1 text-xs border border-border dark:border-border rounded bg-card dark:bg-card min-h-[60px]"
          maxLength={2000}
        />
      )}
      {rateMutation.isError && (
        <div className="text-xs text-destructive">
          Nie udało się zapisać oceny.
        </div>
      )}
    </div>
  );
}

function RatingButton({
  icon,
  label,
  active,
  disabled,
  onClick,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  tone: "green" | "red";
}) {
  const palette = {
    green: {
      active:
        "bg-green-600 text-white border-green-700",
      idle:
        "bg-card dark:bg-card text-green-700 dark:text-green-300 border-green-300 hover:bg-green-50",
    },
    red: {
      active: "bg-red-600 text-white border-red-700",
      idle:
        "bg-card dark:bg-card text-destructive dark:text-red-300 border-red-300 hover:bg-destructive/10",
    },
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "text-xs px-2 py-1 rounded border inline-flex items-center gap-1 disabled:opacity-60",
        active ? palette.active : palette.idle,
      )}
    >
      {icon}
      {label}
    </button>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function SourceBadge({ source }: { source: ChampionProfileSuggestion["source_type"] }) {
  const labels: Record<ChampionProfileSuggestion["source_type"], string> = {
    jd_paste: "opis klienta",
    fireflies_meeting: "Fireflies",
    cloudtalk_call: "CloudTalk",
    manual_consultant_note: "notatka konsultanta",
    historical_jobs: "historia",
  };
  return (
    <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded bg-purple-100 text-purple-700">
      {labels[source]}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const color =
    confidence >= 0.8
      ? "bg-emerald-100 text-emerald-800"
      : confidence >= 0.5
      ? "bg-amber-100 text-amber-800"
      : "bg-muted text-muted-foreground";
  const icon =
    confidence >= 0.8 ? "🟢" : confidence >= 0.5 ? "🟡" : "🔴";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium",
        color,
      )}
    >
      {icon} conf {confidence.toFixed(2)}
    </span>
  );
}

interface SectionDiffProps {
  patch: ChampionSectionPatch;
  current: unknown;
  accepted: boolean;
  onToggle: (v: boolean) => void;
}

function SectionDiff({ patch, current, accepted, onToggle }: SectionDiffProps) {
  return (
    <div
      className={cn(
        "border rounded-xl overflow-hidden",
        accepted
          ? "border-primary/30 dark:border-primary/90"
          : "border-border dark:border-border",
      )}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2 bg-muted dark:bg-card">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => onToggle(e.target.checked)}
            className="w-4 h-4"
          />
          <span className="font-medium text-sm text-foreground dark:text-foreground">
            {SECTION_LABELS[patch.section]}
          </span>
          <ConfidenceBadge confidence={patch.confidence} />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-0 divide-x divide-gray-200 dark:divide-gray-800">
        <SideCol title="Obecne" value={current} muted />
        <SideCol title="Proponowane" value={patch.value} highlight />
      </div>
      {patch.rationale ? (
        <div className="px-4 py-2 text-[11px] text-muted-foreground bg-muted dark:bg-gray-950 border-t border-border dark:border-border">
          <span className="font-semibold">Uzasadnienie:</span> {patch.rationale}
        </div>
      ) : null}
    </div>
  );
}

function SideCol({
  title,
  value,
  muted,
  highlight,
}: {
  title: string;
  value: unknown;
  muted?: boolean;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "px-4 py-3 text-sm",
        highlight && "bg-primary/10 dark:bg-primary/30",
      )}
    >
      <div
        className={cn(
          "text-[10px] uppercase tracking-wide font-semibold mb-1",
          muted ? "text-muted-foreground" : "text-primary dark:text-primary",
        )}
      >
        {title}
      </div>
      <ValuePreview value={value} />
    </div>
  );
}

function ValuePreview({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-xs italic text-muted-foreground">— puste —</span>;
  }
  if (typeof value === "string") {
    return (
      <p className="whitespace-pre-wrap text-foreground dark:text-muted-foreground">
        {value}
      </p>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <p className="text-foreground dark:text-muted-foreground">{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-xs italic text-muted-foreground">— pusta lista —</span>;
    }
    return (
      <ul className="list-disc pl-5 space-y-0.5 text-foreground dark:text-muted-foreground">
        {value.map((item, i) => (
          <li key={i}>
            <ValuePreview value={item} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return (
      <dl className="space-y-0.5">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {k}
            </dt>
            <dd className="text-foreground dark:text-muted-foreground pl-2">
              <ValuePreview value={v} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="text-muted-foreground">{String(value)}</p>;
}
