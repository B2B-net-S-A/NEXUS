"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  FileText,
  Loader2,
  Pencil,
  Plus,
  Share2,
  Trash2,
  Users,
} from "lucide-react";

import {
  userEmailTemplatesApi,
  type UserEmailTemplate,
  type UserEmailTemplateInput,
} from "@/lib/api";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn, formatRelativeTime } from "@/lib/utils";

// Variable chips offered as quick-insert helpers in the editor. Keep in sync
// with the render context shape in app/api/user_email_templates.py.
const AVAILABLE_VARS = [
  { group: "Kandydat", token: "{{ candidate.first_name }}" },
  { group: "Kandydat", token: "{{ candidate.last_name }}" },
  { group: "Kandydat", token: "{{ candidate.full_name }}" },
  { group: "Kandydat", token: "{{ candidate.email }}" },
  { group: "Kandydat", token: "{{ candidate.phone }}" },
  { group: "Rekrutacja", token: "{{ request.role_name }}" },
  { group: "Rekrutacja", token: "{{ request.client_name }}" },
  { group: "Rekrutacja", token: "{{ request.location }}" },
  { group: "Ja", token: "{{ user.name }}" },
  { group: "Ja", token: "{{ user.email }}" },
  { group: "Data", token: "{{ today }}" },
] as const;

interface DraftState {
  name: string;
  subject: string;
  body_html: string;
  is_shared: boolean;
}

const EMPTY_DRAFT: DraftState = {
  name: "",
  subject: "",
  body_html: "",
  is_shared: false,
};

