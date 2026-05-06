"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Loader2, Send } from "lucide-react";

import { microsoft365Api, type EmailMessage } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type ComposeMode =
  | { mode: "new"; defaultTo: string; replyTo?: undefined }
  | { mode: "reply"; replyTo: EmailMessage; defaultTo?: undefined };

type EmailComposeProps = ComposeMode & {
  candidateId: number;
  candidateName: string;
  onClose: () => void;
};

export default function EmailCompose(props: EmailComposeProps) {
  const queryClient = useQueryClient();
  const { candidateId, candidateName, onClose } = props;
  const isReply = props.mode === "reply";

  const [to, setTo] = useState(
    isReply ? props.replyTo.from_address : props.defaultTo,
  );
  const [subject, setSubject] = useState(
    isReply
      ? props.replyTo.subject?.toLowerCase().startsWith("re:")
        ? (props.replyTo.subject ?? "")
        : `Re: ${props.replyTo.subject ?? ""}`
      : `Kontakt — ${candidateName}`,
  );
  const [error, setError] = useState<string | null>(null);

  const editor = useEditor({
    extensions: [StarterKit],
    content: "",
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none min-h-[200px] focus:outline-none border border-border rounded-lg px-3 py-2 bg-card",
      },
    },
  });

  const bodyHtml = useMemo(() => editor?.getHTML() ?? "", [editor]);

  const sendMutation = useMutation({
    mutationFn: async () => {
      const html = editor?.getHTML() ?? "";
      if (!html || html === "<p></p>") {
        throw new Error("Treść wiadomości nie może być pusta.");
      }
      if (isReply) {
        return microsoft365Api
          .reply(candidateId, {
            email_id: props.replyTo.id,
            body_html: html,
          })
          .then((r) => r.data);
      }
      return microsoft365Api
        .compose(candidateId, {
          to: to
            .split(/[,;]/)
            .map((t) => t.trim())
            .filter(Boolean),
          subject,
          body_html: html,
        })
        .then((r) => r.data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["candidate-emails", candidateId],
      });
      onClose();
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "response" in err
            ? (
                (err as { response?: { data?: { detail?: string } } }).response
                  ?.data?.detail ?? "Nie udało się wysłać wiadomości."
              )
            : "Nie udało się wysłać wiadomości.";
      setError(msg);
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isReply ? `Odpowiedz: ${candidateName}` : `Nowy email: ${candidateName}`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {!isReply && (
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                Do
              </label>
              <Input
                value={to}
                onChange={(e) => setTo(e.target.value)}
                placeholder="adres@email.com"
              />
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Temat
            </label>
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              disabled={isReply}
              placeholder="Temat wiadomości"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Treść
            </label>
            <EditorContent editor={editor} />
            <p className="text-xs text-muted-foreground mt-1">
              Wysyłka odbywa się z Twojej skrzynki Microsoft 365.
            </p>
          </div>
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <button
            onClick={onClose}
            disabled={sendMutation.isPending}
            className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            onClick={() => sendMutation.mutate()}
            disabled={sendMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
          >
            {sendMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Wysyłam...
              </>
            ) : (
              <>
                <Send className="h-4 w-4" />
                Wyślij
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
