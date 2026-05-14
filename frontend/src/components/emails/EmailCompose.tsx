"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { FileText, Loader2, Send } from "lucide-react";

import {
  microsoft365Api,
  userEmailTemplatesApi,
  type EmailMessage,
  type UserEmailTemplate,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type ComposeMode =
  | { mode: "new"; defaultTo: string; replyTo?: undefined }
  | { mode: "reply"; replyTo: EmailMessage; defaultTo?: undefined };

type EmailComposeProps = ComposeMode & {
  candidateId: number;
  candidateName: string;
  /** Optional active recruitment / job context — used when rendering templates. */
  requestId?: number;
  onClose: () => void;
};

type TemplateNotice =
  | { kind: "success"; templateName: string; unresolved: string[] }
  | { kind: "error"; message: string };

export default function EmailCompose(props: EmailComposeProps) {
  const queryClient = useQueryClient();
  const { candidateId, candidateName, requestId, onClose } = props;
  const isReply = props.mode === "reply";

  const [to, setTo] = useState(
    isReply ? props.replyTo.from_address : props.defaultTo,
  );
  const [subject, setSubject] = useState(
    isReply
      ? props.replyTo.subject?.toLowerCase().startsWith("re: ")
        ? (props.replyTo.subject ?? "")
        : `Re: ${props.replyTo.subject ?? ""}`
      : `Kontakt — ${candidateName}`,
  );
  const [error, setError] = useState<string | null>(null);
  const [templateNotice, setTemplateNotice] = useState<TemplateNotice | null>(
    null,
  );

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

  // Templates are loaded lazily — only when the dropdown is opened the first
  // time. `enabled: !isReply` because in reply mode the subject is locked.
  const { data: templates } = useQuery({
    queryKey: ["user-email-templates"],
    queryFn: () => userEmailTemplatesApi.list().then((r) => r.data),
    enabled: !isReply,
    staleTime: 60_000,
  });

  const renderMutation = useMutation({
    mutationFn: async (template: UserEmailTemplate) => {
      const res = await userEmailTemplatesApi.render(template.id, {
        candidate_id: candidateId,
        request_id: requestId,
      });
      return { template, data: res.data };
    },
    onSuccess: ({ template, data }) => {
      if (data.rendered_subject) setSubject(data.rendered_subject);
      if (editor) editor.commands.setContent(data.rendered_body_html || "");
      setTemplateNotice({
        kind: "success",
        templateName: template.name,
        unresolved: data.unresolved_vars,
      });
    },
    onError: (err: unknown) => {
      const msg =
        err instanceof Error
          ? err.message
          : "Nie udało się załadować szablonu.";
      setTemplateNotice({ kind: "error", message: msg });
    },
  });

  // Drop any leftover notice once the user manually edits subject/body so it
  // stops claiming "template loaded" against content they've since rewritten.
  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      if (templateNotice) setTemplateNotice(null);
    };
    editor.on("update", handler);
    return () => {
      editor.off("update", handler);
    };
  }, [editor, templateNotice]);

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

  const templateOptions = useMemo(
    () => templates ?? [],
    [templates],
  );

  const handleTemplateSelect = (value: string) => {
    const tpl = templateOptions.find((t) => String(t.id) === value);
    if (tpl) renderMutation.mutate(tpl);
  };

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

          {!isReply && templateOptions.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                Szablon
              </label>
              <Select
                value=""
                onValueChange={handleTemplateSelect}
                disabled={renderMutation.isPending}
              >
                <SelectTrigger className="w-full">
                  <div className="flex items-center gap-2 text-sm">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <SelectValue placeholder="Wybierz szablon…" />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {templateOptions.map((tpl) => (
                    <SelectItem key={tpl.id} value={String(tpl.id)}>
                      {tpl.name}
                      {tpl.is_shared ? " · współdzielony" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {renderMutation.isPending && (
                <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Ładuję szablon…
                </p>
              )}
            </div>
          )}

          {templateNotice?.kind === "success" && (
            <Alert
              variant={
                templateNotice.unresolved.length > 0 ? "warning" : "success"
              }
              title={`Załadowano szablon: ${templateNotice.templateName}`}
              description={
                templateNotice.unresolved.length > 0
                  ? `Niezastąpione zmienne: ${templateNotice.unresolved.join(", ")}`
                  : undefined
              }
            />
          )}
          {templateNotice?.kind === "error" && (
            <Alert variant="error" title={templateNotice.message} />
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