export default function EmailTemplatesCard() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<UserEmailTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["user-email-templates"],
    queryFn: () => userEmailTemplatesApi.list().then((r) => r.data),
    staleTime: 30_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      userEmailTemplatesApi.delete(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-email-templates"] });
    },
    onError: (err: unknown) => {
      setError(
        err instanceof Error ? err.message : "Nie udało się usunąć szablonu.",
      );
    },
  });

  const onSaved = () => {
    queryClient.invalidateQueries({ queryKey: ["user-email-templates"] });
    setEditing(null);
    setCreating(false);
  };

  const templates = data ?? [];

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
          <FileText className="w-6 h-6 text-primary" />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-bold text-foreground dark:text-foreground">
            Szablony emaili (Microsoft 365)
          </h3>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            Twoje prywatne snippety dla okna nowej wiadomości w skrzynce M365.
            Możesz udostępnić szablon całemu zespołowi.
          </p>
        </div>
        <Button
          onClick={() => {
            setError(null);
            setCreating(true);
          }}
          size="sm"
          className="flex-shrink-0"
        >
          <Plus className="h-4 w-4" />
          Nowy szablon
        </Button>
      </div>

      {error && (
        <div className="mb-4">
          <Alert variant="error" title={error} />
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Ładowanie szablonów…
        </div>
      ) : templates.length === 0 ? (
        <div className="text-center py-8 text-sm text-muted-foreground">
          Brak szablonów. Stwórz pierwszy żeby pojawił się w oknie nowej wiadomości
          obok pola Temat.
        </div>
      ) : (
        <ul className="divide-y divide-border dark:divide-border">
          {templates.map((t) => (
            <li
              key={t.id}
              className="flex items-center gap-3 py-3"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground truncate">
                    {t.name}
                  </span>
                  {t.is_shared && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-primary/10 text-primary flex items-center gap-1">
                      <Users className="h-3 w-3" />
                      Współdzielony
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground truncate mt-0.5">
                  {t.subject ?? "–"} · aktualizacja {formatRelativeTime(t.updated_at)}
                </p>
              </div>
              <button
                onClick={() => {
                  setError(null);
                  setEditing(t);
                }}
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                aria-label="Edytuj"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                onClick={() => {
                  if (window.confirm(`Usunąć szablon „${t.name}"?`)) {
                    setError(null);
                    deleteMutation.mutate(t.id);
                  }
                }}
                disabled={deleteMutation.isPending}
                className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-50"
                aria-label="Usuń"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {(creating || editing) && (
        <TemplateEditor
          initial={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={onSaved}
          onError={(msg) => setError(msg)}
        />
      )}
    </div>
  );
}

interface EditorProps {
  initial: UserEmailTemplate | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}

function TemplateEditor({ initial, onClose, onSaved, onError }: EditorProps) {
  const isEdit = initial !== null;

  const [draft, setDraft] = useState<DraftState>(() =>
    initial
      ? {
          name: initial.name,
          subject: initial.subject ?? "",
          body_html: initial.body_html,
          is_shared: initial.is_shared,
        }
      : EMPTY_DRAFT,
  );

  const editor = useEditor({
    extensions: [StarterKit],
    content: draft.body_html,
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none min-h-[240px] focus:outline-none border border-border rounded-lg px-3 py-2 bg-card",
      },
    },
    onUpdate: ({ editor: ed }) => {
      setDraft((prev) => ({ ...prev, body_html: ed.getHTML() }));
    },
  });

  // Re-seed the editor when `initial` changes (open editor for another row).
  useEffect(() => {
    if (!editor) return;
    const next = initial?.body_html ?? "";
    if (editor.getHTML() !== next) editor.commands.setContent(next);
  }, [editor, initial]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload: UserEmailTemplateInput = {
        name: draft.name.trim(),
        subject: draft.subject.trim() || null,
        body_html: draft.body_html,
        is_shared: draft.is_shared,
      };
      if (isEdit && initial) {
        return userEmailTemplatesApi.update(initial.id, payload).then((r) => r.data);
      }
      return userEmailTemplatesApi.create(payload).then((r) => r.data);
    },
    onSuccess: () => onSaved(),
    onError: (err: unknown) => {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "response" in err
            ? (
                (err as { response?: { data?: { detail?: string } } }).response
                  ?.data?.detail ?? "Nie udało się zapisać szablonu."
              )
            : "Nie udało się zapisać szablonu.";
      onError(msg);
    },
  });

  const insertVariable = (token: string) => {
    if (!editor) return;
    editor.chain().focus().insertContent(token).run();
  };

  const groupedVars = useMemo(() => {
    const groups: Record<string, string[]> = {};
    for (const v of AVAILABLE_VARS) {
      (groups[v.group] ??= []).push(v.token);
    }
    return groups;
  }, []);

  const canSave =
    draft.name.trim().length > 0 &&
    draft.body_html.replace(/<\/?[^>]+>/g, "").trim().length > 0 &&
    !saveMutation.isPending;

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>
            {isEdit ? `Edytuj: ${initial?.name}` : "Nowy szablon"}
          </SheetTitle>
        </SheetHeader>
        <SheetBody className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Nazwa
            </label>
            <Input
              value={draft.name}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, name: e.target.value }))
              }
              maxLength={120}
              placeholder="np. Outreach intro"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Temat (opcjonalny)
            </label>
            <Input
              value={draft.subject}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, subject: e.target.value }))
              }
              placeholder="np. Cześć {{ candidate.first_name }}"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Treść
            </label>
            <EditorContent editor={editor} />
            <p className="text-xs text-muted-foreground mt-1">
              Składnia: Jinja2. Zmienne wstawiaj poniższymi przyciskami albo
              ręcznie z podwójnym nawiasem (np. <code>{"{{ candidate.first_name }}"}</code>).
            </p>
          </div>

          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              Dostępne zmienne
            </p>
            <div className="space-y-2">
              {Object.entries(groupedVars).map(([group, tokens]) => (
                <div key={group} className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted-foreground w-20">
                    {group}:
                  </span>
                  {tokens.map((token) => (
                    <button
                      key={token}
                      type="button"
                      onClick={() => insertVariable(token)}
                      className="text-xs px-2 py-1 rounded-md bg-muted hover:bg-primary/10 text-muted-foreground hover:text-primary font-mono"
                    >
                      {token}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <label
            className={cn(
              "flex items-start gap-3 p-3 rounded-xl border border-border dark:border-border cursor-pointer",
              draft.is_shared && "bg-primary/5 border-primary/30",
            )}
          >
            <input
              type="checkbox"
              checked={draft.is_shared}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, is_shared: e.target.checked }))
              }
              className="mt-1"
            />
            <div className="flex-1">
              <p className="text-sm font-medium text-foreground flex items-center gap-2">
                <Share2 className="h-3.5 w-3.5" />
                Udostępnij zespołowi
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Pozostali użytkownicy zobaczą ten szablon na liście wyboru w oknie
                nowej wiadomości. Edytować i usuwać może tylko właściciel.
              </p>
            </div>
          </label>
        </SheetBody>
        <SheetFooter>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={saveMutation.isPending}
          >
            Anuluj
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!canSave}
          >
            {saveMutation.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            {isEdit ? "Zapisz" : "Utwórz szablon"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
