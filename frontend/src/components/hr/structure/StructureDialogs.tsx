"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import type { Division } from "@/lib/api/hr";
import {
  DIVISION_LABELS,
  managerWords,
  useReassignManager,
  useSetDivision,
  useSetDivisionHeads,
  type StructureDivision,
  type StructurePerson,
} from "@/lib/api/hr-structure";

const NONE = "none";

interface Option {
  user_id: number;
  name: string;
}

function PersonSelect({
  id,
  value,
  onChange,
  options,
  emptyLabel,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly Option[];
  emptyLabel: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{emptyLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.user_id} value={String(option.user_id)}>
            {option.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** „Zmień przełożonego / koordynatora” dla zaznaczonych — od razu, bez daty „od kiedy”. */
export function ReassignDialog({
  people,
  candidates,
  open,
  onOpenChange,
  onDone,
}: {
  people: readonly StructurePerson[];
  candidates: readonly Option[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const { showToast } = useToast();
  const reassign = useReassignManager();
  const [value, setValue] = useState(NONE);
  const [error, setError] = useState<string | null>(null);
  const words = managerWords(people.map((person) => person.employment_type));
  const selected = new Set(people.map((person) => person.user_id));
  const options = candidates.filter((option) => !selected.has(option.user_id));

  const submit = () => {
    setError(null);
    reassign.mutate(
      {
        user_ids: people.map((person) => person.user_id),
        manager_user_id: value === NONE ? null : Number(value),
      },
      {
        onSuccess: (result) => {
          showToast(
            result.changed.length
              ? `Zmieniono: ${result.changed.length}`
              : "Bez zmian — wszyscy mieli już tę osobę",
            "success",
          );
          onDone();
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zmiany.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Zmień ${words.ofOne} (${people.length})`}
      description="Zmiana działa od razu. Wnioski i timesheety w toku przejdą do nowej osoby — o akceptacji decyduje ten, kto jest wpisany w chwili decyzji."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={reassign.isPending}>
            {reassign.isPending ? "Zapisywanie…" : "Zmień"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {people.map((person) => person.name).join(", ")}
        </p>
        <FormField label={`Nowy ${words.one}`} htmlFor="structure-new-manager">
          <PersonSelect
            id="structure-new-manager"
            value={value}
            onChange={setValue}
            options={options}
            emptyLabel={`Bez ${words.ofOne}`}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

/** „Ustaw pion” dla zaznaczonych. */
export function DivisionDialog({
  people,
  open,
  onOpenChange,
  onDone,
}: {
  people: readonly StructurePerson[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const { showToast } = useToast();
  const save = useSetDivision();
  const [value, setValue] = useState<string>(NONE);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    save.mutate(
      {
        user_ids: people.map((person) => person.user_id),
        division: value === NONE ? null : (value as Division),
      },
      {
        onSuccess: (result) => {
          showToast(`Pion zapisany: ${result.changed.length}`, "success");
          onDone();
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać pionu.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Ustaw pion (${people.length})`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Pion" htmlFor="structure-division">
          <Select value={value} onValueChange={setValue}>
            <SelectTrigger id="structure-division">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Bez pionu</SelectItem>
              {(Object.keys(DIVISION_LABELS) as Division[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {DIVISION_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}

/** Head Front office i Back office (`app_settings['hr_divisions']`). */
export function DivisionHeadsDialog({
  divisions,
  candidates,
  open,
  onOpenChange,
}: {
  divisions: readonly StructureDivision[];
  candidates: readonly Option[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const save = useSetDivisionHeads();
  const [values, setValues] = useState<Record<Division, string>>(() => ({
    front_office: NONE,
    back_office: NONE,
    ...Object.fromEntries(
      divisions.map((division) => [
        division.key,
        division.head_user_id ? String(division.head_user_id) : NONE,
      ]),
    ),
  }));
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    const heads = Object.fromEntries(
      (Object.keys(values) as Division[]).map((key) => [
        key,
        values[key] === NONE ? null : Number(values[key]),
      ]),
    ) as Record<Division, number | null>;
    save.mutate(heads, {
      onSuccess: () => {
        showToast("Headowie pionów zapisani", "success");
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać.")),
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Headowie pionów"
      description="Osoba w pionie bez przełożonego dostaje podpowiedź „przełożony = head pionu”. Nic nie zapisuje się samo."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {(Object.keys(DIVISION_LABELS) as Division[]).map((key) => (
          <FormField key={key} label={DIVISION_LABELS[key]} htmlFor={`structure-head-${key}`}>
            <PersonSelect
              id={`structure-head-${key}`}
              value={values[key]}
              onChange={(value) => setValues({ ...values, [key]: value })}
              options={candidates}
              emptyLabel="Nie ustawiono"
            />
          </FormField>
        ))}
        {error ? (
          <p role="alert" className="text-sm text-destructive sm:col-span-2">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
