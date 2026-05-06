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
        <DialogHeader className="p-5 border-b border-border">
          <DialogTitle className="text-base font-semibold">
            {thread?.subject ?? "(bez tematu)"}
          </DialogTitle>
          {latest && (
            <div className="text-xs text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>
                <span className="text-muted-foreground">Od:</span>{" "}
                <span className="font-medium text-foreground">
                  {latest.from_name
                    ? `${latest.from_name} <${latest.from_address}>`
                    : latest.from_address}
                </span>
              </span>
              <span>·</span>
              <span>{formatRelativeTime(latest.received_at)}</span>
              {latest.direction === "sent" && (
                <span className="rounded bg-primary/15 text-primary px-1.5 py-0.5">
                  Wysłane z ATS
                </span>
              )}
              {latest.is_private_filtered && (
                <span className="rounded bg-muted text-muted-foreground px-1.5 py-0.5">
                  Prywatne (ATS:ignore)
                </span>
              )}
            </div>
          )}
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {!latest ? (
            <p className="text-sm text-muted-foreground">Wczytuję wiadomość...</p>
          ) : (
            <>
              {latest.is_private_filtered ? (
                <div className="rounded-lg border border-border bg-muted px-4 py-6 text-sm text-muted-foreground text-center">
                  Ta wiadomość jest oznaczona kategorią <code>ATS:ignore</code> w
                  Outlooku — treść nie jest pobierana do Nexusa.
                </div>
              ) : bodyHtml ? (
                <div
                  className="prose prose-sm max-w-none text-foreground"
                  // eslint-disable-next-line react/no-danger -- sanitized via DOMPurify + server-side bleach
                  dangerouslySetInnerHTML={{ __html: bodyHtml }}
                />
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-foreground font-sans">
                  {fullMessage?.body_text ?? latest.body_text ?? ""}
                </pre>
              )}

              {!!fullMessage?.attachments?.length && (
                <div className="pt-3 border-t border-border">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
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
                        className="inline-flex items-center gap-2 text-sm px-3 py-1.5 bg-muted border border-border rounded-lg hover:bg-muted"
                        download
                      >
                        <Paperclip className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="truncate max-w-[20rem]">{a.filename}</span>
                        <Download className="h-3.5 w-3.5 text-muted-foreground" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="border-t border-border p-4 flex items-center justify-between">
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
            Zamknij
          </button>
          {latest && (
            <button
              onClick={() => setReplyTarget(latest)}
              className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg"
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
