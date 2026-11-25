"use client";

// „Nowy wzór z asystentem” (asystent prawny, część B, 25.11.2026): uwaga
// zespołu — „stworzyć całkiem nowy wzór, zachować go i dodać do wyboru
// w Generatorze”. Trzy kroki: 1. Opis (start od wzoru, z Worda albo z opisu),
// 2. Szkic i pola (zmiany względem wzoru bazowego, pola i sprawdzenia),
// 3. Zapis i zatwierdzenie (zatwierdza administrator). Wzór leży w bazie
// (DOCX + lista pól); kwoty słownie, daty i formy Pan/Pani liczy NEXUS.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  FileText,
  FlaskConical,
  Loader2,
  Pencil,
  Sparkles,
  Upload,
  X,
} from "lucide-react";

import { FileDropZone } from "@/components/ds/FileDropZone";
import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { B2B_DOCUMENTS_KEY } from "@/lib/api/b2bDocuments";
import {
  CUSTOM_TEMPLATES_KEY,
  customTemplatesApi,
  customTemplatesKeys,
  useCustomTemplate,
  useCustomTemplateBases,
  useCustomTemplates,
  type CustomFieldDef,
  type CustomTemplateDetail,
  type CustomTemplateOrigin,
  type CustomVersion,
} from "@/lib/api/customTemplates";
import {
  FIELD_KIND_LABELS,
  KIND_OPTIONS,
  SIGNATORY_OPTIONS,
  SOURCE_OPTIONS,
  STUDIO_STEPS,
  changeSummary,
  checkTone,
  citeStateLabel,
  fieldsPayload,
  groupFields,
  initialStep,
  patchField,
  submitBlockers,
  type StudioStep,
} from "@/lib/custom-templates";
import { formatDateTimePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { saveDocx } from "../DocumentDialogs";

const SECTION_LABEL =
  "mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground";
const SELECT_CLASS =
  "h-8 rounded-md border border-border bg-card px-2 text-[12.5px] text-foreground";

export interface TemplateStudioProps {
  /** `null` = nowy wzór (krok „Opis”). */
  templateId: number | null;
  onTemplate: (id: number) => void;
  onClose: () => void;
  /** Harness: szczegóły zamiast zapytania. */
  initialDetail?: CustomTemplateDetail;
}

export function TemplateStudio({
  templateId,
  onTemplate,
  onClose,
  initialDetail,
}: TemplateStudioProps) {
  const detailQuery = useCustomTemplate(initialDetail ? null : templateId);
  const detail = initialDetail ?? detailQuery.data ?? null;
  const [step, setStep] = useState<StudioStep>(templateId ? "draft" : "brief");
  const [stepFor, setStepFor] = useState<number | null>(null);
  useEffect(() => {
    if (detail && stepFor !== detail.id) {
      setStep(initialStep(detail));
      setStepFor(detail.id);
    }
  }, [detail, stepFor]);
  const version = detail?.working ?? detail?.active ?? null;

  return (
    <section
      className="rounded-xl border border-border bg-card shadow-xs"
      aria-label="Nowy wzór z asystentem"
    >
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold">
            {version ? `Wzór · ${version.name}` : "Nowy wzór z asystentem"}
          </h2>
          <p className="text-[12.5px] text-muted-foreground">
            {version
              ? `${version.kind_label} · wersja ${version.version_no} · ${version.status_label}`
              : "Wzór zapisze się w NEXUSIE; w „Nowy dokument” pojawi się po zatwierdzeniu przez administratora."}
          </p>
        </div>
        <Stepper step={step} onStep={detail ? setStep : undefined} />
        <Button variant="ghost" size="sm" onClick={onClose}>
          Zamknij
        </Button>
      </header>
      {templateId && !detail ? (
        detailQuery.isError ? (
          <div className="p-4">
            <Alert
              variant="error"
              title={apiErrorMessage(detailQuery.error, "Nie udało się wczytać wzoru.")}
            />
          </div>
        ) : (
          <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Wczytuję wzór…
          </p>
        )
      ) : step === "brief" || !detail ? (
        <BriefStep
          onCreated={(created) => {
            onTemplate(created.id);
            setStepFor(created.id);
            setStep("draft");
          }}
        />
      ) : step === "draft" ? (
        <DraftStep detail={detail} onNext={() => setStep("save")} />
      ) : (
        <SaveStep detail={detail} onClose={onClose} />
      )}
    </section>
  );
}

function Stepper({
  step,
  onStep,
}: {
  step: StudioStep;
  onStep?: (step: StudioStep) => void;
}) {
  const index = STUDIO_STEPS.findIndex((s) => s.key === step);
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[12px]" aria-label="Kroki">
      {STUDIO_STEPS.map((s, n) => {
        const current = s.key === step;
        const done = n < index;
        const clickable = Boolean(onStep) && s.key !== "brief";
        return (
          <li key={s.key}>
            <button
              type="button"
              disabled={!clickable}
              aria-current={current ? "step" : undefined}
              onClick={() => onStep?.(s.key)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5",
                current
                  ? "border-primary bg-primary/10 font-semibold text-foreground"
                  : "border-border text-muted-foreground",
                clickable && !current && "hover:bg-muted",
              )}
            >
              {done ? (
                <CheckCircle2 className="h-3 w-3 text-success" aria-hidden="true" />
              ) : (
                <Circle className="h-3 w-3" aria-hidden="true" />
              )}
              {n + 1}. {s.label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ── Krok 1: Opis ────────────────────────────────────────────────────────────

function BriefStep({ onCreated }: { onCreated: (detail: CustomTemplateDetail) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const bases = useCustomTemplateBases();
  const templates = useCustomTemplates();
  const approved = (templates.data?.templates ?? []).filter(
    (t) => t.active_version_no !== null && !t.withdrawn,
  );
  const [origin, setOrigin] = useState<CustomTemplateOrigin>("base");
  const [baseKey, setBaseKey] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const modelAvailable = bases.data?.model_available ?? false;
  const effectiveBase = baseKey ?? bases.data?.bases[0]?.key ?? null;
  const create = useMutation({
    mutationFn: () =>
      customTemplatesApi.create({
        origin,
        name: name.trim() || undefined,
        baseKey: origin === "base" ? effectiveBase : null,
        instruction: instruction.trim() || null,
        file: origin === "upload" ? file : null,
      }),
    onSuccess: (detail) => {
      void queryClient.invalidateQueries({ queryKey: [CUSTOM_TEMPLATES_KEY] });
      queryClient.setQueryData(customTemplatesKeys.detail(detail.id), detail);
      if (detail.message) toast.showInfo(detail.message);
      onCreated(detail);
    },
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się utworzyć wzoru.")),
  });
  const ready =
    (origin === "base" && effectiveBase !== null) ||
    (origin === "upload" && file !== null) ||
    (origin === "brief" && instruction.trim().length >= 3 && modelAvailable);

  return (
    <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <div>
          <h3 className={SECTION_LABEL}>Zacznij od</h3>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Zacznij od">
            <OriginCard
              on={origin === "base"}
              onClick={() => setOrigin("base")}
              title="Istniejący wzór"
              hint="Zmienię to, co opiszesz, reszta zostaje"
              icon={<FileText className="h-4 w-4 text-primary" aria-hidden="true" />}
            />
            <OriginCard
              on={origin === "upload"}
              onClick={() => setOrigin("upload")}
              title="Plik Word od działu"
              hint="Luki ____ i formy Pan/Pani zamienię na pola"
              icon={<Upload className="h-4 w-4 text-primary" aria-hidden="true" />}
            />
            <OriginCard
              on={origin === "brief"}
              onClick={() => setOrigin("brief")}
              title="Sam opis"
              hint={modelAvailable ? "Asystent napisze szkic" : "Wymaga asystenta (teraz niedostępny)"}
              icon={<Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />}
              disabled={!modelAvailable}
            />
          </div>
        </div>

        {origin === "base" ? (
          <div className="space-y-1.5">
            <Label>Wzór bazowy</Label>
            {bases.isPending ? (
              <p className="text-sm text-muted-foreground">Wczytuję wzory…</p>
            ) : bases.isError ? (
              <Alert variant="error" title={apiErrorMessage(bases.error, "Nie udało się wczytać wzorów.")} />
            ) : (
              <ul className="space-y-1">
                {[
                  ...(bases.data?.bases ?? []).map((b) => ({
                    key: b.key,
                    label: b.label,
                    description: b.description,
                  })),
                  ...approved.map((t) => ({
                    key: `custom:${t.id}`,
                    label: `${t.name} (wzór własny v${t.active_version_no})`,
                    description: t.description,
                  })),
                ].map((b) => (
                  <li key={b.key}>
                    <button
                      type="button"
                      aria-pressed={effectiveBase === b.key}
                      onClick={() => setBaseKey(b.key)}
                      className={cn(
                        "w-full rounded-md border px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted",
                        effectiveBase === b.key
                          ? "border-primary bg-primary/5 font-medium"
                          : "border-border",
                      )}
                    >
                      {b.label}
                      {b.description ? (
                        <span className="block text-[12px] font-normal text-muted-foreground">
                          {b.description}
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {origin === "upload" ? (
          <FileDropZone
            inputId="custom-template-docx"
            file={file}
            onPick={(f) => {
              setFile(f);
              setFileError(null);
            }}
            accept=".docx"
            maxBytes={5 * 1024 * 1024}
            label="Wzór w Wordzie (.docx)"
            hint="Bez danych osób — NEXUS ostrzeże, jeśli w treści jest NIP, PESEL albo e-mail."
            error={fileError}
            onError={setFileError}
          />
        ) : null}

        <div className="space-y-1.5">
          <Label htmlFor="custom-template-instruction">
            {origin === "brief" ? "Opis wzoru *" : "Polecenie dla asystenta (opcjonalnie)"}
          </Label>
          <Textarea
            id="custom-template-instruction"
            rows={4}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={
              origin === "brief"
                ? "Np. umowa o poprowadzenie szkolenia stacjonarnego u klienta: ryczałt, zwrot kosztów dojazdu do limitu, prawa autorskie do materiałów."
                : "Np. szkolenie stacjonarne w siedzibie klienta: sala po stronie klienta, zwrot kosztów dojazdu do limitu. Reszta bez zmian."
            }
          />
          {!modelAvailable && origin !== "brief" ? (
            <p className="text-[12px] text-muted-foreground">
              Asystent jest teraz niedostępny — wzór powstanie bez zmian, pola wykryje NEXUS.
            </p>
          ) : null}
        </div>
        <div className="max-w-md space-y-1.5">
          <Label htmlFor="custom-template-name">Nazwa robocza</Label>
          <Input
            id="custom-template-name"
            value={name}
            maxLength={150}
            onChange={(e) => setName(e.target.value)}
            placeholder="Np. Umowa o szkolenie stacjonarne u klienta"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => create.mutate()} disabled={!ready} loading={create.isPending}>
            {instruction.trim() && modelAvailable ? "Przygotuj szkic z asystentem" : "Utwórz szkic"}
          </Button>
          <span className="text-[12px] text-muted-foreground">
            Nic nie trafia jeszcze do Generatora — to szkic.
          </span>
        </div>
      </div>
      <aside className="space-y-2 rounded-lg border border-border bg-muted/40 p-3 text-[12.5px] leading-snug">
        <p className="font-semibold">Jak to działa</p>
        <ol className="list-decimal space-y-1 pl-4 text-muted-foreground">
          <li>Asystent proponuje zmiany akapitów i nowe pola — pisze tylko zdania.</li>
          <li>Kwoty słownie, daty i formy Pan/Pani wypełnia NEXUS, nie model.</li>
          <li>Do modelu idzie wyłącznie treść wzoru, bez danych osób.</li>
          <li>Wzór zatwierdza administrator. Dokument ze wzoru własnego nie zmienia kontraktów ani zamówień.</li>
        </ol>
        <p className="text-muted-foreground">
          To pomoc przy wzorze, nie porada prawna — przy karach umownych, sporach i rozwiązaniu ze
          skutkiem natychmiastowym zapytaj prawnika.
        </p>
      </aside>
    </div>
  );
}

function OriginCard({
  on,
  onClick,
  title,
  hint,
  icon,
  disabled,
}: {
  on: boolean;
  onClick: () => void;
  title: string;
  hint: string;
  icon: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-full flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors",
        on ? "border-primary bg-primary/5" : "border-dashed border-border hover:bg-muted",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <span className="flex items-center gap-2 text-sm font-medium">
        {icon}
        {title}
      </span>
      <span className="text-[12px] text-muted-foreground">{hint}</span>
    </button>
  );
}

// ── Krok 2: Szkic i pola ────────────────────────────────────────────────────

function useStudioMutation<T>(
  fn: (arg: T) => Promise<CustomTemplateDetail>,
  error: string,
  success?: string,
) {
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (detail) => {
      queryClient.setQueryData(customTemplatesKeys.detail(detail.id), detail);
      void queryClient.invalidateQueries({ queryKey: customTemplatesKeys.list() });
      void queryClient.invalidateQueries({ queryKey: [B2B_DOCUMENTS_KEY, "types"] });
      if (detail.message) toast.showInfo(detail.message);
      else if (success) toast.showSuccess(success);
    },
    onError: (err) => toast.showError(apiErrorMessage(err, error)),
  });
}

function DraftStep({ detail, onNext }: { detail: CustomTemplateDetail; onNext: () => void }) {
  const toast = useToast();
  const version = (detail.working ?? detail.active) as CustomVersion;
  const editable = detail.can_edit;
  const [instruction, setInstruction] = useState(version.instruction ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [editing, setEditing] = useState(false);
  const [fields, setFields] = useState<CustomFieldDef[]>(version.fields);
  useEffect(() => setFields(version.fields), [version.fields]);
  const redraft = useStudioMutation(
    (text: string) => customTemplatesApi.redraft(detail.id, text),
    "Asystent nie przygotował szkicu.",
    "Szkic zaktualizowany.",
  );
  const upload = useStudioMutation(
    (f: File) => customTemplatesApi.upload(detail.id, f),
    "Nie udało się wczytać pliku Word.",
    "Treść wzoru podmieniona — pola wykryte na nowo.",
  );
  const saveFields = useStudioMutation(
    (next: CustomFieldDef[]) => customTemplatesApi.update(detail.id, { fields: fieldsPayload(next) }),
    "Nie udało się zapisać pól.",
    "Pola zapisane.",
  );
  const sample = useMutation({
    mutationFn: () => customTemplatesApi.sample(detail.id),
    onSuccess: (res) =>
      saveDocx(res as { data: unknown; headers: Record<string, unknown> }, "proba.docx"),
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się przygotować próbnego dokumentu.")),
  });
  const changes = version.changes ?? [];
  const groups = useMemo(() => groupFields(editing ? fields : version.fields), [editing, fields, version.fields]);

  return (
    <div className="grid gap-3.5 p-4 lg:grid-cols-[230px_minmax(0,1fr)_300px]">
      <div className="space-y-3 text-[13px]">
        <div>
          <h3 className={SECTION_LABEL}>Zaczęło się od</h3>
          <p className="rounded-md border border-primary bg-primary/5 px-2 py-1.5 font-medium">
            {version.origin === "upload"
              ? "Plik Word od działu"
              : version.origin === "brief"
                ? "Sam opis"
                : `Wzór: ${version.base_key === "training_agreement" ? "Umowa B2B — szkolenia" : (version.base_key ?? "")}`}
          </p>
        </div>
        {editable ? (
          <div className="space-y-1.5">
            <h3 className={SECTION_LABEL}>Polecenie</h3>
            <Textarea
              aria-label="Polecenie dla asystenta"
              rows={5}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Co zmienić we wzorze?"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={instruction.trim().length < 3}
              loading={redraft.isPending}
              onClick={() => redraft.mutate(instruction.trim())}
            >
              <Sparkles className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
              {changes.length ? "Popraw szkic tym poleceniem" : "Przygotuj szkic"}
            </Button>
            <p className="text-[11.5px] text-muted-foreground">
              Kolejne polecenie zmienia bieżący szkic.
            </p>
          </div>
        ) : version.instruction ? (
          <div>
            <h3 className={SECTION_LABEL}>Polecenie</h3>
            <p className="rounded-md border border-border bg-background p-2 leading-snug">{version.instruction}</p>
          </div>
        ) : null}
        {editable ? (
          <div className="space-y-1.5">
            <h3 className={SECTION_LABEL}>Podmień treść</h3>
            <FileDropZone
              inputId={`custom-template-replace-${detail.id}`}
              file={file}
              onPick={setFile}
              accept=".docx"
              maxBytes={5 * 1024 * 1024}
              label="Plik Word (.docx)"
            />
            {file ? (
              <Button size="sm" variant="outline" loading={upload.isPending} onClick={() => upload.mutate(file)}>
                Wczytaj plik
              </Button>
            ) : null}
          </div>
        ) : null}
        <p className="text-[12px] text-muted-foreground">{changeSummary(changes, version.fields.length)}</p>
      </div>

      <div className="min-w-0 space-y-3">
        {changes.length ? (
          <details className="rounded-md border border-border bg-background" open>
            <summary className="cursor-pointer px-3 py-2 text-[12.5px] font-semibold">
              Zmiany względem wzoru bazowego ({changes.length})
            </summary>
            <ul className="max-h-48 space-y-2 overflow-y-auto px-3 pb-3 text-[12.5px] leading-relaxed">
              {changes.map((c, n) => (
                <li key={`${c.i}-${c.op}-${n}`} className="border-t border-border pt-2 first:border-t-0 first:pt-0">
                  {c.before ? (
                    <del className="bg-destructive-muted text-destructive-muted-foreground">{c.before}</del>
                  ) : null}{" "}
                  {c.after ? (
                    <ins className="bg-success-muted text-success-muted-foreground decoration-success">{c.after}</ins>
                  ) : null}
                  {c.reason ? (
                    <span className="block text-[11.5px] text-muted-foreground">{c.reason}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <article
          aria-label="Treść wzoru"
          className={cn(
            "max-h-[460px] space-y-2 overflow-y-auto rounded-md border border-border bg-background px-5 py-4 text-[13px] leading-relaxed",
            "[&_h1]:text-center [&_h1]:font-semibold [&_h2]:mt-3 [&_h2]:text-center [&_h2]:font-semibold",
            // Numeracja list jest w tekście wzoru albo w stylu Worda — podgląd jej nie dokłada.
            "[&_ol]:list-none [&_ol]:pl-0 [&_p.right]:text-right [&_table]:w-full [&_td]:border [&_td]:border-border [&_td]:p-1",
            "[&_.tpl-field]:rounded [&_.tpl-field]:bg-warning-muted [&_.tpl-field]:px-1 [&_.tpl-field]:text-[12.5px] [&_.tpl-field]:font-medium [&_.tpl-field]:text-warning-muted-foreground",
            "[&_.tpl-control]:font-mono [&_.tpl-control]:text-[11px] [&_.tpl-control]:text-muted-foreground",
          )}
          // HTML z serwera: tekst wzoru i etykiety pól są escapowane
          // (`doc_to_html`, `service.preview_html`).
          dangerouslySetInnerHTML={{ __html: version.preview_html ?? "" }}
        />
      </div>

      <aside className="space-y-3">
        <div>
          <div className="mb-1 flex items-center justify-between">
            <h3 className={SECTION_LABEL}>Pola formularza</h3>
            {editable ? (
              editing ? (
                <span className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setFields(version.fields);
                      setEditing(false);
                    }}
                  >
                    Anuluj
                  </Button>
                  <Button
                    size="sm"
                    loading={saveFields.isPending}
                    onClick={() => saveFields.mutate(fields, { onSuccess: () => setEditing(false) })}
                  >
                    Zapisz pola
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
                  <Pencil className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                  Popraw
                </Button>
              )
            ) : null}
          </div>
          {groups.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">Wzór nie ma jeszcze pól.</p>
          ) : (
            <ul className="space-y-2">
              {groups.map((g) => (
                <li key={g.group}>
                  <div className="text-[12px] font-semibold">{g.group}</div>
                  <ul className="space-y-1">
                    {g.fields.map((f) =>
                      editing ? (
                        <FieldEditor
                          key={f.key}
                          field={f}
                          onChange={(patch) => setFields((prev) => patchField(prev, f.key, patch))}
                        />
                      ) : (
                        <li key={f.key} className="flex items-baseline justify-between gap-2 text-[12.5px]">
                          <span className="min-w-0">
                            {f.label}
                            {f.required ? <span className="text-destructive"> *</span> : null}
                          </span>
                          <span className="shrink-0 text-[11px] text-muted-foreground">
                            {f.kind === "money" ? "kwota · słownie liczy NEXUS" : f.source_label}
                          </span>
                        </li>
                      ),
                    )}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          {version.unused_fields?.length ? (
            <p className="mt-2 text-[11.5px] text-muted-foreground">
              Nieużyte w treści: {version.unused_fields.join(", ")}
            </p>
          ) : null}
        </div>
        <ChecksList version={version} />
      </aside>

      <div className="flex flex-wrap items-center gap-2 lg:col-span-3">
        <Button size="sm" onClick={onNext}>
          Dalej: zapisz jako wzór
        </Button>
        <Button size="sm" variant="outline" loading={sample.isPending} onClick={() => sample.mutate()}>
          <FlaskConical className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
          Próbny dokument (dane fikcyjne)
        </Button>
        <span className="ml-auto text-[12px] text-muted-foreground">
          Kwoty słownie, daty i formy Pan/Pani wypełnia NEXUS, nie model
        </span>
      </div>
    </div>
  );
}

function FieldEditor({
  field,
  onChange,
}: {
  field: CustomFieldDef;
  onChange: (patch: Partial<CustomFieldDef>) => void;
}) {
  const id = `custom-field-${field.key}`;
  return (
    <li className="space-y-1 rounded-md border border-border p-2">
      <Input
        id={id}
        aria-label={`Etykieta pola ${field.key}`}
        value={field.label}
        maxLength={120}
        onChange={(e) => onChange({ label: e.target.value })}
        className="h-8 text-[12.5px]"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          aria-label="Rodzaj pola"
          className={SELECT_CLASS}
          value={field.kind}
          disabled={field.kind === "list" || field.kind === "select"}
          onChange={(e) => onChange({ kind: e.target.value as CustomFieldDef["kind"] })}
        >
          {(["text", "textarea", "date", "money", "bool", "email", "gender"] as const).map((k) => (
            <option key={k} value={k}>
              {FIELD_KIND_LABELS[k]}
            </option>
          ))}
          {field.kind === "list" || field.kind === "select" ? (
            <option value={field.kind}>{FIELD_KIND_LABELS[field.kind]}</option>
          ) : null}
        </select>
        <select
          aria-label="Źródło"
          className={SELECT_CLASS}
          value={field.source}
          onChange={(e) => onChange({ source: e.target.value as CustomFieldDef["source"] })}
        >
          {SOURCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-[12px]">
          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => onChange({ required: e.target.checked })}
          />
          wymagane
        </label>
      </div>
      <Input
        aria-label="Grupa"
        value={field.group}
        maxLength={40}
        onChange={(e) => onChange({ group: e.target.value })}
        className="h-7 text-[12px]"
      />
    </li>
  );
}

function ChecksList({ version }: { version: CustomVersion }) {
  const problems = version.problems ?? [];
  const warnings = version.warnings ?? [];
  return (
    <div className="space-y-2">
      <h3 className={SECTION_LABEL}>Sprawdzone</h3>
      <ul className="space-y-1.5">
        {(version.checks ?? []).map((c) => (
          <li key={c.key} className="flex gap-1.5 text-[12.5px] leading-snug">
            {c.state === "ok" ? (
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
            ) : (
              <AlertTriangle
                className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", c.state === "block" ? "text-destructive" : "text-warning")}
                aria-hidden="true"
              />
            )}
            <span>
              {c.text}{" "}
              <Badge variant={checkTone(c)} size="sm" title={citeStateLabel(c.cite_state)}>
                {c.cite}
              </Badge>
              <span className="block text-[11px] text-muted-foreground">{citeStateLabel(c.cite_state)}</span>
            </span>
          </li>
        ))}
      </ul>
      {problems.length ? (
        <Alert variant="error" title="Do poprawy we wzorze">
          <ul className="mt-1 list-disc pl-4 text-[12px]">
            {problems.slice(0, 8).map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
      {warnings.length ? (
        <Alert variant="warning" title="Uwagi">
          <ul className="mt-1 list-disc pl-4 text-[12px]">
            {warnings.slice(0, 8).map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
    </div>
  );
}

// ── Krok 3: Zapis i zatwierdzenie ───────────────────────────────────────────

function Choice({
  label,
  on,
  onClick,
  disabled,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center rounded-full border px-2.5 text-[12px] transition-colors",
        on ? "border-primary bg-primary/10 font-medium text-foreground" : "border-border text-muted-foreground hover:bg-muted",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      {label}
    </button>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[170px_minmax(0,1fr)] sm:items-center">
      <span className="text-[12.5px] font-medium text-muted-foreground">{label}</span>
      <div className="flex flex-wrap items-center gap-1.5 text-[13px]">{children}</div>
    </div>
  );
}

function SaveStep({ detail, onClose }: { detail: CustomTemplateDetail; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const version = (detail.working ?? detail.active) as CustomVersion;
  const editable = detail.can_edit;
  const [name, setName] = useState(version.name);
  const [description, setDescription] = useState(version.description);
  const [kind, setKind] = useState(version.kind);
  const [scope, setScope] = useState(version.client_scope);
  const [clients, setClients] = useState<{ id: number; name: string }[]>(
    version.client_ids.map((id) => ({ id, name: `Klient #${id}` })),
  );
  const [signatories, setSignatories] = useState(version.signatories);
  const [signatureForm, setSignatureForm] = useState(version.signature_form);
  useEffect(() => {
    setName(version.name);
    setDescription(version.description);
    setKind(version.kind);
    setScope(version.client_scope);
    setSignatories(version.signatories);
    setSignatureForm(version.signature_form);
  }, [version]);
  const settings = () => ({
    name: name.trim(),
    description: description.trim(),
    kind,
    client_scope: scope,
    client_ids: scope === "selected" ? clients.map((c) => c.id) : [],
    signatories,
    signature_form: signatureForm,
  });
  const save = useStudioMutation(
    () => customTemplatesApi.update(detail.id, settings()),
    "Nie udało się zapisać szkicu.",
    "Szkic zapisany.",
  );
  const submit = useStudioMutation(
    async () => {
      await customTemplatesApi.update(detail.id, settings());
      return customTemplatesApi.submit(detail.id);
    },
    "Nie udało się wysłać wzoru do zatwierdzenia.",
    "Wzór czeka na zatwierdzenie administratora.",
  );
  const approve = useStudioMutation(
    () => customTemplatesApi.approve(detail.id),
    "Nie udało się zatwierdzić wzoru.",
    "Wzór zatwierdzony — jest w „Nowy dokument”.",
  );
  const giveBack = useStudioMutation(
    (reason: string) => customTemplatesApi.returnToAuthor(detail.id, reason),
    "Nie udało się zwrócić wzoru.",
    "Wzór wrócił do autora z uwagą.",
  );
  const withdraw = useStudioMutation(
    (reason: string) => customTemplatesApi.withdraw(detail.id, reason),
    "Nie udało się wycofać wzoru.",
    "Wzór wycofany z „Nowy dokument”.",
  );
  const newVersion = useStudioMutation(
    () => customTemplatesApi.newVersion(detail.id),
    "Nie udało się założyć nowej wersji.",
    "Szkic nowej wersji gotowy — działająca wersja zostaje do zatwierdzenia nowej.",
  );
  const discard = useMutation({
    mutationFn: () => customTemplatesApi.discard(detail.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [CUSTOM_TEMPLATES_KEY] });
      toast.showSuccess("Szkic odrzucony.");
      onClose();
    },
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się odrzucić szkicu.")),
  });
  const blockers = submitBlockers({
    ...version,
    name,
    client_scope: scope,
    client_ids: scope === "selected" ? clients.map((c) => c.id) : [],
    checks: (version.checks ?? []).map((c) =>
      c.key === "art53_pr_aut" && signatureForm === "written" ? { ...c, state: "ok" as const } : c,
    ),
  });
  const copyright = (version.checks ?? []).some((c) => c.key === "art53_pr_aut");
  const pending = version.status === "pending";

  return (
    <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      {confirmDialog}
      <div className="space-y-3">
        {version.review_note && version.status === "draft" ? (
          <Alert
            variant="warning"
            title={`Uwaga administratora${version.reviewed_by_name ? ` (${version.reviewed_by_name})` : ""}`}
            description={version.review_note}
          />
        ) : null}
        <Row label="Nazwa w Generatorze">
          <Input
            aria-label="Nazwa w Generatorze"
            value={name}
            maxLength={150}
            disabled={!editable}
            onChange={(e) => setName(e.target.value)}
          />
        </Row>
        <Row label="Opis na karcie">
          <Input
            aria-label="Opis na karcie"
            value={description}
            maxLength={300}
            disabled={!editable}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Np. trener z działalnością, szkolenie w siedzibie klienta"
          />
        </Row>
        <Row label="Rodzaj">
          {KIND_OPTIONS.map((o) => (
            <Choice key={o.value} label={o.label} on={kind === o.value} disabled={!editable} onClick={() => setKind(o.value)} />
          ))}
        </Row>
        <Row label="Dla klientów">
          <Choice label="Wszyscy" on={scope === "all"} disabled={!editable} onClick={() => setScope("all")} />
          <Choice label="Tylko wybrani" on={scope === "selected"} disabled={!editable} onClick={() => setScope("selected")} />
        </Row>
        {scope === "selected" ? (
          <Row label="Wybrani klienci">
            {clients.map((c) => (
              <Badge key={c.id} variant="outline" className="gap-1">
                {c.name}
                {editable ? (
                  <button
                    type="button"
                    aria-label={`Usuń ${c.name}`}
                    onClick={() => setClients((prev) => prev.filter((x) => x.id !== c.id))}
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                ) : null}
              </Badge>
            ))}
            {editable ? (
              <div className="w-64">
                <ClientSinglePicker
                  queryKey="custom-template-clients"
                  value={null}
                  placeholder="Dodaj klienta…"
                  selectableOnly
                  onChange={(client) => {
                    if (client && !clients.some((c) => c.id === client.id)) {
                      setClients((prev) => [...prev, { id: client.id, name: client.name }]);
                    }
                  }}
                />
              </div>
            ) : null}
          </Row>
        ) : null}
        <Row label="Podpis">
          {SIGNATORY_OPTIONS.map((o) => (
            <Choice
              key={o.value}
              label={o.label}
              on={signatories === o.value}
              disabled={!editable}
              onClick={() => setSignatories(o.value)}
            />
          ))}
        </Row>
        <Row label="Forma podpisu">
          <Choice label="Dowolna" on={signatureForm === "any"} disabled={!editable} onClick={() => setSignatureForm("any")} />
          <Choice
            label="Na papierze albo kwalifikowany"
            on={signatureForm === "written"}
            disabled={!editable}
            onClick={() => setSignatureForm("written")}
          />
          {copyright ? (
            <span className="text-[12px] text-muted-foreground">
              wzór przenosi prawa autorskie — wymusza to art. 53 pr. aut.
            </span>
          ) : null}
        </Row>
        <Row label="Co robi po podpisie">
          <Choice label="Tylko dokument w rejestrze" on onClick={() => undefined} />
          <span className="text-[12px] text-muted-foreground">
            zakładanie kontraktów i zamówień zostaje przy wzorach dodanych przez programistę
          </span>
        </Row>
        <Row label="Wersja">
          <span>
            v{version.version_no} · kolejna zmiana = v{version.version_no + 1}, wydane dokumenty zostają na swojej wersji
          </span>
        </Row>

        <ApprovalTimeline detail={detail} version={version} />

        {editable && blockers.length ? (
          <Alert variant="warning" title="Zanim wyślesz do zatwierdzenia">
            <ul className="mt-1 list-disc pl-4 text-[12px]">
              {blockers.slice(0, 8).map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </Alert>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {editable ? (
            <>
              <Button size="sm" disabled={blockers.length > 0} loading={submit.isPending} onClick={() => submit.mutate(undefined)}>
                Wyślij do zatwierdzenia
              </Button>
              <Button size="sm" variant="outline" loading={save.isPending} onClick={() => save.mutate(undefined)}>
                Zapisz szkic
              </Button>
              <Button
                size="sm"
                variant="quiet"
                loading={discard.isPending}
                onClick={async () => {
                  const ok = await askConfirm({
                    title: "Odrzucić szkic?",
                    description: detail.active
                      ? "Działająca wersja zostaje w „Nowy dokument”."
                      : "Wzór nie ma zatwierdzonej wersji — zniknie cały.",
                    confirmLabel: "Odrzuć szkic",
                    variant: "destructive",
                  });
                  if (ok) discard.mutate();
                }}
              >
                Odrzuć szkic
              </Button>
            </>
          ) : null}
          {detail.can_review ? (
            <>
              <Button size="sm" loading={approve.isPending} onClick={() => approve.mutate(undefined)}>
                <CheckCircle2 className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                Zatwierdź wzór
              </Button>
              <Button
                size="sm"
                variant="outline"
                loading={giveBack.isPending}
                onClick={async () => {
                  const reason = await askReason({
                    title: "Zwrócić wzór do poprawy?",
                    description: "Autor zobaczy uwagę przy szkicu.",
                    confirmLabel: "Zwróć",
                    field: { label: "Co poprawić", minLength: 3, placeholder: "Np. § 3 ust. 8 — dodaj limit kosztów noclegu." },
                  });
                  if (reason) giveBack.mutate(reason);
                }}
              >
                Zwróć do poprawy
              </Button>
            </>
          ) : null}
          {detail.can_new_version ? (
            <Button size="sm" variant="outline" loading={newVersion.isPending} onClick={() => newVersion.mutate(undefined)}>
              Nowa wersja wzoru
            </Button>
          ) : null}
          {detail.can_withdraw ? (
            <Button
              size="sm"
              variant="quiet"
              loading={withdraw.isPending}
              onClick={async () => {
                const reason = await askReason({
                  title: "Wycofać wzór z „Nowy dokument”?",
                  description: "Wydane dokumenty zostają i pobierają się dalej.",
                  confirmLabel: "Wycofaj",
                  variant: "destructive",
                  field: { label: "Powód", minLength: 3 },
                });
                if (reason) withdraw.mutate(reason);
              }}
            >
              Wycofaj wzór
            </Button>
          ) : null}
        </div>
        {pending && !detail.can_review ? (
          <p className="text-[12px] text-muted-foreground">
            Wzór czeka na administratora — zmiany po jego decyzji.
          </p>
        ) : null}
      </div>

      <aside className="space-y-2 self-start">
        <div className={SECTION_LABEL}>Tak zobaczą go inni</div>
        <CustomTemplateCard
          name={name || version.name}
          description={description}
          versionNo={version.version_no}
          approvedAt={version.status === "approved" ? version.reviewed_at : null}
        />
        <p className="text-[12px] leading-snug text-muted-foreground">
          Wzór leży w bazie NEXUSA (DOCX + lista pól), nie w kodzie. Dokument z niego trafia do listy
          „Dokumenty do umów” i nie zmienia kontraktów.
        </p>
      </aside>
    </div>
  );
}

function ApprovalTimeline({ detail, version }: { detail: CustomTemplateDetail; version: CustomVersion }) {
  const items = [
    {
      done: true,
      text: `Szkic${version.ai_used ? " z asystentem" : ""} — ${version.created_by_name ?? "autor"}${
        version.created_at ? `, ${formatDateTimePl(version.created_at)}` : ""
      }`,
    },
    {
      done: version.status !== "draft",
      text: version.submitted_at
        ? `Zgłoszony — ${version.submitted_by_name ?? ""}, ${formatDateTimePl(version.submitted_at)}`
        : "Zgłoszenie do zatwierdzenia",
    },
    {
      done: version.status === "approved" || version.status === "withdrawn",
      text:
        version.status === "approved" && version.reviewed_at
          ? `Zatwierdził ${version.reviewed_by_name ?? "administrator"}, ${formatDateTimePl(version.reviewed_at)}`
          : "Zatwierdza administrator",
    },
    {
      done: version.status === "approved" && !detail.withdrawn_at,
      text: detail.withdrawn_at
        ? `Wycofany — ${detail.withdrawn_by_name ?? ""}: ${detail.withdrawn_reason ?? ""}`
        : "Wzór pojawia się w „Nowy dokument” dla wszystkich",
    },
  ];
  const current = items.findIndex((i) => !i.done);
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3">
      <div className="mb-2 text-[12.5px] font-semibold">Zatwierdzenie</div>
      <ol className="space-y-1 text-[12.5px]">
        {items.map((item, n) => (
          <li
            key={item.text}
            className={cn(
              "flex items-center gap-1.5",
              n === current ? "font-medium" : !item.done && "text-muted-foreground",
            )}
          >
            {item.done ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden="true" />
            ) : (
              <Circle className={cn("h-3.5 w-3.5", n === current && "text-primary")} aria-hidden="true" />
            )}
            {item.text}
          </li>
        ))}
      </ol>
      {detail.active && detail.working ? (
        <p className="mt-2 text-[12px] text-muted-foreground">
          Do zatwierdzenia działa wersja v{detail.active.version_no}.
        </p>
      ) : null}
    </div>
  );
}

export function CustomTemplateCard({
  name,
  description,
  versionNo,
  approvedAt,
}: {
  name: string;
  description?: string | null;
  versionNo: number;
  approvedAt?: string | null;
}) {
  return (
    <div className="flex flex-col items-start gap-1 rounded-lg border border-border bg-card p-3 text-left">
      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
        <FileText className="h-4 w-4 text-primary" aria-hidden="true" />
        {name}
      </span>
      {description ? <span className="text-xs text-muted-foreground">{description}</span> : null}
      <span className="mt-1 flex flex-wrap gap-1">
        <Badge variant="soft" size="sm">
          Wzór własny v{versionNo}
        </Badge>
        {approvedAt ? (
          <Badge variant="success" size="sm">
            zatwierdzony {formatDateTimePl(approvedAt).split(",")[0]}
          </Badge>
        ) : null}
      </span>
    </div>
  );
}
