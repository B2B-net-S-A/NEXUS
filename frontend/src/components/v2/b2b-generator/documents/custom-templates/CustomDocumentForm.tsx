"use client";

// Dokument ze wzoru własnego w kreatorze „Nowy dokument”: dla kogo
// (kandydat w rekrutacji albo sam klient), pola z listy wzoru, podgląd
// i DOCX. Dokument trafia do „Dokumenty do umów” bez skutków w kontraktach.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Eye, Loader2, Plus, Trash2 } from "lucide-react";

import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { B2B_DOCUMENTS_KEY, b2bDocumentsApi } from "@/lib/api/b2bDocuments";
import {
  customTemplatesApi,
  customTemplatesKeys,
  type CustomDocumentType,
  type CustomFieldDef,
  type CustomValue,
  type CustomValues,
} from "@/lib/api/customTemplates";
import { groupFields, invalidFieldKeys, offeredForClient } from "@/lib/custom-templates";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

import { saveDocx } from "../DocumentDialogs";

interface Subject {
  candidateId: number | null;
  candidateLabel: string | null;
  jobId: number | null;
  jobLabel: string | null;
  clientId: number | null;
  clientName: string | null;
}

const EMPTY: Subject = {
  candidateId: null,
  candidateLabel: null,
  jobId: null,
  jobLabel: null,
  clientId: null,
  clientName: null,
};

