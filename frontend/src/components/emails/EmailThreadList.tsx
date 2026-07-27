"use client";

import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Mail,
  Paperclip,
  PlusCircle,
  Search,
  Sparkles,
  User,
} from "lucide-react";

import {
  microsoft365Api,
  type EmailSearchHit,
  type EmailThreadPreview,
} from "@/lib/api";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn, formatRelativeTime } from "@/lib/utils";

import EmailCompose from "./EmailCompose";
import EmailThreadView from "./EmailThreadView";
import { EmailBulkActionBar } from "./EmailBulkActionBar";

interface EmailThreadListProps {
  candidateId: number;
  candidateName: string;
  candidateEmail: string | null;
}

const MIN_SEARCH_LEN = 2;

export default function EmailThreadList({
  candidateId,
  candidateName,
  candidateEmail,
}: EmailThreadListProps) {
  const [openConversation, setOpenConversation] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const isSearching = debouncedQuery.length >= MIN_SEARCH_LEN;
  // Each thread row contributes `thread.latest.id` to the bulk selection.
  // Paired with the backend `is_archived` filter, archiving a single-message
  // thread's latest also hides the thread. Bulk works only in the default
  // (non-search) view to keep selection state coherent across query churn.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["candidate-emails", candidateId],
    queryFn: () =>
      microsoft365Api.listCandidateThreads(candidateId).then((r) => r.data),
    enabled: !!candidateId && !isSearching,
    staleTime: 30_000,
  });

  const {
    data: searchData,
    isLoading: isSearchLoading,
    error: searchError,
  } = useQuery({
    queryKey: ["m365-emails-search", debouncedQuery],
    queryFn: () =>
      microsoft365Api.searchEmails(debouncedQuery).then((r) => r.data),
    enabled: isSearching,
    staleTime: 10_000,
  });

  const threads: EmailThreadPreview[] = data ?? [];
  const hits: EmailSearchHit[] = searchData?.items ?? [];

  const visibleIds = useMemo(
    () => threads.map((t) => t.latest.id),
    [threads],
  );
  const allSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const someSelected =
    !allSelected && visibleIds.some((id) => selectedIds.has(id));

  const toggleOne = (id: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  };

  const toggleAll = (checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        for (const id of visibleIds) next.add(id);
      } else {
        for (const id of visibleIds) next.delete(id);
      }
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Wątki email</h3>
        <button
          onClick={() => setComposeOpen(true)}
          disabled={!candidateEmail}
          title={
            candidateEmail
              ? "Napisz nowy email do kandydata"
              : "Kandydat nie ma adresu email"
          }
          className="flex items-center gap-1.5 text-sm font-medium text-primary hover:text-primary/80 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <PlusCircle className="h-4 w-4" />
          Nowy email
        </button>
      </div>

      <Input
        type="search"
        placeholder="Szukaj w mailach…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        leadingIcon={<Search className="h-4 w-4" />}
        aria-label="Wyszukaj w mailach"
      />

      {isSearching ? (
        <SearchResults
          hits={hits}
          isLoading={isSearchLoading}
          error={searchError}
          query={debouncedQuery}
          onOpen={(conversationId) => setOpenConversation(conversationId)}
        />
      ) : (
        <ThreadResults
          threads={threads}
          isLoading={isLoading}
          error={error}
          onOpen={(conversationId) => setOpenConversation(conversationId)}
          selectedIds={selectedIds}
          allSelected={allSelected}
          someSelected={someSelected}
          onToggleOne={toggleOne}
          onToggleAll={toggleAll}
        />
      )}

      <EmailBulkActionBar
        selectedIds={Array.from(selectedIds)}
        onClear={clearSelection}
        invalidateQueryKeys={[["candidate-emails", candidateId]]}
      />

      {openConversation && (
        <EmailThreadView
          candidateId={candidateId}
          conversationId={openConversation}
          onClose={() => setOpenConversation(null)}
        />
      )}

      {composeOpen && candidateEmail && (
        <EmailCompose
          mode="new"
          candidateId={candidateId}
          candidateName={candidateName}
          defaultTo={candidateEmail}
          onClose={() => setComposeOpen(false)}
        />
      )}
    </div>
  );
}

// ── Thread list (default view) ───────────────────────────────────────────────

interface ThreadResultsProps {
  threads: EmailThreadPreview[];
  isLoading: boolean;
  error: unknown;
  onOpen: (conversationId: string) => void;
  selectedIds: Set<number>;
  allSelected: boolean;
  someSelected: boolean;
  onToggleOne: (id: number, checked: boolean) => void;
  onToggleAll: (checked: boolean) => void;
}

