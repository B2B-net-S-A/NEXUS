"use client";

import { useState } from "react";
import { Upload } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadTemplateVersion,
  useAgreementSettings,
  useAgreementTemplates,
  useSaveAgreementSettings,
  useUpdateAgreementTemplate,
  useUploadAgreementTemplate,
  useUploadTemplateVersion,
  type AgreementTemplate,
  type AgreementTemplates,
  type TemplateKind,
} from "@/lib/api/hr-agreements";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const KIND_ORDER: TemplateKind[] = ["zlecenie", "b2b", "uop", "annex"];

/** Sprawdzenie pliku przed wysłaniem — serwer sprawdza to samo i więcej. */
export function templateFileProblem(file: File | null, maxBytes: number): string | null {
  if (!file) return "Wybierz plik Word (.docx) ze wzorem.";
  if (!file.name.toLowerCase().endsWith(".docx")) return "Wgraj plik Word w formacie .docx.";
  if (file.size === 0 || file.size > maxBytes) {
    return `Plik jest pusty albo większy niż ${Math.round(maxBytes / 1024 / 1024)} MB.`;
  }
  return null;
}

function UploadTemplateDialog({
  catalog,
  template,
  onClose,
}: {
  catalog: AgreementTemplates;
  /** Podany = nowa wersja tego wzoru; brak = nowy wzór. */
  template?: AgreementTemplate;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const upload = useUploadAgreementTemplate();
  const version = useUploadTemplateVersion();
  const [kind, setKind] = useState<TemplateKind>("zlecenie");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = upload.isPending || version.isPending;

  const submit = () => {
    const problem =
      templateFileProblem(file, catalog.max_bytes) ?? (template || name.trim() ? null : "Nazwij wzór.");
    if (problem || !file) {
      setError(problem);
      return;
    }
    setError(null);
    const failed = (err: unknown) => setError(apiErrorMessage(err, "Nie udało się dodać wzoru."));
    if (template) {
      version.mutate(
        { templateId: template.id, file },
        {
          onSuccess: (saved) => {
            showToast(`Dodano wersję ${saved.version}`, "success");
            onClose();
          },
          onError: failed,
        },
      );
      return;
    }
    upload.mutate(
      { file, kind, name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: () => {
          showToast("Wzór umowy dodany", "success");
          onClose();
        },
        onError: failed,
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={template ? `Nowa wersja: ${template.name}` : "Dodaj wzór umowy"}
      description="Plik Word z polami {{ … }} z listy niżej. Treść prawną daje wzór — NEXUS tylko wstawia pola, sprawdza plik i wypełnia go próbnie przed zapisem."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? "Sprawdzanie…" : template ? "Dodaj wersję" : "Dodaj wzór"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {template ? null : (
          <>
            <FormField label="Rodzaj" htmlFor="agreement-tpl-kind">
              <Select value={kind} onValueChange={(value) => setKind(value as TemplateKind)}>
                <SelectTrigger id="agreement-tpl-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KIND_ORDER.map((key) => (
                    <SelectItem key={key} value={key}>
                      {catalog.kinds[key]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Nazwa" htmlFor="agreement-tpl-name" required>
              <Input
                id="agreement-tpl-name"
                maxLength={120}
                placeholder="np. Zlecenie — recepcja"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </FormField>
            <FormField label="Opis" htmlFor="agreement-tpl-description" className="sm:col-span-2">
              <Input
                id="agreement-tpl-description"
                maxLength={300}
                placeholder="np. wzór kancelarii z 10.2026"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </FormField>
          </>
        )}
        <FormField label="Plik .docx" htmlFor="agreement-tpl-file" className="sm:col-span-2" required>
          <Input
            id="agreement-tpl-file"
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

function FieldsHelp({ catalog }: { catalog: AgreementTemplates }) {
  return (
    <details className="rounded-lg border border-border bg-card p-3 text-sm">
      <summary className="cursor-pointer font-medium">Pola, które wypełnia NEXUS</summary>
      <p className="mt-2 text-xs text-muted-foreground">
        Wymagane w każdym wzorze: {catalog.required.zlecenie.join(", ")}. Warunek:{" "}
        <code>{"{% if hours_confirmation %}…{% endif %}"}</code>. Bez PESEL-u, numeru dowodu i
        adresu — tożsamość przy podpisie potwierdza Autenti.
      </p>
      <dl className="mt-2 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
        {catalog.fields.map((field) => (
          <div key={field.field} className="contents">
            <dt className="font-mono text-foreground">{`{{ ${field.field} }}`}</dt>
            <dd className="text-muted-foreground">{field.label}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function ModuleSwitch({ isAdmin }: { isAdmin: boolean }) {
  const { showToast } = useToast();
  const settings = useAgreementSettings();
  const save = useSaveAgreementSettings();
  if (!settings.data) return null;
  const { enabled, autenti_configured: autenti } = settings.data;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 p-3 text-sm">
      <span>
        Umowy z ludźmi {enabled ? "włączone" : "wyłączone"}
        <span className="block text-xs text-muted-foreground">
          {autenti
            ? "Podpis przez Autenti — wysyłka tylko na kliknięcie Kadr."
            : "Autenti nie jest ustawione — podpis oznacza się ręcznie, ze skanem."}
          {isAdmin ? "" : " Moduł włącza administrator."}
        </span>
      </span>
      {isAdmin ? (
        <Switch
          checked={enabled}
          disabled={save.isPending}
          aria-label="Umowy z ludźmi włączone"
          onCheckedChange={(checked) =>
            save.mutate(checked, {
              onSuccess: () => showToast(checked ? "Umowy włączone" : "Umowy wyłączone", "success"),
              onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przełączyć modułu."), "error"),
            })
          }
        />
      ) : null}
    </div>
  );
}

/**
 * Ustawienia → Kadry → „Wzory umów” (etap 5, E5): wzory umów z ludźmi
 * wgrywane przez Kadry, z wersjami. Nowy plik to nowa wersja; umowy pamiętają
 * wersję, z której powstały. Wycofany wzór nie trafia do nowych umów.
 */
export function AgreementTemplatesCard({ isAdmin }: { isAdmin: boolean }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useAgreementTemplates(false);
  const update = useUpdateAgreementTemplate();
  const [upload, setUpload] = useState<{ template?: AgreementTemplate } | null>(null);
  const rows = query.data?.items ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  if (state === "forbidden") return null;

  const download = (action: () => Promise<void>) =>
    void action().catch((err: unknown) => showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error"));

  const toggle = async (template: AgreementTemplate) => {
    if (template.is_active) {
      const ok = await askConfirm({
        title: `Wycofać wzór „${template.name}”?`,
        description: "Nowe umowy nie powstaną z tego wzoru. Umowy, które już z niego powstały, dalej się z niego odtwarzają.",
        confirmLabel: "Wycofaj",
        variant: "destructive",
      });
      if (!ok) return;
    }
    update.mutate(
      { id: template.id, is_active: !template.is_active },
      {
        onSuccess: () => showToast(template.is_active ? "Wzór wycofany" : "Wzór przywrócony", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić wzoru."), "error"),
      },
    );
  };

  return (
    <Card className="space-y-3 p-4" aria-labelledby="agreement-templates-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="agreement-templates-title" className="text-base font-semibold text-foreground">
            Wzory umów z pracownikami
          </h2>
          <p className="text-sm text-muted-foreground">
            B2B biura, zlecenie, umowa o pracę i aneks — pliki Word od Kadr z wersjami.
          </p>
        </div>
        <Button onClick={() => setUpload({})} disabled={!query.data}>
          <Upload className="h-4 w-4" aria-hidden />
          Dodaj wzór
        </Button>
      </div>
      <ModuleSwitch isAdmin={isAdmin} />
      {query.data ? <FieldsHelp catalog={query.data} /> : null}
      {state === "loading" ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie wzorów…</p>
      ) : state === "not_found" ? (
        <p className="text-sm text-muted-foreground">
          Moduł umów jest wyłączony — po włączeniu przez administratora dodasz tu wzory.
        </p>
      ) : state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void query.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Nie ma jeszcze wzorów umów — dodaj pierwszy plik Word od kancelarii albo Kadr.
        </div>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr>
                <th className={cn(CALM_HEAD, "w-[38%] py-2 pr-3 text-left")}>Wzór</th>
                <th className={cn(CALM_HEAD, "w-[16%] py-2 pr-3 text-left")}>Rodzaj</th>
                <th className={cn(CALM_HEAD, "w-[18%] py-2 pr-3 text-left")}>Wersja</th>
                <th className={cn(CALM_HEAD, "w-[12%] py-2 pr-3 text-left")}>Stan</th>
                <th className={cn(CALM_HEAD, "py-2")}>
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((template) => {
                const latest = template.versions[0];
                const used = template.versions.reduce((sum, version) => sum + version.agreements, 0);
                return (
                  <tr key={template.id} className={CALM_ROW}>
                    <td className="py-2 pr-3">
                      <span className={template.is_active ? "font-medium" : "text-muted-foreground"}>
                        {template.name}
                      </span>
                      <span className={CALM_SUBLINE}>
                        {[template.description, latest?.file_name].filter(Boolean).join(" · ")}
                      </span>
                    </td>
                    <td className="py-2 pr-3">{template.kind_label}</td>
                    <td className="py-2 pr-3">
                      {latest ? `wersja ${latest.version}` : "—"}
                      <span className={CALM_SUBLINE}>
                        {latest?.created_at ? formatIsoDatePl(latest.created_at) : ""}
                        {used ? ` · umowy: ${used}` : ""}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <StatusDot tone={template.is_active ? "success" : "neutral"}>
                        {template.is_active ? "w użyciu" : "wycofany"}
                      </StatusDot>
                    </td>
                    <td className="whitespace-nowrap py-2 text-right">
                      {latest ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => download(() => downloadTemplateVersion(latest, "sample"))}
                          >
                            Próbka
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => download(() => downloadTemplateVersion(latest, "file"))}
                          >
                            Plik
                          </Button>
                        </>
                      ) : null}
                      {template.is_active ? (
                        <Button variant="ghost" size="sm" onClick={() => setUpload({ template })}>
                          Nowa wersja
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={update.isPending}
                        onClick={() => void toggle(template)}
                      >
                        {template.is_active ? "Wycofaj" : "Przywróć"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {upload && query.data ? (
        <UploadTemplateDialog catalog={query.data} template={upload.template} onClose={() => setUpload(null)} />
      ) : null}
      {confirmDialog}
    </Card>
  );
}
