"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
  AUDIENCE_ASSIGNEES,
  AUDIENCE_LABELS,
  CATEGORY_LABELS,
  useCatchUpTemplate,
  useLifecycleTemplates,
  useSaveTemplate,
  type AssigneeKind,
  type Audience,
  type CaseKind,
  type EquipmentCondition,
  type ItemConditions,
  type LifecycleTemplate,
  type TaskCategory,
  type TemplateItem,
} from "@/lib/api/hr-lifecycle";
import { countPl } from "@/lib/plural-pl";
import { isForbiddenError, resolveViewState } from "@/lib/view-state";

import { behindLabel, conditionSummary, formatOffset } from "./lifecycle-format";

const KIND_LABELS: Record<CaseKind, string> = {
  onboarding: "Wejście",
  offboarding: "Odejście",
};
const ANY = "any";
const FORMS = Object.keys(EMPLOYMENT_TYPE_LABELS) as EmploymentType[];
const FORM_SHORT: Record<EmploymentType, string> = { uop: "UoP", b2b: "B2B", zlecenie: "Zlecenie" };

interface Draft {
  id?: number;
  kind: CaseKind;
  audience: Audience;
  version: number;
  name: string;
  is_active: boolean;
  employment_type: EmploymentType | null;
  department: string | null;
  items: TemplateItem[];
}

function emptyItem(audience: Audience): TemplateItem {
  return {
    title: "",
    category: "other",
    assignee_kind: audience === "consultant" ? "care_owner" : "people_admin",
    due_offset_days: 0,
    description: null,
    required: true,
    requires_file: false,
    conditions: {},
  };
}

function toDraft(template: LifecycleTemplate): Draft {
  return {
    id: template.id,
    kind: template.kind,
    audience: template.audience ?? "team",
    version: template.version ?? 1,
    name: template.name,
    is_active: template.is_active,
    employment_type: template.employment_type,
    department: template.department,
    items: template.items.map((item) => ({ ...item, conditions: { ...item.conditions } })),
  };
}

function newDraft(kind: CaseKind, audience: Audience): Draft {
  return {
    kind,
    audience,
    version: 0,
    name: "",
    is_active: true,
    employment_type: null,
    department: null,
    items: [emptyItem(audience)],
  };
}

/**
 * Ustawienia → Kadry: „Ścieżki wejścia i odejścia” (etap 3, M4). Ścieżka ma
 * odbiorców (zespół wewnętrzny albo konsultant u klienta), wersję i pozycje
 * z terminem, wykonawcą (rolą), warunkiem i „wymagane”. Kadry zmieniają
 * ścieżki zespołu, head back office — konsultanta, admin — wszystkie (serwer
 * mówi `can_edit`). Zapis to nowa wersja: nowe sprawy dostają ją od razu,
 * trwające — po „Dociągnij”.
 */
