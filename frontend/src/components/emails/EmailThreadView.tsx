"use client";

import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  Paperclip,
  Reply,
  X,
} from "lucide-react";

import {
  microsoft365Api,
  type EmailAttachmentPreview,
  type EmailMessage,
} from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert } from "@/components/ui/alert";
import { useToast } from "@/components/Toast";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  buildThreadTree,
  flattenThread,
  MAX_DEPTH,
} from "@/lib/email-threading";

import { planThreadReply, type ReplyPlan } from "@/lib/email-reply-target";
import EmailCompose from "./EmailCompose";

interface EmailThreadViewProps {
  candidateId: number;
  /** Adres kandydata — „Odpowiedz” celuje wyłącznie w jego maile. */
  candidateEmail?: string | null;
  conversationId: string;
  onClose: () => void;
}

/**
 * Stan wysyłki z NEXUSA (audyt 22.09 r2, FIX-07). ``pending`` = wysyłka
 * w toku, ``uncertain`` = Microsoft 365 nie potwierdził wysyłki i nie wiadomo,
 * czy mail wyszedł. Bez tej plakietki wiersz wyglądał jak zwykły wysłany
 * mail, a ponowienie kończyło się niezrozumiałym 409.
 */
export function SendStateBadge({
  state,
}: {
  state: EmailMessage["send_state"];
}) {
  if (state === "pending") {
    return (
      <span className="rounded bg-muted text-muted-foreground text-[10px] px-1.5 py-0.5">
        Wysyłanie…
      </span>
    );
  }
  if (state === "uncertain") {
    return (
      <span
        className="rounded bg-destructive/15 text-destructive text-[10px] px-1.5 py-0.5"
        title="Microsoft 365 nie potwierdził wysyłki. Sprawdź folder Wysłane w Outlooku, zanim wyślesz ponownie."
      >
        Nie wiadomo, czy wyszło — sprawdź Wysłane
      </span>
    );
  }
  return null;
}

