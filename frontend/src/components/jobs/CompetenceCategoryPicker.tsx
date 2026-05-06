"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Info } from "lucide-react";
import { api } from "@/lib/api";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";

export interface CompetenceCategory {
  id: number;
  slug: string;
  name_pl: string;
  name_en: string;
  description: string;
  keywords: string[];
  display_order: number;
}

export interface CcSuggestion {
  competence_category_id: number;
  slug: string;
  name_pl: string;
  score: number;
  confidence_band: "high" | "medium" | "low";
  keywords_matched: string[];
}

export interface CcSuggestionsResponse {
  top: CcSuggestion | null;
  alternatives: CcSuggestion[];
  tie: boolean;
}

interface Props {
  value: number | null;
  onChange: (value: number | null) => void;
  /** Draft job input: when non-empty, we offer an "Auto-suggest" button. */
  jobTitle: string;
  description?: string;
  requirements?: string;
  /** If provided, the picker shows an AI suggestion panel immediately. */
  initialSuggestions?: CcSuggestionsResponse | null;
  /** Called when user accepts an AI suggestion (for override-logging). */
  onAcceptSuggestion?: (suggestion: CcSuggestion) => void;
}

/**
 * CompetenceCategoryPicker — dropdown of 5 CCs with AI auto-suggest banner.
 *
 * When `initialSuggestions.top` is available and not a tie, the picker
 * pre-highlights the suggested CC with a confidence badge. The user can still
 * freely change the selection — which fires `onAcceptSuggestion(null)`-like
 * intent via `onChange`, so the caller can log a `cc-override`.
 */
export function CompetenceCategoryPicker({
  value,
  onChange,
  jobTitle,
  description,
  requirements,
  initialSuggestions,
  onAcceptSuggestion,
}: Props) {
  const { data: categoriesData, isLoading: loadingCats } = useQuery({
    queryKey: ["competence-categories"],
    queryFn: () =>
      api
        .get<CompetenceCategory[]>("/api/competence-categories")
        .then((r) => r.data),
    staleTime: 60 * 60 * 1000, // 1h cache — CCs rarely change
  });

  const categories = useMemo(() => categoriesData ?? [], [categoriesData]);

  const [suggestions, setSuggestions] = useState<CcSuggestionsResponse | null>(
    initialSuggestions ?? null,
  );
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);

  // Auto-pre-select on first load if we have a confident top and user hasn't picked.
  useEffect(() => {
    if (value !== null) return;
    if (!suggestions?.top) return;
    if (suggestions.tie) return;
    onChange(suggestions.top.competence_category_id);
    onAcceptSuggestion?.(suggestions.top);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestions]);

  const canSuggest = Boolean(jobTitle && jobTitle.trim().length >= 4);

  const handleSuggest = async () => {
    setSuggestError(null);
    setSuggestLoading(true);
    try {
      // No job exists yet — call the classifier with a draft payload via dedicated endpoint?
      // MVP: for the create flow we rely on post-create classification; here we just
      // nudge the user with a keyword-based hint computed client-side.
      const corpus = [jobTitle, description, requirements]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!corpus) {
        setSuggestError("Wpisz tytuł / opis przed sugestią.");
        return;
      }
      const scored = categories.map((cc) => {
        const matched = (cc.keywords ?? []).filter((k) =>
          corpus.includes(k.toLowerCase()),
        );
        const ratio = (cc.keywords?.length ?? 0)
          ? matched.length / (cc.keywords?.length ?? 1)
          : 0;
        return {
          cc,
          ratio,
          matched,
          score: Math.min(1, ratio < 0.4 ? ratio * 2.5 : ratio + 0.3),
        };
      });
      scored.sort((a, b) => b.score - a.score);
      const top = scored[0];
      const second = scored[1];
      if (!top || top.score <= 0) {
        setSuggestError("Za mało kontekstu — wybierz CC ręcznie.");
        return;
      }
      const tie = !!second && Math.abs(top.score - second.score) < 0.1;
      const toSuggestion = (x: (typeof scored)[number]): CcSuggestion => ({
        competence_category_id: x.cc.id,
        slug: x.cc.slug,
        name_pl: x.cc.name_pl,
        score: Number(x.score.toFixed(4)),
        confidence_band:
          x.score >= 0.65 ? "high" : x.score >= 0.4 ? "medium" : "low",
        keywords_matched: x.matched.slice(0, 10),
      });
      const resp: CcSuggestionsResponse = {
        top: toSuggestion(top),
        alternatives: scored.slice(1, 3).map(toSuggestion),
        tie,
      };
      setSuggestions(resp);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Błąd sugestii";
      setSuggestError(msg);
    } finally {
      setSuggestLoading(false);
    }
  };

  const selectedSuggestionForValue = useMemo(() => {
    if (!value || !suggestions) return null;
    if (suggestions.top?.competence_category_id === value) return suggestions.top;
    return (
      suggestions.alternatives.find(
        (a) => a.competence_category_id === value,
      ) ?? null
    );
  }, [value, suggestions]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-muted-foreground dark:text-muted-foreground">
          Competence Category
        </label>
        {canSuggest && (
          <button
            type="button"
            onClick={handleSuggest}
            disabled={suggestLoading || loadingCats}
            className="text-[11px] text-primary hover:text-primary/80 font-medium disabled:opacity-50"
          >
            {suggestLoading ? "Analizuję…" : "✨ Sugeruj AI"}
          </button>
        )}
      </div>
      <select
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value ? Number(e.target.value) : null)
        }
        className="w-full h-10 rounded-lg border border-border dark:border-border bg-card dark:bg-card px-3 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
      >
        <option value="">— wybierz kategorię —</option>
        {categories.map((cc) => (
          <option key={cc.id} value={cc.id}>
            {cc.name_pl}
          </option>
        ))}
      </select>

      {suggestError && (
        <div className="text-[11px] text-amber-700 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          {suggestError}
        </div>
      )}

      {suggestions?.tie && (
        <div className="text-[11px] text-amber-800 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1.5 flex items-center gap-1.5">
          <AlertCircle className="w-3.5 h-3.5" />
          AI nie rozstrzyga — dwa bliskie dopasowania. Wybierz ręcznie.
        </div>
      )}

      {suggestions && !suggestions.tie && suggestions.top && (
        <div className="text-[11px] bg-primary/10 dark:bg-primary/30 rounded px-2 py-1.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ConfidenceBadge
              score={
                selectedSuggestionForValue?.score ?? suggestions.top.score
              }
              band={
                selectedSuggestionForValue?.confidence_band ??
                suggestions.top.confidence_band
              }
            />
            <span className="text-foreground dark:text-muted-foreground">
              AI sugeruje: <strong>{suggestions.top.name_pl}</strong>
            </span>
          </div>
          {(suggestions.top.keywords_matched?.length ?? 0) > 0 && (
            <span
              title={`Dopasowane słowa: ${suggestions.top.keywords_matched.join(", ")}`}
              className="text-muted-foreground hover:text-foreground cursor-help"
            >
              <Info className="w-3.5 h-3.5" />
            </span>
          )}
        </div>
      )}
    </div>
  );
}
