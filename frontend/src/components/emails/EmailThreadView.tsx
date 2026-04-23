"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { Download, Paperclip, Reply, X } from "lucide-react";

import { microsoft365Api, type EmailMessage, type EmailThreadPreview } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatRelativeTime } from "@/lib/utils";

import EmailCompose from "./EmailCompose";

interface EmailThreadViewProps {
  candidateId: number;
  conversationId: string;
  onClose: () => void;
}

export default function EmailThreadView({
  candidateId,
  conversationId,
  onClose,
}: EmailThreadViewProps) {
  const [replyTarget, setReplyTarget] = useState<EmailMessage | null>(null);

  // Reuse the thread list query — cheap and guarantees we have the "latest"
  // in-thread reference for Reply. If the user landed here from a stale cache
  // the thread list query refreshes on focus.
  const { data: threads } = useQuery({
    queryKey: ["candidate-emails", candidateId],
    queryFn: () =>
      microsoft365Api.listCandidateThreads(candidateId).then((r) => r.data),
    staleTime: 30_000,
  });

  const thread: EmailThreadPreview | undefined = useMemo(
    () => threads?.find((t) => t.conversation_id === conversationId),
    [threads, conversationId],
  );

  // Phase 1 simplification: show only the latest message with its full body.
  // Previous messages in the thread could be loaded individually via getEmail
  // but the most-recent is the primary read. Expandable history = Phase 2.
  const latest = thread?.latest;
  const { data: fullMessage } = useQuery({
    queryKey: ["email", latest?.id],
    queryFn: () => microsoft365Api.getEmail(latest!.id).then((r) => r.data),
    enabled: !!latest?.id,
  });

  const bodyHtml = useMemo(() => {
    const raw = fullMessage?.body_html ?? latest?.body_html ?? "";
    if (!raw) return "";
    return DOMPurify.sanitize(raw, {
      ADD_ATTR: ["target"],
      FORBID_TAGS: ["style", "script"],
    });
  }, [fullMessage?.body_html, latest?.body_html]);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col p-0">
        <DialogHeader className="p-5 border-b border-gray-200">
          <DialogTitle className="text-base font-semibold">
            {thread?.subject ?? "(bez tematu)"}
          </DialogTitle>
          {latest && (
            <div className="text-xs text-gray-500 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>
                <span className="text-gray-400">Od:</span>{" "}
                <span className="font-medium text-gray-700">
                  {latest.from_name
                    ? `${latest.from_name} <${latest.from_address}>`
                    : latest.from_address}
                </span>
              </span>
              <span>·</span>
              <span>{formatRelativeTime(latest.received_at)}</span>
              {latest.direction === "sent" && (
                <span className="rounded bg-blue-100 text-blue-700 px-1.5 py-0.5">
                  Wysłane z ATS
                </span>
              )}
              {latest.is_private_filtered && (
                <span className="rounded bg-gray-200 text-gray-600 px-1.5 py-0.5">
                  Prywatne (ATS:ignore)
                </span>
              )}
            </div>
          )}
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {!latest ? (
            <p className="text-sm text-gray-500">Wczytuję wiadomość...</p>
          ) : (
            <>
              {latest.is_private_filtered ? (
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500 text-center">
                  Ta wiadomość jest oznaczona kategorią <code>ATS:ignore</code> w
                  Outlooku — treść nie jest pobierana do Nexusa.
                </div>
              ) : bodyHtml ? (
                <div
                  className="prose prose-sm max-w-none text-gray-800"
                  // eslint-disable-next-line react/no-danger -- sanitized via DOMPurify + server-side bleach
                  dangerouslySetInnerHTML={{ __html: bodyHtml }}
                />
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans">
                  {fullMessage?.body_text ?? latest.body_text ?? ""}
                </pre>
              )}

              {!!fullMessage?.attachments?.length && (
                <div className="pt-3 border-t border-gray-100">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                    Załączniki
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {fullMessage.attachments.map((a) => (
                      <a
                        key={a.id}
                        href={microsoft365Api.downloadAttachmentUrl(
                          fullMessage.id,
                          a.id,
                        )}
                        className="inline-flex items-center gap-2 text-sm px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100"
                        download
                      >
                        <Paperclip className="h-3.5 w-3.5 text-gray-400" />
                        <span className="truncate max-w-[20rem]">{a.filename}</span>
                        <Download className="h-3.5 w-3.5 text-gray-400" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="border-t border-gray-200 p-4 flex items-center justify-between">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-800"
          >
            <X className="h-4 w-4" />
            Zamknij
          </button>
          {latest && (
            <button
              onClick={() => setReplyTarget(latest)}
              className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
            >
              <Reply className="h-4 w-4" />
              Odpowiedz
            </button>
          )}
        </div>
      </DialogContent>

      {replyTarget && (
        <EmailCompose
          mode="reply"
          candidateId={candidateId}
          candidateName={replyTarget.from_name ?? replyTarget.from_address}
          replyTo={replyTarget}
          onClose={() => setReplyTarget(null)}
        />
      )}
    </Dialog>
  );
}
