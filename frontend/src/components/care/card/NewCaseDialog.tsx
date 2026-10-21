"use client";

import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
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
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_AREAS,
  CASE_AREA_LABELS,
  useCaseAssignees,
  useCreateCase,
  type CaseArea,
} from "@/lib/api/admin-cases";
import { careKeys } from "@/lib/api/care";

const NOBODY = "none";

interface NewCaseDialogProps {
  contractId: number;
  /** „Anna Nowak · Bank” — kogo dotyczy sprawa. */
  subject: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * „+ Nowa sprawa” w karcie konsultanta: sprawa z tym kontraktem w jednym
 * rejestrze Spraw (`POST /api/cases` z `contract_id`). Zakłada ją obsługa
 * skrzynki (uprawnienie „Sprawy”); bez niego sprawę zakłada się w oknie
 * rozmowy („Coś do załatwienia?”). Bez stawek — sprawa negocjacyjna w karcie
 * i tak pokazuje tylko tytuł, obszar, status, termin i osobę.
 */
export function NewCaseDialog({ contractId, subject, open, onOpenChange }: NewCaseDialogProps) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const ids = { title: useId(), area: useId(), assignee: useId(), due: useId(), description: useId() };
  const create = useCreateCase();
  const assignees = useCaseAssignees(open);
  const [title, setTitle] = useState("");
  const [area, setArea] = useState<CaseArea>("administration");
  const [assignee, setAssignee] = useState(NOBODY);
  const [dueOn, setDueOn] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    if (!title.trim()) {
      setError("Podaj tytuł sprawy.");
      return;
    }
    create.mutate(
      {
        title: title.trim(),
        area,
        priority: "P2",
        due_on: dueOn || null,
        assignee_user_id: assignee === NOBODY ? null : Number(assignee),
        description: description.trim() || null,
        contract_id: contractId,
      },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries({ queryKey: careKeys.card(contractId) });
          void queryClient.invalidateQueries({ queryKey: careKeys.timeline(contractId) });
          showToast("Sprawa założona", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się założyć sprawy.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Nowa sprawa"
      description={`Dotyczy: ${subject}. Trafi do Spraw w „Ludziach” i do karty konsultanta.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} loading={create.isPending}>
            Załóż sprawę
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <FormField label="Tytuł" htmlFor={ids.title} required>
          <Input
            id={ids.title}
            value={title}
            maxLength={300}
            placeholder="np. Wymiana laptopa"
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Obszar" htmlFor={ids.area}>
            <Select value={area} onValueChange={(next) => setArea(next as CaseArea)}>
              <SelectTrigger id={ids.area}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CASE_AREAS.map((key) => (
                  <SelectItem key={key} value={key}>
                    {CASE_AREA_LABELS[key]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Prowadzi" htmlFor={ids.assignee}>
            <Select value={assignee} onValueChange={setAssignee}>
              <SelectTrigger id={ids.assignee}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NOBODY}>Bez osoby</SelectItem>
                {(assignees.data ?? []).map((person) => (
                  <SelectItem key={person.id} value={String(person.id)}>
                    {person.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Termin" htmlFor={ids.due}>
            <Input id={ids.due} type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} />
          </FormField>
        </div>
        <FormField label="Opis" htmlFor={ids.description}>
          <Textarea
            id={ids.description}
            rows={3}
            maxLength={4000}
            value={description}
            placeholder="Co trzeba załatwić. Bez stawek i danych o zdrowiu."
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
        {assignees.isError ? (
          <p className="text-xs text-muted-foreground">
            Listy osób nie udało się wczytać — sprawę przydzieli obsługa skrzynki.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