function ThreadResults({
  threads,
  isLoading,
  error,
  onOpen,
  selectedIds,
  allSelected,
  someSelected,
  onToggleOne,
  onToggleAll,
}: ThreadResultsProps) {
  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        Wczytuję wątki...
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-sm text-destructive py-4 text-center">
        Błąd ładowania wątków. Sprawdź status integracji w Ustawieniach.
      </div>
    );
  }
  if (threads.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-8 text-center">
        <Mail className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">
          Brak wątków email z tym kandydatem.
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Wątki pojawią się automatycznie po synchronizacji M365.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-muted/30">
        <Checkbox
          aria-label={allSelected ? "Odznacz wszystkie" : "Zaznacz wszystkie"}
          checked={
            allSelected ? true : someSelected ? "indeterminate" : false
          }
          onCheckedChange={(value) => onToggleAll(value === true)}
        />
        <span className="text-xs text-muted-foreground">
          {selectedIds.size > 0
            ? `Zaznaczono ${selectedIds.size}`
            : "Zaznacz, aby uruchomić akcje masowe"}
        </span>
      </div>
      <ul className="divide-y divide-gray-100">
        {threads.map((t) => {
          const checked = selectedIds.has(t.latest.id);
          return (
            <li
              key={t.conversation_id}
              className={cn(
                "flex items-start gap-3 px-4 py-3 hover:bg-muted transition",
                t.unread_count > 0 && "bg-primary/10",
                checked && "bg-primary/5",
              )}
            >
              <div className="pt-1" onClick={(e) => e.stopPropagation()}>
                <Checkbox
                  aria-label={`Zaznacz wątek: ${t.subject ?? "(bez tematu)"}`}
                  checked={checked}
                  onCheckedChange={(value) =>
                    onToggleOne(t.latest.id, value === true)
                  }
                />
              </div>

              <button
                type="button"
                onClick={() => onOpen(t.conversation_id)}
                className="flex-1 min-w-0 text-left flex items-start gap-3"
              >
                <div className="w-9 h-9 rounded-full bg-muted text-muted-foreground flex items-center justify-center text-sm font-medium shrink-0">
                  {initial(t.latest.from_name ?? t.latest.from_address)}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p
                      className={cn(
                        "text-sm truncate",
                        t.unread_count > 0
                          ? "font-semibold text-foreground"
                          : "font-medium text-foreground",
                      )}
                    >
                      {t.subject || "(bez tematu)"}
                    </p>
                    {t.message_count > 1 && (
                      <span className="text-xs text-muted-foreground">
                        {t.message_count}
                      </span>
                    )}
                    {t.latest.has_attachments && (
                      <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    {t.latest.match_method !== "strict" &&
                      t.latest.match_method !== "manual" && (
                        <span
                          className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded"
                          title={`Dopasowanie: ${t.latest.match_method}`}
                        >
                          <Sparkles className="h-3 w-3" />
                          smart
                        </span>
                      )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5">
                    <User className="h-3 w-3" />
                    <span className="truncate">
                      {t.latest.from_name ?? t.latest.from_address}
                    </span>
                  </p>
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {t.latest.body_preview ?? ""}
                  </p>
                </div>

                <div className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
                  {formatRelativeTime(t.latest.received_at)}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Search results (FTS view) ────────────────────────────────────────────────

interface SearchResultsProps {
  hits: EmailSearchHit[];
  isLoading: boolean;
  error: unknown;
  query: string;
  onOpen: (conversationId: string) => void;
}

function SearchResults({
  hits,
  isLoading,
  error,
  query,
  onOpen,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        Szukam…
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-sm text-destructive py-4 text-center">
        Błąd wyszukiwania. Spróbuj ponownie.
      </div>
    );
  }
  if (hits.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border p-8 text-center">
        <Mail className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">
          Brak wyników dla «{query}».
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-gray-100 rounded-xl border border-border bg-card">
      {hits.map((hit) => (
        <li key={hit.id}>
          <button
            onClick={() => onOpen(hit.m365_conversation_id)}
            className={cn(
              "w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-muted transition",
              !hit.is_read && "bg-primary/10",
            )}
          >
            <div className="w-9 h-9 rounded-full bg-muted text-muted-foreground flex items-center justify-center text-sm font-medium shrink-0">
              {initial(hit.from_name ?? hit.from_address)}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p
                  className={cn(
                    "text-sm truncate",
                    !hit.is_read
                      ? "font-semibold text-foreground"
                      : "font-medium text-foreground",
                  )}
                >
                  {hit.subject || "(bez tematu)"}
                </p>
                {hit.has_attachments && (
                  <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5">
                <User className="h-3 w-3" />
                <span className="truncate">
                  {hit.from_name ?? hit.from_address}
                </span>
              </p>
              {hit.snippet && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  <HighlightedSnippet snippet={hit.snippet} />
                </p>
              )}
            </div>

            <div className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
              {formatRelativeTime(hit.received_at)}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

// Render ts_headline output safely: split on <mark>...</mark> tokens and emit
// React fragments so the surrounding plain text is auto-escaped by React.
// body_text is sanitized server-side but parser-level escaping is cheap and
// blocks any literal `<` characters that slip through.
function HighlightedSnippet({ snippet }: { snippet: string }) {
  const parts = snippet.split(/(<mark>.*?<\/mark>)/g);
  return (
    <>
      {parts.map((part, idx) => {
        const match = part.match(/^<mark>(.*?)<\/mark>$/);
        if (match) {
          return (
            <mark
              key={idx}
              className="bg-amber-200/70 text-foreground rounded px-0.5"
            >
              {match[1]}
            </mark>
          );
        }
        return <Fragment key={idx}>{part}</Fragment>;
      })}
    </>
  );
}

function initial(s: string): string {
  return (s?.[0] ?? "?").toUpperCase();
}
