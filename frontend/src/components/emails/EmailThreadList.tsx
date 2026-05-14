"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, Paperclip, PlusCircle, Sparkles, User } from "lucide-react";

import { microsoft365Api, type EmailThreadPreview } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Checkbox } from "@/components/ui/checkbox";

import EmailCompose from "./EmailCompose";
import EmailThreadView from "./EmailThreadView";
import { EmailBulkActionBar } from "./EmailBulkActionBar";

interface EmailThreadListProps {
  candidateId: number;
  candidateName: string;
  candidateEmail: string | null;
}

export default function EmailThreadList({
  candidateId,
  candidateName,
  candidateEmail,
}: EmailThreadListProps) {
  const [openConversation, setOpenConversation] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["candidate-emails", candidateId],
    queryFn: () =>
      microsoft365Api.listCandidateThreads(candidateId).then((r) => r.data),
    enabled: !!candidateId,
    staleTime: 30_000,
  });

  const threads: EmailThreadPreview[] = data ?? [];

  // Each thread row contributes its `latest.id` to the bulk selection. Acts on
  // the latest message of each selected conversation — paired with the backend
  // `is_archived` filter, archiving the latest also hides the thread when it's
  // the only visible message.
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

      {isLoading && (
        <div className="text-sm text-muted-foreground py-8 text-center">
          Wczytuję wątki...
        </div>
      )}

      {error && (
        <div className="text-sm text-destructive py-4 text-center">
          Błąd ładowania wątków. Sprawdź status integracji w Ustawieniach.
        </div>
      )}

      {!isLoading && !error && threads.length === 0 && (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <Mail className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">
            Brak wątków email z tym kandydatem.
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Wątki pojawią się automatycznie po synchronizacji M365.
          </p>
        </div>
      )}

      {threads.length > 0 && (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-muted/30">
            <Checkbox
              aria-label={allSelected ? "Odznacz wszystkie" : "Zaznacz wszystkie"}
              checked={
                allSelected ? true : someSelected ? "indeterminate" : false
              }
              onCheckedChange={(value) => toggleAll(value === true)}
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
                  <div
                    className="pt-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Checkbox
                      aria-label={`Zaznacz wątek: ${t.subject ?? "(bez tematu)"}`}
                      checked={checked}
                      onCheckedChange={(value) =>
                        toggleOne(t.latest.id, value === true)
                      }
                    />
                  </div>

                  <button
                    type="button"
                    onClick={() => setOpenConversation(t.conversation_id)}
                    className="flex-1 min-w-0 text-left flex items-start gap-3"
                  >
                    <div className="w-9 h-9 rounded-full bg-muted text-muted-foreground flex items-center justify-center text-sm font-medium flex-shrink-0">
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

                    <div className="text-xs text-muted-foreground whitespace-nowrap flex-shrink-0">
                      {formatRelativeTime(t.latest.received_at)}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
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

function initial(s: string): string {
  return (s?.[0] ?? "?").toUpperCase();
}
