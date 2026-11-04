"use client";

import { useState } from "react";
import { Search, X } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_AREAS,
  CASE_AREA_LABELS,
  useCaseAssignees,
  useCaseContractOptions,
  useCreateCase,
  useUpdateCase,
  type CaseArea,
  type CaseContractRef,
  type CaseCreateInput,
  type CaseDetail,
  type CasePriority,
} from "@/lib/api/admin-cases";
import { formatIsoDatePl } from "@/lib/date-pl";

const NONE = "none";

const PRIORITY_OPTIONS: { value: CasePriority; label: string }[] = [
  { value: "P1", label: "P1 · 2 dni" },
  { value: "P2", label: "P2 · 5 dni" },
  { value: "P3", label: "P3 · 10 dni" },
];

/** Wartości formularza sprawy (puste pole = brak wartości). */
export interface CaseFormState {
  title: string;
  area: CaseArea;
  priority: CasePriority;
  due_on: string;
  follow_up_on: string;
  assignee_user_id: string;
  subject_user_id: string;
  contract: CaseContractRef | null;
  description: string;
}

export const EMPTY_CASE_FORM: CaseFormState = {
  title: "",
  area: "administration",
  priority: "P2",
  due_on: "",
  follow_up_on: "",
  assignee_user_id: "",
  subject_user_id: "",
  contract: null,
  description: "",
};

export function caseToForm(detail: CaseDetail): CaseFormState {
  return {
    title: detail.title,
    area: detail.area,
    priority: detail.priority,
    due_on: detail.due_on ?? "",
    follow_up_on: detail.follow_up_on ?? "",
    assignee_user_id: detail.assignee ? String(detail.assignee.id) : "",
    subject_user_id: detail.subject_user ? String(detail.subject_user.id) : "",
    contract: detail.contract,
    description: detail.description ?? "",
  };
}

export function caseFormToPayload(form: CaseFormState): CaseCreateInput {
  return {
    title: form.title.trim(),
    area: form.area,
    priority: form.priority,
    due_on: form.due_on || null,
    follow_up_on: form.follow_up_on || null,
    assignee_user_id: form.assignee_user_id ? Number(form.assignee_user_id) : null,
    subject_user_id: form.subject_user_id ? Number(form.subject_user_id) : null,
    contract_id: form.contract?.id ?? null,
    description: form.description.trim() ? form.description.trim() : null,
  };
}

export function ContractPicker({
  value,
  onChange,
}: {
  value: CaseContractRef | null;
  onChange: (next: CaseContractRef | null) => void;
}) {
  const [query, setQuery] = useState("");
  const options = useCaseContractOptions(query, value === null);

  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
        <span className="min-w-0 truncate">
          <span className="font-medium text-foreground">
            {value.candidate_name ?? `Kontrakt #${value.id}`}
          </span>
          {value.client_name ? (
            <span className="text-muted-foreground"> · {value.client_name}</span>
          ) : null}
        </span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => onChange(null)}
          aria-label="Odepnij kontrakt"
        >
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    );
  }

  const items = options.data ?? [];
  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id="case-contract"
          className="pl-8"
          placeholder="Imię lub nazwisko konsultanta…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {options.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(options.error, "Nie udało się wyszukać kontraktów.")}
        </p>
      ) : null}
      {options.isSuccess && query.trim().length >= 2 && items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Brak kontraktu dla „{query.trim()}”.</p>
      ) : null}
      {items.length > 0 ? (
        <ul className="max-h-40 overflow-y-auto rounded-md border border-border">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="flex w-full items-baseline justify-between gap-3 px-3 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => {
                  onChange(item);
                  setQuery("");
                }}
              >
                <span className="min-w-0 truncate">
                  {item.candidate_name}
                  {item.client_name ? (
                    <span className="text-muted-foreground"> · {item.client_name}</span>
                  ) : null}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  od {formatIsoDatePl(item.start_date)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

interface CaseFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Bez sprawy — „Nowa sprawa”; ze sprawą — edycja. */
  existing?: CaseDetail;
  onCreated?: (id: number) => void;
}