export function LifecycleTemplatesCard(_props: { config?: HrConfig }) {
  const templates = useLifecycleTemplates(null);
  const [selected, setSelected] = useState<Draft | null>(null);

  if (isForbiddenError(templates.error)) return null;
  const rows = templates.data ?? [];
  const state = resolveViewState({
    isLoading: templates.isLoading,
    error: templates.error,
    isSuccess: templates.isSuccess,
    isEmpty: rows.length === 0,
  });
  const editable = new Set(rows.filter((row) => row.can_edit).map((row) => row.audience ?? "team"));
  const current =
    selected?.id != null ? rows.find((row) => row.id === selected.id) ?? null : null;

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">Ścieżki wejścia i odejścia</h2>
          <p className="text-sm text-muted-foreground">
            Termin w dniach roboczych od startu albo ostatniego dnia. Wykonawca to rola, nie osoba.
            Warunek zamiast osobnej ścieżki: pozycja pojawia się tylko tam, gdzie pasuje.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["team", "consultant"] as Audience[])
            .filter((audience) => editable.has(audience))
            .flatMap((audience) =>
              (Object.keys(KIND_LABELS) as CaseKind[]).map((kind) => (
                <Button
                  key={`${audience}-${kind}`}
                  size="sm"
                  variant="outline"
                  onClick={() => setSelected(newDraft(kind, audience))}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {KIND_LABELS[kind]} · {AUDIENCE_LABELS[audience].toLowerCase()}
                </Button>
              )),
            )}
        </div>
      </div>
      {state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => templates.refetch()} />
      ) : state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
          <PathList
            rows={rows}
            selectedId={selected?.id ?? null}
            onSelect={(row) => setSelected(toDraft(row))}
          />
          {selected ? (
            <PathEditor
              key={`${selected.id ?? "new"}-${selected.kind}-${selected.audience}-${selected.version}`}
              draft={selected}
              template={current}
              canEdit={selected.id == null ? true : Boolean(current?.can_edit)}
              onSaved={(saved) => setSelected(toDraft(saved))}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              {state === "empty" ? "Brak ścieżek." : "Wybierz ścieżkę z listy."}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function PathList({
  rows,
  selectedId,
  onSelect,
}: {
  rows: LifecycleTemplate[];
  selectedId: number | null;
  onSelect: (row: LifecycleTemplate) => void;
}) {
  return (
    <nav aria-label="Ścieżki" className="space-y-3">
      {(Object.keys(KIND_LABELS) as CaseKind[]).map((kind) => (
        <div key={kind} className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {KIND_LABELS[kind]}
          </p>
          {rows
            .filter((row) => row.kind === kind)
            .map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => onSelect(row)}
                aria-current={row.id === selectedId ? "true" : undefined}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                  row.id === selectedId
                    ? "border-primary bg-primary/10"
                    : "border-border bg-card hover:bg-muted/50"
                }`}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className={row.is_active ? "font-medium text-foreground" : "text-muted-foreground"}>
                    {row.name}
                  </span>
                  <span className="text-xs text-muted-foreground">v{row.version ?? 1}</span>
                </span>
                <span className="block text-xs text-muted-foreground">
                  {AUDIENCE_LABELS[row.audience ?? "team"]} ·{" "}
                  {countPl(row.items.length, "pozycja", "pozycje", "pozycji")}
                  {row.is_active ? "" : " · wyłączona"}
                </span>
              </button>
            ))}
        </div>
      ))}
    </nav>
  );
}

function PathEditor({
  draft,
  template,
  canEdit,
  onSaved,
}: {
  draft: Draft;
  template: LifecycleTemplate | null;
  canEdit: boolean;
  onSaved: (saved: LifecycleTemplate) => void;
}) {
  const { showToast } = useToast();
  const save = useSaveTemplate();
  const catchUp = useCatchUpTemplate();
  const [value, setValue] = useState<Draft>(draft);
  const [error, setError] = useState<string | null>(null);
  const assignees = AUDIENCE_ASSIGNEES[value.audience];

  const setItem = (index: number, patch: Partial<TemplateItem>) =>
    setValue((current) => ({
      ...current,
      items: current.items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    }));
  const setConditions = (index: number, patch: Partial<ItemConditions>) =>
    setValue((current) => ({
      ...current,
      items: current.items.map((item, i) =>
        i === index ? { ...item, conditions: { ...item.conditions, ...patch } } : item,
      ),
    }));

  const submit = () => {
    setError(null);
    if (!value.name.trim()) {
      setError("Podaj nazwę ścieżki.");
      return;
    }
    save.mutate(
      {
        id: value.id,
        kind: value.kind,
        audience: value.audience,
        name: value.name.trim(),
        is_active: value.is_active,
        employment_type: value.employment_type,
        department: value.department?.trim() || null,
        items: value.items
          .filter((item) => item.title.trim())
          .map((item) => ({
            // Id pozycji: zapis zmienia ją w miejscu, zadania w sprawach zostają przypięte.
            id: item.id,
            title: item.title.trim(),
            category: item.category,
            assignee_kind: item.assignee_kind,
            due_offset_days: item.due_offset_days,
            description: item.description?.trim() || null,
            required: item.required ?? true,
            requires_file: item.requires_file ?? false,
            conditions: {
              employment_types: item.conditions?.employment_types ?? [],
              equipment: item.conditions?.equipment ?? null,
              student: item.conditions?.student ? true : null,
            },
          })),
      },
      {
        onSuccess: (saved) => {
          showToast(`Ścieżka zapisana jako wersja ${saved.version ?? 1}`, "success");
          onSaved(saved);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać ścieżki.")),
      },
    );
  };

  const behind = template?.live_cases_behind ?? 0;

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[220px] flex-1 space-y-1 text-sm">
          <span className="text-muted-foreground">Nazwa ścieżki</span>
          <Input
            value={value.name}
            maxLength={160}
            disabled={!canEdit}
            onChange={(event) => setValue({ ...value, name: event.target.value })}
          />
        </label>
        {value.audience === "team" ? (
          <label className="w-40 space-y-1 text-sm">
            <span className="text-muted-foreground">Forma</span>
            <Select
              value={value.employment_type ?? ANY}
              disabled={!canEdit}
              onValueChange={(next) =>
                setValue({ ...value, employment_type: next === ANY ? null : (next as EmploymentType) })
              }
            >
              <SelectTrigger aria-label="Forma zatrudnienia ścieżki">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Każda</SelectItem>
                {FORMS.map((key) => (
                  <SelectItem key={key} value={key}>
                    {EMPLOYMENT_TYPE_LABELS[key]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        ) : null}
        <label className="flex items-center gap-2 pb-2 text-sm">
          <Switch
            checked={value.is_active}
            disabled={!canEdit}
            onCheckedChange={(checked) => setValue({ ...value, is_active: checked })}
            aria-label="Ścieżka w użyciu"
          />
          <span>W użyciu</span>
        </label>
      </div>
      <p className="text-xs text-muted-foreground">
        {AUDIENCE_LABELS[value.audience]}
        {value.id != null ? ` · wersja ${value.version}` : " · nowa ścieżka"}
        {value.audience === "consultant"
          ? " · pakiet klienta dokłada dokumenty, dostępy i odbiór rzeczy od klienta przy każdym kontrakcie"
          : ""}
        {canEdit ? "" : " · tylko do odczytu"}
      </p>
      <div className="overflow-hidden rounded-lg border border-border">
        <div className="grid grid-cols-[96px_minmax(0,1fr)_128px_72px_32px] gap-2 border-b border-border bg-muted/40 px-2 py-1.5 text-xs font-medium text-muted-foreground">
          <span>Kiedy</span>
          <span>Co · warunek</span>
          <span>Kto</span>
          <span>Wymagane</span>
          <span />
        </div>
        {value.items.map((item, index) => (
          <ItemRow
            key={item.id ?? `new-${index}`}
            item={item}
            index={index}
            kind={value.kind}
            assignees={assignees}
            canEdit={canEdit}
            onChange={(patch) => setItem(index, patch)}
            onConditions={(patch) => setConditions(index, patch)}
            onRemove={() =>
              setValue({ ...value, items: value.items.filter((_, i) => i !== index) })
            }
          />
        ))}
      </div>
      {canEdit ? (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setValue({ ...value, items: [...value.items, emptyItem(value.audience)] })}
        >
          <Plus className="h-4 w-4" aria-hidden />
          Dodaj pozycję
        </Button>
      ) : null}
      {behind > 0 && template ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
          <span>
            {behindLabel(behind, value.kind)} Możesz dociągnąć do nich nowe pozycje albo zostawić
            bez zmian.
          </span>
          {canEdit ? (
            <Button
              size="sm"
              variant="outline"
              disabled={catchUp.isPending}
              onClick={() =>
                catchUp.mutate(template.id, {
                  onSuccess: (result) =>
                    showToast(
                      `Dociągnięte: ${countPl(result.tasks, "pozycja", "pozycje", "pozycji")} w ${countPl(result.cases, "sprawie", "sprawach", "sprawach")}`,
                      "success",
                    ),
                  onError: (err) =>
                    showToast(apiErrorMessage(err, "Nie udało się dociągnąć pozycji."), "error"),
                })
              }
            >
              Dociągnij do trwających
            </Button>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {canEdit ? (
        <div className="flex justify-end">
          <Button disabled={save.isPending} onClick={submit}>
            {value.id != null ? `Zapisz jako wersję ${value.version + 1}` : "Zapisz ścieżkę"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ItemRow({
  item,
  index,
  kind,
  assignees,
  canEdit,
  onChange,
  onConditions,
  onRemove,
}: {
  item: TemplateItem;
  index: number;
  kind: CaseKind;
  assignees: AssigneeKind[];
  canEdit: boolean;
  onChange: (patch: Partial<TemplateItem>) => void;
  onConditions: (patch: Partial<ItemConditions>) => void;
  onRemove: () => void;
}) {
  const forms = item.conditions?.employment_types ?? [];
  const options = assignees.includes(item.assignee_kind)
    ? assignees
    : [item.assignee_kind, ...assignees];
  const label = item.title || `pozycja ${index + 1}`;
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)_128px_72px_32px] items-start gap-2 border-b border-border/60 px-2 py-2 last:border-b-0">
      <div className="space-y-1">
        <Input
          type="number"
          min={-60}
          max={120}
          value={item.due_offset_days}
          disabled={!canEdit}
          aria-label={`Termin w dniach roboczych: ${label}`}
          onChange={(event) => onChange({ due_offset_days: Number(event.target.value) || 0 })}
        />
        <p className="text-[11px] leading-tight text-muted-foreground">
          {formatOffset(kind, item.due_offset_days)}
        </p>
      </div>
      <div className="min-w-0 space-y-1">
        <Input
          value={item.title}
          maxLength={200}
          disabled={!canEdit}
          aria-label={`Co: ${label}`}
          onChange={(event) => onChange({ title: event.target.value })}
        />
        <Input
          value={item.description ?? ""}
          maxLength={500}
          disabled={!canEdit}
          placeholder="Opis (opcjonalnie)"
          aria-label={`Opis: ${label}`}
          onChange={(event) => onChange({ description: event.target.value })}
        />
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>Warunek:</span>
            {FORMS.map((form) => (
              <label key={form} className="flex items-center gap-1">
                <Checkbox
                  checked={forms.includes(form)}
                  aria-label={`${FORM_SHORT[form]}: ${label}`}
                  onCheckedChange={(checked) =>
                    onConditions({
                      employment_types:
                        checked === true ? [...forms, form] : forms.filter((f) => f !== form),
                    })
                  }
                />
                {FORM_SHORT[form]}
              </label>
            ))}
            <Select
              value={item.conditions?.equipment ?? ANY}
              onValueChange={(next) =>
                onConditions({ equipment: next === ANY ? null : (next as EquipmentCondition) })
              }
            >
              <SelectTrigger className="h-7 w-36 text-xs" aria-label={`Sprzęt: ${label}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>sprzęt: każdy</SelectItem>
                <SelectItem value="ours">sprzęt od nas</SelectItem>
                <SelectItem value="client">sprzęt od klienta</SelectItem>
              </SelectContent>
            </Select>
            <label className="flex items-center gap-1">
              <Checkbox
                checked={Boolean(item.conditions?.student)}
                aria-label={`Student: ${label}`}
                onCheckedChange={(checked) => onConditions({ student: checked === true })}
              />
              student
            </label>
            <label className="flex items-center gap-1">
              <Checkbox
                checked={Boolean(item.requires_file)}
                aria-label={`Wymaga pliku: ${label}`}
                onCheckedChange={(checked) => onChange({ requires_file: checked === true })}
              />
              z plikiem
            </label>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            {[conditionSummary(item.conditions) || "zawsze", item.requires_file ? "z plikiem" : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
      </div>
      <div className="space-y-1">
        <Select
          value={item.assignee_kind}
          disabled={!canEdit}
          onValueChange={(next) => onChange({ assignee_kind: next as AssigneeKind })}
        >
          <SelectTrigger aria-label={`Kto: ${label}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((key) => (
              <SelectItem key={key} value={key}>
                {ASSIGNEE_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={item.category}
          disabled={!canEdit}
          onValueChange={(next) => onChange({ category: next as TaskCategory })}
        >
          <SelectTrigger className="h-7 text-xs" aria-label={`Kategoria: ${label}`}>
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
      </div>
      <div className="flex justify-center pt-2">
        <Checkbox
          checked={item.required ?? true}
          disabled={!canEdit}
          aria-label={`Wymagane: ${label}`}
          onCheckedChange={(checked) => onChange({ required: checked === true })}
        />
      </div>
      {canEdit && !item.key ? (
        <Button variant="quiet" size="icon" aria-label={`Usuń pozycję ${label}`} onClick={onRemove}>
          <Trash2 className="h-4 w-4" aria-hidden />
        </Button>
      ) : (
        <span
          className="pt-2 text-center text-[11px] text-muted-foreground"
          title={item.key ? "Pozycję czytają inne moduły — można ją zmienić, nie usunąć." : undefined}
        >
          {item.key ? "stała" : ""}
        </span>
      )}
    </div>
  );
}
