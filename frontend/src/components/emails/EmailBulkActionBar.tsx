"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CheckCheck,
  Link as LinkIcon,
  Loader2,
  Mail,
  MailOpen,
  Search,
  Unlink,
  X,
} from "lucide-react";

import {
  candidatesApi,
  microsoft365Api,
  type BulkEmailAction,
  type BulkEmailActionResponse,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

interface EmailBulkActionBarProps {
  selectedIds: number[];
  onClear: () => void;
  onCompleted?: (response: BulkEmailActionResponse) => void;
  /** Queries to invalidate after a successful mutation (e.g. candidate threads). */
  invalidateQueryKeys?: ReadonlyArray<ReadonlyArray<unknown>>;
}

interface ActionConfig {
  type: BulkEmailAction;
  label: string;
  icon: React.ReactNode;
  description: string;
  needsCandidate?: boolean;
}

const ACTIONS: ActionConfig[] = [
  {
    type: "archive",
    label: "Archiwizuj",
    icon: <Archive className="w-4 h-4" />,
    description: "Ukrywa wybrane maile z domyślnego widoku wątków.",
  },
  {
    type: "mark_read",
    label: "Oznacz jako przeczytane",
    icon: <MailOpen className="w-4 h-4" />,
    description: "Ustawia is_read=true dla wybranych maili.",
  },
  {
    type: "mark_unread",
    label: "Oznacz jako nieprzeczytane",
    icon: <Mail className="w-4 h-4" />,
    description: "Ustawia is_read=false dla wybranych maili.",
  },
  {
    type: "link_to_candidate",
    label: "Połącz z kandydatem",
    icon: <LinkIcon className="w-4 h-4" />,
    description: "Przepina wybrane maile do innego kandydata (match_method=manual).",
    needsCandidate: true,
  },
  {
    type: "unlink",
    label: "Odepnij",
    icon: <Unlink className="w-4 h-4" />,
    description: "Usuwa powiązanie maila z kandydatem (match_method=unmatched).",
  },
];

interface CandidateSearchResult {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
}

export function EmailBulkActionBar({
  selectedIds,
  onClear,
  onCompleted,
  invalidateQueryKeys,
}: EmailBulkActionBarProps) {
  const [activeAction, setActiveAction] = useState<BulkEmailAction | null>(null);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [feedback, setFeedback] = useState<{
    variant: "success" | "error";
    title: string;
    description?: string;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(candidateQuery.trim()), 250);
    return () => clearTimeout(t);
  }, [candidateQuery]);

  useEffect(() => {
    if (activeAction === "link_to_candidate") {
      inputRef.current?.focus();
    }
  }, [activeAction]);

  const candidatesQuery = useQuery({
    queryKey: ["bulk-email-candidate-search", debouncedQuery],
    queryFn: async () => {
      const r = await candidatesApi.list({
        q: debouncedQuery,
        page_size: 10,
      });
      const items = ((r.data as { items?: CandidateSearchResult[] }).items ?? []);
      return items;
    },
    enabled: activeAction === "link_to_candidate" && debouncedQuery.length >= 2,
    staleTime: 30_000,
  });

  const mutation = useMutation({
    mutationFn: async (params: {
      action: BulkEmailAction;
      candidate_id?: number;
    }) => {
      const r = await microsoft365Api.bulkAction({
        email_ids: selectedIds,
        action: params.action,
        candidate_id: params.candidate_id,
      });
      return r.data;
    },
    onSuccess: (data) => {
      if (invalidateQueryKeys) {
        for (const key of invalidateQueryKeys) {
          queryClient.invalidateQueries({ queryKey: [...key] });
        }
      }
      setActiveAction(null);
      setCandidateQuery("");
      setFeedback({
        variant: "success",
        title: `Zaktualizowano ${data.updated_count} ${pluralizeMail(data.updated_count)}`,
        description:
          data.skipped_count > 0
            ? `Pominięto ${data.skipped_count} (np. cudze maile / nieznane id).`
            : undefined,
      });
      onCompleted?.(data);
      onClear();
    },
    onError: () => {
      setFeedback({
        variant: "error",
        title: "Operacja nie powiodła się",
        description: "Spróbuj ponownie lub sprawdź połączenie M365.",
      });
    },
  });

  useEffect(() => {
    if (!feedback) return;
    const t = setTimeout(() => setFeedback(null), 4000);
    return () => clearTimeout(t);
  }, [feedback]);

  const triggerAction = (action: ActionConfig) => {
    if (mutation.isPending) return;
    if (action.needsCandidate) {
      setActiveAction(action.type);
      return;
    }
    setActiveAction(null);
    mutation.mutate({ action: action.type });
  };

  const submitLink = (candidateId: number) => {
    mutation.mutate({ action: "link_to_candidate", candidate_id: candidateId });
  };

  const searchResults = useMemo(
    () => candidatesQuery.data ?? [],
    [candidatesQuery.data],
  );

  if (selectedIds.length === 0 && !feedback) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-full max-w-3xl px-4 pointer-events-none">
      <div className="space-y-2 pointer-events-auto">
        {feedback && (
          <Alert
            variant={feedback.variant}
            title={feedback.title}
            description={feedback.description}
          />
        )}

        {selectedIds.length > 0 && (
          <div className="bg-card border border-border rounded-xl shadow-2xl p-3">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm font-semibold text-foreground">
                {selectedIds.length} {pluralizeMail(selectedIds.length)} zaznaczone
              </span>

              <div className="flex flex-wrap gap-1">
                {ACTIONS.map((action) => (
                  <button
                    key={action.type}
                    type="button"
                    onClick={() => triggerAction(action)}
                    disabled={mutation.isPending}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                      "text-foreground hover:bg-muted",
                      "disabled:opacity-50 disabled:cursor-not-allowed",
                      activeAction === action.type && "bg-primary/10 text-primary",
                    )}
                    title={action.description}
                  >
                    {mutation.isPending &&
                    mutation.variables?.action === action.type ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      action.icon
                    )}
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

            {activeAction === "link_to_candidate" && (
              <div className="mt-3 pt-3 border-t border-border space-y-2">
                <div className="flex items-center gap-2">
                  <Search className="w-4 h-4 text-muted-foreground shrink-0" />
                  <input
                    ref={inputRef}
                    type="text"
                    value={candidateQuery}
                    onChange={(e) => setCandidateQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setActiveAction(null);
                    }}
                    placeholder="Szukaj kandydata po nazwisku, imieniu lub email…"
                    className="flex-1 bg-background border border-input rounded-md px-3 py-1.5 text-sm focus:outline-hidden focus:ring-2 focus:ring-ring"
                  />
                  <button
                    type="button"
                    onClick={() => setActiveAction(null)}
                    className="text-sm text-muted-foreground hover:text-foreground"
                  >
                    Anuluj
                  </button>
                </div>

                {debouncedQuery.length < 2 ? (
                  <p className="text-xs text-muted-foreground px-1">
                    Wpisz co najmniej 2 znaki, aby wyszukać kandydata.
                  </p>
                ) : candidatesQuery.isLoading ? (
                  <p className="text-xs text-muted-foreground px-1 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Szukam…
                  </p>
                ) : searchResults.length === 0 ? (
                  <p className="text-xs text-muted-foreground px-1">
                    Brak wyników.
                  </p>
                ) : (
                  <ul className="max-h-48 overflow-y-auto rounded-md border border-border bg-background">
                    {searchResults.map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => submitLink(c.id)}
                          disabled={mutation.isPending}
                          className="w-full text-left px-3 py-2 hover:bg-muted text-sm flex items-center gap-2 disabled:opacity-50"
                        >
                          <CheckCheck className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="font-medium">
                            {c.name} {c.lastname}
                          </span>
                          {c.email && (
                            <span className="text-xs text-muted-foreground truncate">
                              {c.email}
                            </span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function pluralizeMail(n: number): string {
  if (n === 1) return "mail";
  // Polish 2-4 vs 5+ (with the 12-14 exception).
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "maile";
  return "maili";
}
