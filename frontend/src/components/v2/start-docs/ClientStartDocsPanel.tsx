"use client";

/**
 * Lista „Dokumenty do startu” u klienta (zakładka „Wejście u klienta”).
 * Pusta lista znaczy, że NEXUS o nic nie pyta. Wzory plików leżą w plikach
 * klienta, bo repozytorium jest publiczne.
 */

import { useRef, useState, type ChangeEvent } from "react";
import { FileUp, PencilLine, Plus, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useArchiveClientStartDoc,
  useClientStartDocs,
  useSaveClientStartDoc,
  useUploadStartDocTemplate,
  type ClientStartDoc,
  type ClientStartDocInput,
  type StartDocKind,
} from "@/lib/api/start-documents";
import { offsetText } from "@/lib/start-docs-format";
import { resolveViewState } from "@/lib/view-state";

const KIND_LABEL: Record<StartDocKind, string> = {
  file: "Plik",
  pesel: "PESEL",
  agreement: "Umowa (odhacza się sama)",
};

const EMPTY: ClientStartDocInput = {
  name: "",
  note: null,
  kind: "file",
  required: true,
  offset_days: -2,
  link_url: null,
  fill_from_agreement: false,
};

function EditDialog({
  initial,
  busy,
  onSave,
  onClose,
}: {
  initial: ClientStartDocInput;
  busy: boolean;
  onSave: (input: ClientStartDocInput) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const patch = (change: Partial<ClientStartDocInput>) =>
    setDraft((current) => ({ ...current, ...change }));
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title={initial.name ? `Zmień: ${initial.name}` : "Nowy dokument"}
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          <Button size="sm" disabled={!draft.name.trim() || busy} onClick={() => onSave(draft)}>
            Zapisz
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <FormField label="Nazwa">
          <Input
            aria-label="Nazwa"
            value={draft.name}
            maxLength={200}
            onChange={(event) => patch({ name: event.target.value })}
          />
        </FormField>
        <FormField label="Podpowiedź dla rekrutera i konsultanta">
          <Input
            aria-label="Podpowiedź"
            value={draft.note ?? ""}
            maxLength={300}
            onChange={(event) => patch({ note: event.target.value || null })}
          />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Rodzaj">
            <Select value={draft.kind} onValueChange={(kind) => patch({ kind: kind as StartDocKind })}>
              <SelectTrigger aria-label="Rodzaj">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(KIND_LABEL) as StartDocKind[]).map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {KIND_LABEL[kind]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Termin w dniach roboczych">
            <div className="flex gap-2">
              <Input
                aria-label="Dni robocze"
                type="number"
                min={0}
                max={30}
                value={Math.abs(draft.offset_days)}
                onChange={(event) => {
                  const days = Math.min(30, Math.max(0, Number(event.target.value) || 0));
                  patch({ offset_days: draft.offset_days > 0 ? days : -days });
                }}
              />
              <Select
                value={draft.offset_days > 0 ? "after" : "before"}
                onValueChange={(side) =>
                  patch({
                    offset_days:
                      (side === "after" ? 1 : -1) * Math.max(1, Math.abs(draft.offset_days)),
                  })
                }
              >
                <SelectTrigger aria-label="Przed czy po starcie" className="min-w-[8.5rem]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="before">przed startem</SelectItem>
                  <SelectItem value="after">po starcie</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </FormField>
        </div>
        <FormField label="Link (np. e-KRK)">
          <Input
            aria-label="Link"
            placeholder="https://"
            value={draft.link_url ?? ""}
            maxLength={500}
            onChange={(event) => patch({ link_url: event.target.value || null })}
          />
        </FormField>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.required}
            onCheckedChange={(checked) => patch({ required: checked === true })}
          />
          Wymagany do kompletu
        </label>
        {draft.kind === "file" ? (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={draft.fill_from_agreement}
              onCheckedChange={(checked) => patch({ fill_from_agreement: checked === true })}
            />
            Wstaw do wzoru DOCX dane z umowy (nazwa, NIP, adres, telefon)
          </label>
        ) : null}
      </div>
    </AppModal>
  );
}

