"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
import { apiErrorMessage } from "@/lib/api-error";
import { EMPLOYMENT_TYPE_LABELS, type EmploymentType, type HrConfig } from "@/lib/api/hr";
import {
  ASSIGNEE_LABELS,
  CATEGORY_LABELS,
  useLifecycleTemplates,
  useSaveTemplate,
  type AssigneeKind,
  type CaseKind,
  type LifecycleTemplate,
  type TaskCategory,
  type TemplateItem,
} from "@/lib/api/hr-lifecycle";
import { resolveViewState } from "@/lib/view-state";

import { formatOffset } from "./lifecycle-format";

const ANY = "any";
const KIND_LABELS: Record<CaseKind, string> = {
  onboarding: "Wejście",
  offboarding: "Odejście",
};

interface Draft {
  id?: number;
  kind: CaseKind;
  name: string;
  is_active: boolean;
  employment_type: EmploymentType | null;
  department: string;
  items: TemplateItem[];
}

function emptyDraft(kind: CaseKind): Draft {
  return {
    kind,
    name: "",
    is_active: true,
    employment_type: null,
    department: "",
    items: [{ title: "", category: "other", assignee_kind: "people_admin", due_offset_days: 0 }],
  };
}

function toDraft(template: LifecycleTemplate): Draft {
  return {
    id: template.id,
    kind: template.kind,
    name: template.name,
    is_active: template.is_active,
    employment_type: template.employment_type,
    department: template.department ?? "",
    items: template.items.map((item) => ({ ...item })),
  };
}

/**
 * Ustawienia → Kadry: listy zadań wejścia i odejścia (wpina koordynator
 * w `/settings/hr`). Zmiana listy nie rusza spraw już założonych.
 */
export function LifecycleTemplatesCard({ config }: { config: HrConfig }) {
  const canManage = config.me.people_admin || config.me.is_admin;
  const templates = useLifecycleTemplates(null, canManage);
  const [draft, setDraft] = useState<Draft | null>(null);

  if (!canManage) return null;
  const state = resolveViewState({
    isLoading: templates.isLoading,
    isError: templates.isError,
    error: templates.error,
    isSuccess: templates.isSuccess,
    isEmpty: (templates.data ?? []).length === 0,
  });

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Wejście i odejście — listy zadań</h2>
          <p className="text-sm text-muted-foreground">
            Terminy w dniach roboczych od startu albo ostatniego dnia pracy. Lista z formą
            zatrudnienia albo działem wygrywa z ogólną.
          </p>
        </div>
        <div className="flex gap-2">
          {(Object.keys(KIND_LABELS) as CaseKind[]).map((kind) => (
            <Button key={kind} size="sm" variant="outline" onClick={() => setDraft(emptyDraft(kind))}>
              <Plus className="h-4 w-4" aria-hidden />
              {KIND_LABELS[kind]}
            </Button>
          ))}
        </div>
      </div>
      {state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => templates.refetch()} />
      ) : state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">Brak list zadań.</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {(templates.data ?? []).map((template) => (
            <li key={template.id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
              <span className={template.is_active ? "text-foreground" : "text-muted-foreground"}>
                <span className="font-medium">{template.name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  · {KIND_LABELS[template.kind]} · {template.items.length} zadań
                  {template.employment_type
                    ? ` · ${EMPLOYMENT_TYPE_LABELS[template.employment_type]}`
                    : ""}
                  {template.department ? ` · ${template.department}` : ""}
                  {template.is_active ? "" : " · wyłączona"}
                </span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => setDraft(toDraft(template))}>
                Edytuj
              </Button>
            </li>
          ))}
        </ul>
      )}
      {draft ? (
        <TemplateEditor draft={draft} onClose={() => setDraft(null)} />
      ) : null}
    </Card>
  );
}