function initialsOf(name: string | null | undefined, fallback: string): string {
  const source = (name && name.trim()) || fallback;
  const parts = source.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Two-tone soft palette deterministic by from_address — same sender keeps
// the same color across cards so the eye can scan the thread quickly.
const AVATAR_TONES = [
  "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
  "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
];

function avatarToneFor(address: string): string {
  let hash = 0;
  for (let i = 0; i < address.length; i++) {
    hash = (hash * 31 + address.charCodeAt(i)) >>> 0;
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length];
}

interface ThreadMessageCardProps {
  email: EmailMessage;
  depth: number;
  initiallyExpanded: boolean;
  onReply: (email: EmailMessage) => void;
}

function ThreadMessageCard({
  email,
  depth,
  initiallyExpanded,
  onReply,
}: ThreadMessageCardProps) {
  const [expanded, setExpanded] = useState(initiallyExpanded);
  const { showError } = useToast();
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  // Only fetch the full body once the card is expanded — keeps the initial
  // open of a long thread cheap.
  const { data: fullMessage } = useQuery({
    queryKey: ["email", email.id],
    queryFn: () => microsoft365Api.getEmail(email.id).then((r) => r.data),
    enabled: expanded,
    staleTime: 60_000,
  });

  const bodyHtml = useMemo(() => {
    const raw = fullMessage?.body_html ?? email.body_html ?? "";
    if (!raw) return "";
    return DOMPurify.sanitize(raw, {
      ADD_ATTR: ["target"],
      FORBID_TAGS: ["style", "script"],
    });
  }, [fullMessage?.body_html, email.body_html]);

  const senderLabel = email.from_name
    ? `${email.from_name} <${email.from_address}>`
    : email.from_address;
  const initials = initialsOf(email.from_name, email.from_address);
  const tone = avatarToneFor(email.from_address);

  // Download via authenticated fetch → same-origin blob. A raw <a href> to the
  // backend 401s: the JWT lives in localStorage (not a cookie), so a plain
  // navigation/download sends no Authorization header.
  const handleDownloadAttachment = async (att: EmailAttachmentPreview) => {
    if (!fullMessage) return;
    setDownloadingId(att.id);
    try {
      await downloadAuthenticatedFile(
        `/api/emails/${fullMessage.id}/attachments/${att.id}/download`,
        att.filename,
      );
    } catch {
      showError("Nie udało się pobrać załącznika.");
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div
      // Wcięcie przez zmienne CSS — Tailwind nie generuje klasy na każdą
      // głębokość. Od `sm` 24 px na poziom (limit MAX_DEPTH → max 480 px);
      // na telefonie 8 px i najwyżej 6 poziomów, inaczej głęboka odpowiedź
      // zostawiała treści ~100 px szerokości.
      style={
        {
          "--thread-depth": depth,
          "--thread-depth-narrow": Math.min(depth, 6),
        } as CSSProperties
      }
      className="pl-[calc(var(--thread-depth-narrow)*0.5rem)] sm:pl-[calc(var(--thread-depth)*1.5rem)]"
    >
      <div
        className={cn(
          "rounded-lg border bg-card",
          depth > 0 && "border-l-2 border-l-border/60",
        )}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-start gap-3 px-3 py-2 text-left hover:bg-muted/50 rounded-t-lg"
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 mt-1 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 mt-1 text-muted-foreground shrink-0" />
          )}
          <div
            className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0",
              tone,
            )}
            aria-hidden
          >
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium text-foreground truncate">
                {email.from_name ?? email.from_address}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatRelativeTime(email.received_at)}
              </span>
              {email.direction === "sent" && (
                <span className="rounded bg-primary/15 text-primary text-[10px] px-1.5 py-0.5">
                  Wysłane z ATS
                </span>
              )}
              <SendStateBadge state={email.send_state} />
              {email.is_private_filtered && (
                <span className="rounded bg-muted text-muted-foreground text-[10px] px-1.5 py-0.5">
                  Prywatne
                </span>
              )}
              {!email.is_read && email.direction !== "sent" && (
                <span className="rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200 text-[10px] px-1.5 py-0.5">
                  Nieprzeczytane
                </span>
              )}
            </div>
            {!expanded && (
              <p className="text-xs text-muted-foreground truncate mt-0.5">
                {email.body_preview ?? ""}
              </p>
            )}
          </div>
        </button>

        {expanded && (
          <div className="border-t border-border px-4 py-3 space-y-3">
            <div className="text-xs text-muted-foreground">
              <span>Od:</span>{" "}
              <span className="text-foreground">{senderLabel}</span>
            </div>

            {email.is_private_filtered ? (
              <Alert
                variant="warning"
                description="Ta wiadomość jest oznaczona kategorią ATS:ignore w Outlooku — treść nie jest pobierana do Nexusa."
              />
            ) : bodyHtml ? (
              <div
                // Maile HTML (newslettery) niosą tabele i obrazy o stałej
                // szerokości — bez limitu rozpychały cały panel na telefonie.
                // `contain: paint` + `isolation`: mail od kandydata z
                // `position: fixed` na cały ekran nie przykryje aplikacji
                // podrobionym komunikatem — zostaje w ramce wiadomości
                // (audyt bezpieczeństwa 24.09.2026).
                className="prose prose-sm relative isolate max-w-none break-words text-foreground [contain:paint] [&_img]:h-auto [&_img]:max-w-full [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto"
                dangerouslySetInnerHTML={{ __html: bodyHtml }}
              />
            ) : fullMessage?.body_text || email.body_text ? (
              <pre className="whitespace-pre-wrap text-sm text-foreground font-sans">
                {fullMessage?.body_text ?? email.body_text ?? ""}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground">Wczytuję wiadomość...</p>
            )}

            {!!fullMessage?.attachments?.length && (
              <div className="pt-2 border-t border-border">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                  Załączniki
                </p>
                <div className="flex flex-wrap gap-2">
                  {fullMessage.attachments.map((a) => {
                    const isDownloading = downloadingId === a.id;
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => handleDownloadAttachment(a)}
                        disabled={isDownloading}
                        className="inline-flex min-w-0 max-w-full items-center gap-2 text-sm px-3 py-1.5 bg-muted border border-border rounded-lg hover:bg-muted/80 disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 truncate max-w-[20rem]">
                          {a.filename}
                        </span>
                        {isDownloading ? (
                          <Loader2 className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
                        ) : (
                          <Download className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="pt-2 flex justify-end">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onReply(email);
                }}
                className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 bg-primary hover:bg-primary/90 text-white rounded-md"
              >
                <Reply className="h-3.5 w-3.5" />
                Odpowiedz
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function EmailThreadView({
  candidateId,
  candidateEmail = null,
  conversationId,
  onClose,
}: EmailThreadViewProps) {
  const [replyPlan, setReplyPlan] = useState<ReplyPlan>(null);

  const {
    data: messages,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["email-thread", candidateId, conversationId],
    queryFn: () =>
      microsoft365Api
        .listThreadMessages(candidateId, conversationId)
        .then((r) => r.data),
    staleTime: 30_000,
  });

  const flatNodes = useMemo(() => {
    if (!messages || messages.length === 0) return [];
    return flattenThread(buildThreadTree(messages));
  }, [messages]);

  const subject = isLoading
    ? "Wątek email"
    : (messages?.[messages.length - 1]?.subject ?? "(bez tematu)");
  const latestId = flatNodes[flatNodes.length - 1]?.email.id ?? null;

  const messageCount = messages?.length ?? 0;
  const unreadCount = useMemo(
    () => (messages ?? []).filter((m) => !m.is_read && m.direction !== "sent").length,
    [messages],
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90dvh] flex flex-col p-0">
        <DialogHeader className="p-5 border-b border-border">
          <DialogTitle className="text-base font-semibold">{subject}</DialogTitle>
          <div className="text-xs text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {messageCount} {messageCount === 1 ? "wiadomość" : "wiadomości"}
            </span>
            {unreadCount > 0 && (
              <>
                <span>·</span>
                <span className="text-amber-700 dark:text-amber-300">
                  {unreadCount} nieprzeczytane
                </span>
              </>
            )}
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Wczytuję wątek...</p>
          ) : isError ? (
            <div className="space-y-2">
              <Alert
                variant="error"
                description="Nie udało się wczytać wątku."
              />
              <button
                type="button"
                onClick={() => void refetch()}
                className="text-sm font-medium text-primary hover:text-primary/80"
              >
                Ponów
              </button>
            </div>
          ) : flatNodes.length === 0 ? (
            <Alert
              variant="info"
              description="Ten wątek nie ma wiadomości przypisanych do tego kandydata albo nie masz do nich dostępu."
            />
          ) : (
            flatNodes.map((node) => (
              <ThreadMessageCard
                key={node.email.id}
                email={node.email}
                depth={Math.min(node.depth, MAX_DEPTH)}
                initiallyExpanded={node.email.id === latestId}
                onReply={(e) => setReplyPlan(planThreadReply(messages ?? [], e, candidateEmail))}
              />
            ))
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
          {latestId !== null && messages && messages.length > 0 && (
            <button
              onClick={() => setReplyPlan(planThreadReply(messages, undefined, candidateEmail))}
              className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 bg-primary hover:bg-primary/90 text-white rounded-lg"
            >
              <Reply className="h-4 w-4" />
              Odpowiedz
            </button>
          )}
        </div>
      </DialogContent>

      {replyPlan?.mode === "reply" && (
        <EmailCompose
          mode="reply"
          candidateId={candidateId}
          candidateName={replyPlan.replyTo.from_name ?? replyPlan.replyTo.from_address}
          replyTo={replyPlan.replyTo}
          onClose={() => setReplyPlan(null)}
        />
      )}
      {replyPlan?.mode === "new" && (
        <EmailCompose
          mode="new"
          candidateId={candidateId}
          candidateName={replyPlan.defaultTo}
          defaultTo={replyPlan.defaultTo}
          onClose={() => setReplyPlan(null)}
        />
      )}
    </Dialog>
  );
}