/** „Nowa sprawa” i „Edytuj sprawę” — te same pola. */
export function CaseFormDialog({ open, onOpenChange, existing, onCreated }: CaseFormDialogProps) {
  const { showToast } = useToast();
  const assignees = useCaseAssignees(open);
  const create = useCreateCase();
  const update = useUpdateCase(existing?.id ?? 0);
  const [form, setForm] = useState<CaseFormState>(() =>
    existing ? caseToForm(existing) : EMPTY_CASE_FORM,
  );
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;
  const set = <K extends keyof CaseFormState>(key: K, value: CaseFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const close = (next: boolean) => {
    if (!next) {
      setForm(existing ? caseToForm(existing) : EMPTY_CASE_FORM);
      setError(null);
    }
    onOpenChange(next);
  };

  const submit = () => {
    if (form.title.trim().length < 3) {
      setError("Tytuł musi mieć co najmniej 3 znaki.");
      return;
    }
    setError(null);
    const payload = caseFormToPayload(form);
    if (existing) {
      update.mutate(
        { ...payload, expected_updated_at: existing.updated_at },
        {
          onSuccess: () => {
            showToast("Sprawa zapisana", "success");
            onOpenChange(false);
          },
          onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać sprawy.")),
        },
      );
      return;
    }
    create.mutate(payload, {
      onSuccess: (created) => {
        showToast("Sprawa założona", "success");
        close(false);
        onCreated?.(created.id);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się założyć sprawy.")),
    });
  };

  const people = assignees.data ?? [];
  const handlers = people.filter((person) => person.handler);
  const others = people.filter((person) => !person.handler);

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      title={existing ? "Edytuj sprawę" : "Nowa sprawa"}
      description={
        existing
          ? undefined
          : "Sprawa trafia do kolumny „Nowe”. Pusty termin liczy się z priorytetu w dniach roboczych."
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? "Zapisywanie…" : existing ? "Zapisz" : "Załóż sprawę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Tytuł" htmlFor="case-title" required className="sm:col-span-2">
          <Input
            id="case-title"
            value={form.title}
            maxLength={200}
            onChange={(event) => set("title", event.target.value)}
            placeholder="np. Polisa OC dla konsultanta"
          />
        </FormField>
        <FormField label="Obszar" htmlFor="case-area">
          <Select value={form.area} onValueChange={(value) => set("area", value as CaseArea)}>
            <SelectTrigger id="case-area">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CASE_AREAS.map((area) => (
                <SelectItem key={area} value={area}>
                  {CASE_AREA_LABELS[area]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Priorytet">
          <SegmentedRadio
            label="Priorytet"
            value={form.priority}
            onChange={(value) => set("priority", value)}
            options={PRIORITY_OPTIONS}
          />
        </FormField>
        <FormField label="Termin" htmlFor="case-due">
          <Input
            id="case-due"
            type="date"
            value={form.due_on}
            onChange={(event) => set("due_on", event.target.value)}
          />
        </FormField>
        <FormField label="Kontakt" htmlFor="case-follow-up" description="Kiedy wrócić do sprawy">
          <Input
            id="case-follow-up"
            type="date"
            value={form.follow_up_on}
            onChange={(event) => set("follow_up_on", event.target.value)}
          />
        </FormField>
        <FormField label="Osoba odpowiedzialna" htmlFor="case-assignee">
          <Select
            value={form.assignee_user_id || NONE}
            onValueChange={(value) => set("assignee_user_id", value === NONE ? "" : value)}
          >
            <SelectTrigger id="case-assignee">
              <SelectValue placeholder={assignees.isLoading ? "Wczytywanie…" : "Nikt"} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nikt</SelectItem>
              {[...handlers, ...others].map((person) => (
                <SelectItem key={person.id} value={String(person.id)}>
                  {person.name}
                  {person.handler ? "" : " (poza obsługą skrzynki)"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Osoba, której dotyczy" htmlFor="case-subject">
          <Select
            value={form.subject_user_id || NONE}
            onValueChange={(value) => set("subject_user_id", value === NONE ? "" : value)}
          >
            <SelectTrigger id="case-subject">
              <SelectValue placeholder="Nikt" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nikt</SelectItem>
              {people.map((person) => (
                <SelectItem key={person.id} value={String(person.id)}>
                  {person.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Kontrakt konsultanta"
          htmlFor="case-contract"
          className="sm:col-span-2"
        >
          <ContractPicker value={form.contract} onChange={(next) => set("contract", next)} />
        </FormField>
        <FormField label="Opis" htmlFor="case-description" className="sm:col-span-2">
          <Textarea
            id="case-description"
            rows={4}
            maxLength={20000}
            value={form.description}
            onChange={(event) => set("description", event.target.value)}
          />
        </FormField>
        {assignees.isError ? (
          <p role="alert" className="text-sm text-destructive sm:col-span-2">
            {apiErrorMessage(assignees.error, "Nie udało się wczytać listy osób.")}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive sm:col-span-2">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