function TemplateEditor({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const { showToast } = useToast();
  const save = useSaveTemplate();
  const [value, setValue] = useState<Draft>(draft);
  const [error, setError] = useState<string | null>(null);

  const setItem = (index: number, patch: Partial<TemplateItem>) =>
    setValue((current) => ({
      ...current,
      items: current.items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    }));

  const submit = () => {
    setError(null);
    if (!value.name.trim()) {
      setError("Podaj nazwę listy.");
      return;
    }
    const items = value.items.filter((item) => item.title.trim());
    save.mutate(
      {
        id: value.id,
        kind: value.kind,
        name: value.name.trim(),
        is_active: value.is_active,
        employment_type: value.employment_type,
        department: value.department.trim() || null,
        items: items.map((item) => ({
          title: item.title.trim(),
          category: item.category,
          assignee_kind: item.assignee_kind,
          due_offset_days: item.due_offset_days,
        })),
      },
      {
        onSuccess: () => {
          showToast("Lista zadań zapisana", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać listy.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`${value.id ? "Lista" : "Nowa lista"}: ${KIND_LABELS[value.kind].toLowerCase()}`}
      description="Termin: liczba dni roboczych (ujemna = przed datą sprawy)."
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Nazwa" htmlFor="tpl-name" required>
            <Input
              id="tpl-name"
              value={value.name}
              maxLength={160}
              onChange={(event) => setValue({ ...value, name: event.target.value })}
            />
          </FormField>
          <FormField label="Forma zatrudnienia" htmlFor="tpl-type">
            <Select
              value={value.employment_type ?? ANY}
              onValueChange={(next) =>
                setValue({
                  ...value,
                  employment_type: next === ANY ? null : (next as EmploymentType),
                })
              }
            >
              <SelectTrigger id="tpl-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Każda</SelectItem>
                {(Object.keys(EMPLOYMENT_TYPE_LABELS) as EmploymentType[]).map((key) => (
                  <SelectItem key={key} value={key}>
                    {EMPLOYMENT_TYPE_LABELS[key]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Dział (opcjonalnie)" htmlFor="tpl-dept">
            <Input
              id="tpl-dept"
              value={value.department}
              maxLength={200}
              onChange={(event) => setValue({ ...value, department: event.target.value })}
            />
          </FormField>
        </div>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>Lista w użyciu</span>
          <Switch
            checked={value.is_active}
            onCheckedChange={(checked) => setValue({ ...value, is_active: checked })}
            aria-label="Lista w użyciu"
          />
        </label>
        <div className="space-y-2">
          {value.items.map((item, index) => (
            <div key={index} className="grid items-end gap-2 sm:grid-cols-[1fr_130px_130px_90px_auto]">
              <FormField label={index === 0 ? "Zadanie" : undefined} htmlFor={`tpl-title-${index}`}>
                <Input
                  id={`tpl-title-${index}`}
                  value={item.title}
                  maxLength={200}
                  onChange={(event) => setItem(index, { title: event.target.value })}
                />
              </FormField>
              <FormField label={index === 0 ? "Kategoria" : undefined}>
                <Select
                  value={item.category}
                  onValueChange={(next) => setItem(index, { category: next as TaskCategory })}
                >
                  <SelectTrigger aria-label="Kategoria">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(CATEGORY_LABELS) as TaskCategory[]).map((key) => (
                      <SelectItem key={key} value={key}>
                        {CATEGORY_LABELS[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField label={index === 0 ? "Wykonuje" : undefined}>
                <Select
                  value={item.assignee_kind}
                  onValueChange={(next) => setItem(index, { assignee_kind: next as AssigneeKind })}
                >
                  <SelectTrigger aria-label="Wykonuje">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(ASSIGNEE_LABELS) as AssigneeKind[]).map((key) => (
                      <SelectItem key={key} value={key}>
                        {ASSIGNEE_LABELS[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField
                label={index === 0 ? "Termin" : undefined}
                htmlFor={`tpl-offset-${index}`}
              >
                <Input
                  id={`tpl-offset-${index}`}
                  type="number"
                  min={-60}
                  max={120}
                  value={item.due_offset_days}
                  title={formatOffset(value.kind, item.due_offset_days)}
                  onChange={(event) =>
                    setItem(index, { due_offset_days: Number(event.target.value) || 0 })
                  }
                />
              </FormField>
              <Button
                variant="quiet"
                size="icon"
                aria-label={`Usuń zadanie ${item.title || index + 1}`}
                onClick={() =>
                  setValue({ ...value, items: value.items.filter((_, i) => i !== index) })
                }
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ))}
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              setValue({
                ...value,
                items: [
                  ...value.items,
                  { title: "", category: "other", assignee_kind: "people_admin", due_offset_days: 0 },
                ],
              })
            }
          >
            <Plus className="h-4 w-4" aria-hidden />
            Dodaj zadanie
          </Button>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
