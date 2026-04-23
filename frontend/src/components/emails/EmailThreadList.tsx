"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, Paperclip, PlusCircle, Sparkles, User } from "lucide-react";

import { microsoft365Api, type EmailThreadPreview } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";

import EmailCompose from "./EmailCompose";
import EmailThreadView from "./EmailThreadView";

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

  const { data, isLoading, error } = useQuery({
    queryKey: ["candidate-emails", candidateId],
    queryFn: () =>
      microsoft365Api.listCandidateThreads(candidateId).then((r) => r.data),
    enabled: !!candidateId,
    staleTime: 30_000,
  });

  const threads: EmailThreadPreview[] = data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[hsl(var(--text-title))]">
          Wątki email
        </h3>
        <button
          onClick={() => setComposeOpen(true)}
          disabled={!candidateEmail}
          title={
            candidateEmail
              ? "Napisz nowy email do kandydata"
              : "Kandydat nie ma adresu email"
          }
          className="flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <PlusCircle className="h-4 w-4" />
          Nowy email
        </button>
      </div>

      {isLoading && (
        <div className="text-sm text-gray-500 py-8 text-center">
          Wczytuję wątki...
        </div>
      )}

      {error && (
        <div className="text-sm text-red-600 py-4 text-center">
          Błąd ładowania wątków. Sprawdź status integracji w Ustawieniach.
        </div>
      )}

      {!isLoading && !error && threads.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-200 p-8 text-center">
          <Mail className="h-8 w-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">
            Brak wątków email z tym kandydatem.
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Wątki pojawią się automatycznie po synchronizacji M365.
          </p>
        </div>
      )}

      <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
        {threads.map((t) => (
          <li key={t.conversation_id}>
            <button
              onClick={() => setOpenConversation(t.conversation_id)}
              className={cn(
                "w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition",
                t.unread_count > 0 && "bg-blue-50/40",
              )}
            >
              <div className="w-9 h-9 rounded-full bg-gray-100 text-gray-500 flex items-center justify-center text-sm font-medium flex-shrink-0">
                {initial(t.latest.from_name ?? t.latest.from_address)}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p
                    className={cn(
                      "text-sm truncate",
                      t.unread_count > 0
                        ? "font-semibold text-gray-900"
                        : "font-medium text-gray-700",
                    )}
                  >
                    {t.subject || "(bez tematu)"}
                  </p>
                  {t.message_count > 1 && (
                    <span className="text-xs text-gray-400">
                      {t.message_count}
                    </span>
                  )}
                  {t.latest.has_attachments && (
                    <Paperclip className="h-3.5 w-3.5 text-gray-400" />
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
                <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5">
                  <User className="h-3 w-3" />
                  <span className="truncate">
                    {t.latest.from_name ?? t.latest.from_address}
                  </span>
                </p>
                <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                  {t.latest.body_preview ?? ""}
                </p>
              </div>

              <div className="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
                {formatRelativeTime(t.latest.received_at)}
              </div>
            </button>
          </li>
        ))}
      </ul>

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
