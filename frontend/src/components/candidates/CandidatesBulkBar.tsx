"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Tag,
  Briefcase,
  EyeOff,
  Users,
  X,
  Loader2,
  AlertCircle,
} from "lucide-react";
import {
  candidatesBulkApi,
  type BulkActionType,
  type BulkActionResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface CandidatesBulkBarProps {
  selectedIds: number[];
  onClear: () => void;
  onCompleted?: (response: BulkActionResponse) => void;
}

interface ActionConfig {
  type: BulkActionType;
  label: string;
  icon: React.ReactNode;
  destructive?: boolean;
  description: string;
}

const ACTIONS: ActionConfig[] = [
  {
    type: "add_tags",
    label: "Dodaj tagi",
    icon: <Tag className="w-4 h-4" />,
    description: "Dopisuje podane tagi (oddzielone przecinkami) do wybranych kandydatów.",
  },
  {
    type: "assign_talent_pool",
    label: "Do talent pool",
    icon: <Users className="w-4 h-4" />,
    description:
      "Otwiera picker talent pools – przypisanie wykona się przez bulk endpoint pools.",
  },
  {
    type: "assign_to_job",
    label: "Do rekrutacji",
    icon: <Briefcase className="w-4 h-4" />,
    description:
      "Otwiera picker rekrutacji – propose przebiega przez /jobs/{id}/proposals/bulk.",
  },
  {
    type: "anonymize_pii",
    label: "Anonimizuj (RODO)",
    icon: <EyeOff className="w-4 h-4" />,
    destructive: true,
    description:
      "Czyści PII (imię/nazwisko/email/telefon/LinkedIn) i ustawia status=blacklisted. Operacja nieodwracalna.",
  },
];

/**
 * Floating bulk-action bar that appears when one or more candidates are
 * selected on the list view. Mirrors Traffit's "akcje masowe" floating
 * bar – sticks to the bottom of the viewport and shows the count + action
 * buttons. Tag-input is inline; talent-pool / job pickers delegate to the
 * existing modals (callers wire those up).
 */
export function CandidatesBulkBar({
  selectedIds,
  onClear,
  onCompleted,
}: CandidatesBulkBarProps) {
  const [activeAction, setActiveAction] = useState<BulkActionType | null>(null);
  const [tagDraft, setTagDraft] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: ({
      action,
      params,
    }: {
      action: BulkActionType;
      params?: Record<string, unknown>;
    }) =>
      candidatesBulkApi
        .dispatch({ action, candidate_ids: selectedIds, params })
        .then((r) => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      setActiveAction(null);
      setTagDraft("");
      onCompleted?.(data);
    },
  });

  if (selectedIds.length === 0) return null;

  const submitTags = () => {
    const tags = tagDraft
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);
    if (tags.length === 0) return;
    mutation.mutate({ action: "add_tags", params: { tags } });
  };

  const confirmAndAnonymize = () => {
    if (
      !window.confirm(
        `Anonimizować ${selectedIds.length} kandydat(ów)? Operacja jest nieodwracalna.`,
      )
    ) {
      return;
    }
    mutation.mutate({ action: "anonymize_pii" });
  };

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-full max-w-3xl px-4">
      <div className="bg-card border border-border rounded-xl shadow-2xl p-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-foreground">
            {selectedIds.length}{" "}
            {selectedIds.length === 1
              ? "kandydat"
              : selectedIds.length < 5
                ? "kandydatów"
                : "kandydatów"}
          </span>

          <div className="flex flex-wrap gap-1">
            {ACTIONS.map((action) => (
              <button
                key={action.type}
                type="button"
                onClick={() => {
                  if (action.type === "anonymize_pii") {
                    confirmAndAnonymize();
                  } else {
                    setActiveAction(action.type);
                  }
                }}
                disabled={mutation.isPending}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                  action.destructive
                    ? "text-rose-500 hover:bg-rose-500/10"
                    : "text-foreground hover:bg-muted",
                  "disabled:opacity-50 disabled:cursor-not-allowed",
                  activeAction === action.type && "bg-primary/10 text-primary",
                )}
                title={action.description}
              >
                {action.icon}
                {action.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={onClear}
            className="ml-auto p-1.5 text-muted-foreground hover:text-foreground rounded-md"
            title="Wyczyść zaznaczenie"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {activeAction === "add_tags" && (
          <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
            <Tag className="w-4 h-4 text-muted-foreground shrink-0" />
            <input
              type="text"
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitTags();
                if (e.key === "Escape") setActiveAction(null);
              }}
              placeholder="senior, python, remote – oddziel przecinkami, Enter aby zapisać"
              className="flex-1 bg-background border border-input rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              autoFocus
            />
            <button
              type="button"
              onClick={submitTags}
              disabled={mutation.isPending || !tagDraft.trim()}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md disabled:opacity-50"
            >
              {mutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                "Dodaj"
              )}
            </button>
            <button
              type="button"
              onClick={() => setActiveAction(null)}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Anuluj
            </button>
          </div>
        )}

        {(activeAction === "assign_talent_pool" ||
          activeAction === "assign_to_job") && (
          <div className="mt-3 pt-3 border-t border-border flex items-center gap-2 text-sm text-muted-foreground">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              Wybierz {activeAction === "assign_talent_pool" ? "talent pool" : "rekrutację"} z
              listy obok – przypisanie zostanie wykonane po wybraniu.
            </span>
            <button
              type="button"
              onClick={() => setActiveAction(null)}
              className="ml-auto text-muted-foreground hover:text-foreground"
            >
              Zamknij
            </button>
          </div>
        )}

        {mutation.isError && (
          <div className="mt-2 text-xs text-rose-500 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            Wykonanie operacji nie powiodło się.
          </div>
        )}
      </div>
    </div>
  );
}
