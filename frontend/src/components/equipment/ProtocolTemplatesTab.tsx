"use client";

import { useState } from "react";
import { Download, Upload } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadProtocolTemplate,
  downloadStandardTemplate,
  useProtocolTemplates,
  useUpdateProtocolTemplate,
  useUploadProtocolTemplate,
  type ProtocolTemplate,
  type ProtocolTemplateField,
} from "@/lib/api/client-onboarding";
import type { ProtocolKind } from "@/lib/api/equipment";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

const KIND_LABELS: Record<ProtocolKind, string> = { wydanie: "Wydanie", zwrot: "Zwrot" };

/** Sprawdzenie pliku przed wysłaniem — serwer sprawdza to samo i więcej. */
export function fileProblem(file: File | null, maxBytes: number): string | null {
  if (!file) return "Wybierz plik Word (.docx) ze wzorem.";
  if (!file.name.toLowerCase().endsWith(".docx")) return "Wgraj plik Word w formacie .docx.";
  if (file.size === 0 || file.size > maxBytes) {
    return `Plik jest pusty albo większy niż ${Math.round(maxBytes / 1024 / 1024)} MB.`;
  }
  return null;
}

function UploadDialog({ maxBytes, onClose }: { maxBytes: number; onClose: () => void }) {
  const { showToast } = useToast();
  const upload = useUploadProtocolTemplate();
  const [kind, setKind] = useState<ProtocolKind>("wydanie");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const problem = fileProblem(file, maxBytes) ?? (name.trim() ? null : "Nazwij wzór.");
    if (problem || !file) {
      setError(problem);
      return;
    }
    setError(null);
    upload.mutate(
      { file, kind, name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: () => {
          showToast("Wzór dodany", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać wzoru.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Dodaj wzór protokołu"
      description="Plik Word z polami {{ … }} — te same pola co w standardzie. NEXUS sprawdzi plik i wypełni go próbnie, zanim go zapisze."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={upload.isPending}>
            {upload.isPending ? "Sprawdzanie…" : "Dodaj wzór"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Rodzaj" htmlFor="tpl-kind">
          <Select value={kind} onValueChange={(value) => setKind(value as ProtocolKind)}>
            <SelectTrigger id="tpl-kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="wydanie">Protokół wydania</SelectItem>
              <SelectItem value="zwrot">Protokół zwrotu</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Nazwa" htmlFor="tpl-name" required>
          <Input
            id="tpl-name"
            maxLength={120}
            placeholder="np. Standard z kaucją"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField label="Opis" htmlFor="tpl-description" className="sm:col-span-2">
          <Input
            id="tpl-description"
            maxLength={300}
            placeholder="np. zwrot do naszego biura, kaucja według umowy"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
        <FormField label="Plik .docx" htmlFor="tpl-file" className="sm:col-span-2" required>
          <Input
            id="tpl-file"
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

function FieldsHelp({ fields, required }: { fields: ProtocolTemplateField[]; required: Record<ProtocolKind, string[]> }) {
  return (
    <details className="rounded-lg border border-border bg-card p-3 text-sm">
      <summary className="cursor-pointer font-medium">Pola, które wypełnia protokół</summary>
      <p className="mt-2 text-xs text-muted-foreground">
        Wymagane: {required.wydanie.join(", ")}. Tabela pozycji to wiersz z{" "}
        <code>{"{%tr for line in lines %}"}</code>, pola wiersza (<code>{"{{ line.name }}"}</code>…) i wiersz z{" "}
        <code>{"{%tr endfor %}"}</code> — najprościej zacząć od pobranego standardu.
      </p>
      <dl className="mt-2 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
        {fields.map((field) => (
          <div key={field.field} className="contents">
            <dt className="font-mono text-foreground">{`{{ ${field.field} }}`}</dt>
            <dd className="text-muted-foreground">{field.label}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/**
 * „Sprzęt → Wzory protokołów” (etap 3, O3): wzory wgrane przez recepcję.
 * Wybór wzoru dla klienta jest w pakiecie klienta („Wejście u klienta”).
 */
export function ProtocolTemplatesTab() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useProtocolTemplates();
  const update = useUpdateProtocolTemplate();
  const [uploading, setUploading] = useState(false);
  const rows = query.data?.items ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });

  const download = (action: () => Promise<void>) =>
    void action().catch((err: unknown) =>
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"),
    );

  const toggle = async (template: ProtocolTemplate) => {
    if (template.is_active) {
      const ok = await askConfirm({
        title: `Wycofać wzór „${template.name}”?`,
        description:
          "Nowe protokoły nie powstaną z tego wzoru. Protokoły, które już z niego powstały, dalej się z niego pobierają.",
        confirmLabel: "Wycofaj",
        variant: "destructive",
      });
      if (!ok) return;
    }
    update.mutate(
      { id: template.id, is_active: !template.is_active },
      {
        onSuccess: () =>
          showToast(template.is_active ? "Wzór wycofany" : "Wzór przywrócony", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić wzoru."), "error"),
      },
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Własne wzory wydania i zwrotu (np. z kaucją, zwrot u klienta). Bez wybranego wzoru protokół
          powstaje ze standardu recepcji.
        </p>
        <Button variant="outline" onClick={() => download(() => downloadStandardTemplate("wydanie"))}>
          <Download className="h-4 w-4" aria-hidden />
          Standard wydania
        </Button>
        <Button variant="outline" onClick={() => download(() => downloadStandardTemplate("zwrot"))}>
          <Download className="h-4 w-4" aria-hidden />
          Standard zwrotu
        </Button>
        <Button onClick={() => setUploading(true)} disabled={!query.data}>
          <Upload className="h-4 w-4" aria-hidden />
          Dodaj wzór
        </Button>
      </div>
      {query.data ? <FieldsHelp fields={query.data.fields} required={query.data.required} /> : null}
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie wzorów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void query.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nie ma jeszcze własnych wzorów — protokoły powstają ze standardu.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Wzór</TableHead>
                <TableHead className={CALM_HEAD}>Rodzaj</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Pakiety</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Protokoły</TableHead>
                <TableHead className={CALM_HEAD}>Stan</TableHead>
                <TableHead className={CALM_HEAD} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((template) => (
                <TableRow key={template.id} className={`${CALM_ROW} h-[48px]`}>
                  <TableCell>
                    <span className={template.is_active ? "font-medium" : "text-muted-foreground"}>
                      {template.name}
                    </span>
                    <span className={CALM_SUBLINE}>
                      {[template.description, template.file_name].filter(Boolean).join(" · ")}
                    </span>
                  </TableCell>
                  <TableCell>{KIND_LABELS[template.kind]}</TableCell>
                  <TableCell className={CALM_AMOUNT}>{template.packs}</TableCell>
                  <TableCell className={CALM_AMOUNT}>{template.protocols}</TableCell>
                  <TableCell>
                    <StatusDot tone={template.is_active ? "success" : "neutral"}>
                      {template.is_active ? "w użyciu" : "wycofany"}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => download(() => downloadProtocolTemplate(template, "sample"))}
                    >
                      Próbka
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => download(() => downloadProtocolTemplate(template, "file"))}
                    >
                      Plik
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={update.isPending}
                      onClick={() => void toggle(template)}
                    >
                      {template.is_active ? "Wycofaj" : "Przywróć"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {uploading && query.data ? (
        <UploadDialog maxBytes={query.data.max_bytes} onClose={() => setUploading(false)} />
      ) : null}
      {confirmDialog}
    </div>
  );
}
