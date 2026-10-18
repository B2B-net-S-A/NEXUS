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
import {
  EMPLOYMENT_TYPE_LABELS,
  useSetEmploymentType,
  type EmploymentType,
  type PersonFull,
} from "@/lib/api/hr";

import { formFrom } from "./EditProfileDialog";
import {
  FormSpecificFields,
  profileFormToPayload,
  type ProfileFormState,
} from "./ProfileFieldsForm";

interface EmploymentTypeDialogProps {
  person: PersonFull;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * „Zmień formę” dla Finansów — kartotekę edytują Kadry, formę i pola od niej
 * zależne zmieniają też Finanse (decyzja Artura 19.10.2026).
 */
export function EmploymentTypeDialog({ person, open, onOpenChange }: EmploymentTypeDialogProps) {
  const { showToast } = useToast();
  const save = useSetEmploymentType(person.user_id);
  const [form, setForm] = useState<ProfileFormState>(() => formFrom(person));
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof ProfileFormState>(key: K, value: ProfileFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = () => {
    if (!form.employment_type) {
      setError("Wybierz formę współpracy.");
      return;
    }
    setError(null);
    const payload = profileFormToPayload(form);
    save.mutate(
      {
        employment_type: form.employment_type,
        student_contribution_exempt: payload.student_contribution_exempt,
        contribution_exempt_until: payload.contribution_exempt_until,
        leave_seniority_years: payload.leave_seniority_years,
        zus_certificate_received_on: payload.zus_certificate_received_on,
      },
      {
        onSuccess: () => {
          showToast("Forma współpracy zapisana", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać formy.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Forma współpracy · ${person.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Forma współpracy" htmlFor="hr-form-type">
          <Select
            value={form.employment_type}
            onValueChange={(value) => set("employment_type", value as EmploymentType)}
          >
            <SelectTrigger id="hr-form-type">
              <SelectValue placeholder="Do uzupełnienia — wybierz" />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(EMPLOYMENT_TYPE_LABELS) as EmploymentType[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {EMPLOYMENT_TYPE_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormSpecificFields form={form} set={set} id={(name) => `hr-form-${name}`} />
      </div>
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