export function ClientStartDocsPanel({
  clientId,
  canEdit,
}: {
  clientId: number;
  canEdit: boolean;
}) {
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useClientStartDocs(clientId);
  const save = useSaveClientStartDoc(clientId);
  const archive = useArchiveClientStartDoc(clientId);
  const upload = useUploadStartDocTemplate(clientId);
  const [editing, setEditing] = useState<ClientStartDoc | "new" | null>(null);
  const [templateFor, setTemplateFor] = useState<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-4 text-sm text-muted-foreground">Wczytywanie listy dokumentów…</p>;
  }
  if (state === "forbidden" || state === "not_found") return null;
  if (state === "error" || !query.data) {
    return <QueryStateNotice state="error" onRetry={() => void query.refetch()} />;
  }
  const items = query.data;

  const onTemplate = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || templateFor === null) return;
    try {
      await upload.mutateAsync({ id: templateFor, file });
      showSuccess("Wzór zapisany.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać wzoru."));
    }
  };

  return (
    <section
      aria-label="Dokumenty do startu"
      className="space-y-3 rounded-lg border border-border bg-card p-3"
      data-testid="start-docs-client"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">Dokumenty do startu</h3>
        <span className="text-xs text-muted-foreground">
          Lista dla każdej osoby z tego klienta. Pusta lista: NEXUS o nic nie pyta.
        </span>
        {canEdit ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setEditing("new")}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Dodaj dokument
          </Button>
        ) : null}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".docx,.pdf"
        className="hidden"
        aria-label="Plik wzoru"
        onChange={(event) => void onTemplate(event)}
      />
      {items.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 pr-3 font-semibold">Dokument</th>
                <th className="py-1.5 pr-3 font-semibold">Do kompletu</th>
                <th className="py-1.5 pr-3 font-semibold">Termin</th>
                <th className="py-1.5 pr-3 font-semibold">Wzór</th>
                {canEdit ? <th className="py-1.5" aria-label="Akcje" /> : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="py-2 pr-3">
                    <span className="block font-medium text-foreground">{item.name}</span>
                    {item.note ? (
                      <span className="block text-[11px] text-muted-foreground">{item.note}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3">
                    <Badge variant={item.required ? "info" : "neutral"}>
                      {item.required ? "Wymagany" : "Opcjonalny"}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3 text-muted-foreground">
                    {item.kind === "agreement" ? "Przy podpisie" : offsetText(item.offset_days)}
                  </td>
                  <td className="py-2 pr-3 text-muted-foreground">
                    {item.kind === "file" ? (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span>{item.template_name ?? "Brak"}</span>
                        {canEdit ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            onClick={() => {
                              setTemplateFor(item.id);
                              fileInput.current?.click();
                            }}
                          >
                            <FileUp className="h-3 w-3" aria-hidden />
                            {item.template_name ? "Podmień" : "Dodaj"}
                          </Button>
                        ) : null}
                      </div>
                    ) : (
                      "Nie dotyczy"
                    )}
                  </td>
                  {canEdit ? (
                    <td className="whitespace-nowrap py-2 text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Zmień: ${item.name}`}
                        onClick={() => setEditing(item)}
                      >
                        <PencilLine className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Usuń: ${item.name}`}
                        onClick={async () => {
                          const ok = await askConfirm({
                            title: `Usunąć „${item.name}” z listy?`,
                            description:
                              "Pozycja zniknie z list wszystkich osób tego klienta. Pliki, które ktoś już dodał, zostają.",
                            confirmLabel: "Usuń",
                          });
                          if (!ok) return;
                          try {
                            await archive.mutateAsync(item.id);
                          } catch (error) {
                            showError(apiErrorMessage(error, "Nie udało się usunąć pozycji."));
                          }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="py-2 text-sm text-muted-foreground">Ten klient nie ma jeszcze listy.</p>
      )}
      {editing ? (
        <EditDialog
          initial={editing === "new" ? EMPTY : editing}
          busy={save.isPending}
          onClose={() => setEditing(null)}
          onSave={async (input) => {
            try {
              await save.mutateAsync({ id: editing === "new" ? null : editing.id, input });
              setEditing(null);
            } catch (error) {
              showError(apiErrorMessage(error, "Nie udało się zapisać pozycji."));
            }
          }}
        />
      ) : null}
      {confirmDialog}
    </section>
  );
}