export function CustomDocumentForm({
  type,
  onBack,
  onClose,
}: {
  type: CustomDocumentType;
  onBack: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState<Subject>(EMPTY);
  const [mode, setMode] = useState<"candidate" | "client">("candidate");
  const [values, setValues] = useState<CustomValues>({});
  const [initialized, setInitialized] = useState<string | null>(null);
  const [errors, setErrors] = useState<Set<string>>(new Set());
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const prefill = useQuery({
    queryKey: customTemplatesKeys.prefill(type.template_id, subject.candidateId, subject.jobId),
    queryFn: () =>
      customTemplatesApi.prefill(type.template_id, subject.candidateId, subject.jobId),
    enabled: subject.candidateId === null || subject.jobId !== null,
    staleTime: 0,
  });
  const initKey = `${subject.candidateId}|${subject.jobId}`;
  useEffect(() => {
    if (!prefill.data || initialized === initKey) return;
    // Prefill uzupełnia tylko puste pola — wpisanego przez człowieka nie nadpisuje.
    setValues((prev) => {
      const next = { ...prev };
      for (const [k, v] of Object.entries(prefill.data.values)) {
        if (next[k] === undefined || next[k] === "") next[k] = v;
      }
      return next;
    });
    setInitialized(initKey);
  }, [prefill.data, initKey, initialized]);

  const body = () => ({
    values,
    candidate_id: mode === "candidate" ? subject.candidateId : null,
    job_id: mode === "candidate" ? subject.jobId : null,
    client_id: mode === "client" ? subject.clientId : null,
  });
  const clientOk =
    type.client_scope === "all" ||
    (mode === "client" && offeredForClient(type, subject.clientId)) ||
    mode === "candidate";
  const validate = (): boolean => {
    const bad = invalidFieldKeys(type.fields, values);
    setErrors(new Set(bad));
    if (bad.length) {
      toast.showError("Uzupełnij zaznaczone pola.");
      return false;
    }
    if (mode === "candidate" && subject.candidateId !== null && subject.jobId === null) {
      toast.showError("Wybierz rekrutację kandydata.");
      return false;
    }
    if (type.client_scope === "selected" && mode === "client" && !offeredForClient(type, subject.clientId)) {
      toast.showError("Ten wzór jest tylko dla wybranych klientów — wskaż jednego z nich.");
      return false;
    }
    return true;
  };
  const preview = useMutation({
    mutationFn: () => customTemplatesApi.preview(type.template_id, body()),
    onSuccess: (data) => setPreviewHtml(data.html),
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się przygotować podglądu.")),
  });
  const create = useMutation({
    mutationFn: () => customTemplatesApi.createDocument(type.template_id, body()),
    onSuccess: (res) => {
      saveDocx(res as { data: unknown; headers: Record<string, unknown> }, "dokument.docx");
      void queryClient.invalidateQueries({ queryKey: [B2B_DOCUMENTS_KEY] });
      toast.showSuccess("Dokument zapisany w „Dokumenty do umów”.");
      onClose();
    },
    onError: (err) => toast.showError(apiErrorMessage(err, "Nie udało się wystawić dokumentu.")),
  });
  const groups = useMemo(() => groupFields(type.fields), [type.fields]);
  const set = (key: string, value: CustomValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="mr-1 h-4 w-4" aria-hidden="true" />
          Zmień rodzaj dokumentu
        </Button>
        <Badge variant="soft">Wzór własny v{type.version_no}</Badge>
        <span className="text-xs text-muted-foreground">
          Bez skutków w kontraktach — dokument trafi do listy „Dokumenty do umów”.
        </span>
      </div>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Dla kogo</h3>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Dla kogo">
          {(
            [
              ["candidate", "Kandydat w rekrutacji"],
              ["client", "Klient (bez kandydata)"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              onClick={() => setMode(value)}
              className={cn(
                "inline-flex h-7 items-center rounded-full border px-2.5 text-[12px]",
                mode === value ? "border-primary bg-primary/10 font-medium" : "border-border text-muted-foreground hover:bg-muted",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {mode === "candidate" ? (
          <CandidateJobPicker subject={subject} onSubject={setSubject} />
        ) : (
          <div className="max-w-sm space-y-1">
            <Label>Klient{type.client_scope === "selected" ? " *" : ""}</Label>
            <ClientSinglePicker
              queryKey="custom-document-clients"
              selectableOnly
              value={subject.clientId !== null ? { id: subject.clientId, name: subject.clientName ?? "" } : null}
              onChange={(client) =>
                setSubject({ ...subject, clientId: client?.id ?? null, clientName: client?.name ?? null })
              }
            />
            {!clientOk ? (
              <p className="text-xs text-destructive">Ten wzór jest tylko dla wybranych klientów.</p>
            ) : null}
          </div>
        )}
      </section>

      {groups.map((g) => (
        <section key={g.group} className="space-y-3">
          <h3 className="text-sm font-semibold">{g.group}</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {g.fields.map((f) => (
              <CustomFieldInput
                key={f.key}
                field={f}
                value={values[f.key]}
                invalid={errors.has(f.key)}
                onChange={(v) => set(f.key, v)}
              />
            ))}
          </div>
        </section>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          loading={preview.isPending}
          onClick={() => {
            if (validate()) preview.mutate();
          }}
        >
          <Eye className="mr-1 h-4 w-4" aria-hidden="true" />
          Podgląd
        </Button>
        <Button
          loading={create.isPending}
          onClick={() => {
            if (validate()) create.mutate();
          }}
        >
          <Download className="mr-1 h-4 w-4" aria-hidden="true" />
          Pobierz DOCX
        </Button>
      </div>
      {previewHtml !== null ? (
        // sandbox="" — podgląd bez skryptów, formularzy i nawigacji.
        <iframe
          title="Podgląd dokumentu"
          sandbox=""
          srcDoc={previewHtml}
          className="h-[70dvh] w-full rounded-lg border border-border bg-card"
        />
      ) : null}
    </div>
  );
}

function CustomFieldInput({
  field,
  value,
  invalid,
  onChange,
}: {
  field: CustomFieldDef;
  value: CustomValue | undefined;
  invalid: boolean;
  onChange: (value: CustomValue) => void;
}) {
  const id = `custom-doc-${field.key}`;
  const label = (
    <Label htmlFor={id}>
      {field.label}
      {field.required ? " *" : ""}
      {field.source !== "manual" ? (
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">({field.source_label})</span>
      ) : null}
    </Label>
  );
  const text = typeof value === "string" || typeof value === "number" ? String(value) : "";
  const cls = invalid ? "border-destructive" : undefined;
  if (field.kind === "list") {
    return (
      <div className="space-y-1 md:col-span-2">
        {label}
        <ListInput field={field} value={Array.isArray(value) ? value : []} onChange={onChange} />
      </div>
    );
  }
  if (field.kind === "bool") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    );
  }
  if (field.kind === "gender") {
    return (
      <div className="space-y-1">
        {label}
        <select
          id={id}
          className={cn("flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm", cls)}
          value={text || "m"}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="m">Pan (formy męskie)</option>
          <option value="k">Pani (formy żeńskie)</option>
        </select>
      </div>
    );
  }
  if (field.kind === "select") {
    return (
      <div className="space-y-1">
        {label}
        <select
          id={id}
          className={cn("flex h-9 w-full rounded-md border border-border bg-card px-3 text-sm", cls)}
          value={text}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">—</option>
          {field.options.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (field.kind === "textarea") {
    return (
      <div className="space-y-1 md:col-span-2">
        {label}
        <Textarea id={id} rows={3} className={cls} value={text} onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {label}
      <Input
        id={id}
        type={field.kind === "date" ? "date" : field.kind === "email" ? "email" : "text"}
        inputMode={field.kind === "money" ? "decimal" : undefined}
        className={cls}
        value={text}
        placeholder={field.kind === "money" ? "np. 6200,00 (słownie wpisze NEXUS)" : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.help ? <p className="text-xs text-muted-foreground">{field.help}</p> : null}
    </div>
  );
}

function ListInput({
  field,
  value,
  onChange,
}: {
  field: CustomFieldDef;
  value: Record<string, string>[] | string[];
  onChange: (value: CustomValue) => void;
}) {
  const keys = field.item_keys;
  const rows = value as (Record<string, string> | string)[];
  const update = (n: number, next: Record<string, string> | string) =>
    onChange(rows.map((r, i) => (i === n ? next : r)) as CustomValue);
  return (
    <div className="space-y-1.5">
      {rows.map((row, n) => (
        <div key={n} className="flex items-center gap-1.5">
          {keys.length === 0 ? (
            <Input
              aria-label={`${field.label} ${n + 1}`}
              value={typeof row === "string" ? row : ""}
              onChange={(e) => update(n, e.target.value)}
            />
          ) : (
            keys.map((k) => (
              <Input
                key={k.key}
                aria-label={`${k.label} ${n + 1}`}
                placeholder={k.label}
                className={k.key === "no" ? "w-16" : undefined}
                value={typeof row === "string" ? "" : (row[k.key] ?? "")}
                onChange={(e) =>
                  update(n, { ...(typeof row === "string" ? {} : row), [k.key]: e.target.value })
                }
              />
            ))
          )}
          <Button
            variant="quiet"
            size="sm"
            aria-label="Usuń pozycję"
            onClick={() => onChange(rows.filter((_, i) => i !== n) as CustomValue)}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        disabled={rows.length >= 30}
        onClick={() =>
          onChange([
            ...rows,
            keys.length === 0
              ? ""
              : Object.fromEntries(
                  keys.map((k) => [k.key, k.key === "no" ? String(rows.length + 1) : ""]),
                ),
          ] as CustomValue)
        }
      >
        <Plus className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
        Dodaj pozycję
      </Button>
    </div>
  );
}

function CandidateJobPicker({
  subject,
  onSubject,
}: {
  subject: Subject;
  onSubject: (s: Subject) => void;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 300).trim();
  const candidates = useQuery({
    queryKey: [B2B_DOCUMENTS_KEY, "candidates", debounced],
    queryFn: () => b2bDocumentsApi.searchCandidates(debounced),
    enabled: debounced.length >= 2,
    staleTime: 30_000,
  });
  const recruitments = useQuery({
    queryKey: [B2B_DOCUMENTS_KEY, "recruitments", subject.candidateId ?? 0],
    queryFn: () => b2bDocumentsApi.candidateRecruitments(subject.candidateId as number),
    enabled: subject.candidateId !== null,
  });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label htmlFor="custom-doc-candidate">Kandydat (opcjonalnie)</Label>
        <Input
          id="custom-doc-candidate"
          placeholder="Imię i nazwisko (min. 2 znaki)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {subject.candidateLabel ? (
          <Badge variant="outline">{subject.candidateLabel}</Badge>
        ) : null}
        {candidates.isError ? (
          <Alert variant="error" title={apiErrorMessage(candidates.error, "Nie udało się wyszukać kandydatów.")} />
        ) : candidates.isSuccess && candidates.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak kandydatów o tym nazwisku.</p>
        ) : (
          <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border empty:hidden">
            {(candidates.data ?? []).map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  aria-pressed={subject.candidateId === c.id}
                  onClick={() =>
                    onSubject({ ...subject, candidateId: c.id, candidateLabel: c.full_name, jobId: null, jobLabel: null })
                  }
                  className={cn("w-full px-3 py-2 text-left text-sm hover:bg-muted", subject.candidateId === c.id && "bg-primary/5")}
                >
                  {c.full_name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">Rekrutacja</p>
        {subject.candidateId === null ? (
          <p className="text-sm text-muted-foreground">
            Dane Partnera podpowiemy z profilu kandydata po wybraniu rekrutacji. Bez kandydata wpiszesz je ręcznie.
          </p>
        ) : recruitments.isPending ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Wczytuję rekrutacje…
          </p>
        ) : recruitments.isError ? (
          <Alert variant="error" title={apiErrorMessage(recruitments.error, "Nie udało się wczytać rekrutacji.")} />
        ) : recruitments.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ten kandydat nie jest w żadnej rekrutacji.</p>
        ) : (
          <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
            {recruitments.data.map((r) => (
              <li key={r.stage_id}>
                <button
                  type="button"
                  aria-pressed={subject.jobId === r.job_id}
                  onClick={() => onSubject({ ...subject, jobId: r.job_id, jobLabel: r.job_title })}
                  className={cn("w-full px-3 py-2 text-left text-sm hover:bg-muted", subject.jobId === r.job_id && "bg-primary/5")}
                >
                  {r.job_title}
                  <span className="block text-xs text-muted-foreground">{r.stage}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
