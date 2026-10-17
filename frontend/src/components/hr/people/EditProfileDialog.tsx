"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useUpdateProfile, type PersonFull } from "@/lib/api/hr";

import {
  ProfileFieldsForm,
  profileFormToPayload,
  type ProfileFormState,
} from "./ProfileFieldsForm";

function formFrom(person: PersonFull): ProfileFormState {
  return {
    manager_user_id: person.manager_user_id ? String(person.manager_user_id) : "",
    employment_type: person.employment_type,
    employment_status: person.employment_status,
    work_start_date: person.work_start_date ?? "",
    last_working_day: person.last_working_day ?? "",
    default_location: person.default_location,
    timesheet_required: person.timesheet_required,
    can_log_overtime: person.can_log_overtime,
    job_title: person.job_title ?? "",
    department: person.department ?? "",
    phone: person.phone ?? "",
    division: person.division ?? "",
  };
}

interface EditProfileDialogProps {
  person: PersonFull;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  managers: { user_id: number; name: string }[];
}

export function EditProfileDialog({
  person,
  open,
  onOpenChange,
  managers,
}: EditProfileDialogProps) {
  const { showToast } = useToast();
  const update = useUpdateProfile(person.user_id);
  const [form, setForm] = useState<ProfileFormState>(() => formFrom(person));
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    update.mutate(profileFormToPayload(form), {
      onSuccess: () => {
        showToast("Kartoteka zapisana", "success");
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać.")),
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Kartoteka · ${person.name}`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={update.isPending}>
            {update.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <ProfileFieldsForm
        form={form}
        onChange={setForm}
        managers={managers.filter((manager) => manager.user_id !== person.user_id)}
        idPrefix="hr-edit"
      />
      {error ? (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
