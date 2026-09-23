"use client";

/**
 * Tagi w nagłówku profilu kandydata — podgląd dla każdego, edycja chipami dla
 * `candidate.write`. Każda zmiana to JEDEN tag (`POST/DELETE …/tags`), nigdy
 * cała lista: obiekty importu Traffita (źródło pozyskania) zostają nietknięte,
 * a tag dodany równolegle przez kolegę nie znika.
 */

import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { getTagName } from "@/components/v2/pages/candidate-list-helpers";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { apiErrorMessage } from "@/lib/api-error";
import {
  addCandidateTag,
  candidateTagKeys,
  hasStringTag,
  normalizeTagInput,
  removeCandidateTag,
  suggestCandidateTags,
  type CandidateTagsResponse,
} from "@/lib/api/candidateTags";

interface Props {
  candidateId: number;
  tags: unknown;
  canEdit: boolean;
}

interface TagChip {
  label: string;
  /** Napis da się usunąć; obiekt importu — nie. */
  removable: boolean;
}

export function tagChips(tags: unknown): TagChip[] {
  if (!Array.isArray(tags)) return [];
  const seen = new Set<string>();
  const out: TagChip[] = [];
  for (const raw of tags) {
    const label = getTagName(raw);
    if (!label) continue;
    const key = label.toLocaleLowerCase("pl");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ label, removable: typeof raw === "string" });
  }
  return out;
}

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function CandidateTagsEditor({ candidateId, tags, canEdit }: Props) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const listId = useId();
  const debounced = useDebounced(draft, 250);
  const chips = tagChips(tags);

  const suggestions = useQuery({
    queryKey: candidateTagKeys.suggest(debounced),
    queryFn: () => suggestCandidateTags(debounced),
    enabled: adding && canEdit,
    staleTime: 60_000,
  });

  const applyResult = (result: CandidateTagsResponse) => {
    queryClient.setQueryData(candidateQueryKeys.detail(candidateId), (prev: unknown) =>
      prev && typeof prev === "object" ? { ...(prev as object), tags: result.tags } : prev,
    );
    void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
    void queryClient.invalidateQueries({ queryKey: ["candidate-tags"] });
  };

  const add = useMutation({
    mutationFn: (tag: string) => addCandidateTag(candidateId, tag),
    onSuccess: (result) => {
      applyResult(result);
      setDraft("");
      setAdding(false);
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać tagu.")),
  });

  const remove = useMutation({
    mutationFn: (tag: string) => removeCandidateTag(candidateId, tag),
    onSuccess: applyResult,
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się usunąć tagu.")),
  });

  const normalized = normalizeTagInput(draft);
  const duplicate = normalized.tag !== null && hasStringTag(tags, normalized.tag);
  const submit = () => {
    if (!normalized.tag || duplicate || add.isPending) return;
    add.mutate(normalized.tag);
  };

  if (chips.length === 0 && !canEdit) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1" aria-label="Tagi kandydata">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"
        >
          #{chip.label}
          {canEdit && chip.removable ? (
            <button
              type="button"
              aria-label={`Usuń tag ${chip.label}`}
              disabled={remove.isPending}
              onClick={() => remove.mutate(chip.label)}
              className="rounded-full p-0.5 hover:bg-primary/20 disabled:opacity-50"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          ) : null}
        </span>
      ))}
      {canEdit && !adding ? (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary"
        >
          <Plus className="h-3 w-3" aria-hidden />
          Tag
        </button>
      ) : null}
      {canEdit && adding ? (
        <span className="inline-flex flex-col gap-0.5">
          <span className="inline-flex items-center gap-1">
            <input
              autoFocus
              aria-label="Nowy tag"
              list={listId}
              value={draft}
              maxLength={80}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submit();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  setDraft("");
                  setAdding(false);
                }
              }}
              placeholder="np. senior, bankowość"
              className="h-7 w-44 rounded-md border border-input bg-background px-2 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <datalist id={listId}>
              {(suggestions.data ?? [])
                .filter((s) => !hasStringTag(tags, s.name))
                .map((s) => (
                  <option key={s.name} value={s.name}>
                    {`${s.name} (${s.count})`}
                  </option>
                ))}
            </datalist>
            <button
              type="button"
              onClick={submit}
              disabled={!normalized.tag || duplicate || add.isPending}
              className="h-7 rounded-md bg-primary px-2 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              Dodaj
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft("");
                setAdding(false);
              }}
              className="h-7 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent"
            >
              Anuluj
            </button>
          </span>
          {normalized.error || duplicate ? (
            <span role="alert" className="text-xs text-destructive">
              {normalized.error ?? "Kandydat ma już ten tag."}
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
