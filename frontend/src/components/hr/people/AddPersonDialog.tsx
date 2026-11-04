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
import { useCreateProfile, useUsersWithoutProfile } from "@/lib/api/hr";

import {
  EMPTY_PROFILE_FORM,
  ProfileFieldsForm,
  profileFormToPayload,
  type ProfileFormState,
} from "./ProfileFieldsForm";

interface AddPersonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  managers: { user_id: number; name: string }[];
}

/** Kadry: kartoteka dla konta, które już istnieje w NEXUSIE. */
export function AddPersonDialog({ open, onOpenChange, managers }: AddPersonDialogProps) {
  const { showToast } = useToast();
  const accounts = useUsersWithoutProfile(open);
  const create = useCreateProfile();
  const [userId, setUserId] = useState("");
  const [form, setForm] = useState<ProfileFormState>(EMPTY_PROFILE_FORM);
  const [error, setError] = useState<string | null>(null);

  const close = (next: boolean) => {
    if (!next) {
      setUserId("");
      setForm(EMPTY_PROFILE_FORM);
      setError(null);
    }
    onOpenChange(next);
  };

  const submit = () => {
    if (!userId) {
      setError("Wybierz osobę.");
      return;
    }
    setError(null);
    create.mutate(
      { user_id: Number(userId), ...profileFormToPayload(form) },
      {
        onSuccess: () => {
          showToast("Kartoteka założona", "success");
          close(false);
        },
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się założyć kartoteki.")),
      },
    );
  };

  const options = accounts.data ?? [];

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      title="Dodaj osobę do kartoteki"
      description="Osoba musi mieć konto w NEXUSIE. Nowe konta zakłada kreator wejścia."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? "Zapisywanie…" : "Załóż kartotekę"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <FormField label="Osoba" htmlFor="hr-add-user" required>
          <Select value={userId} onValueChange={setUserId}>
            <SelectTrigger id="hr-add-user">
              <SelectValue
                placeholder={
                  accounts.isLoading
                    ? "Wczytywanie kont…"
                    : options.length === 0 && accounts.isSuccess
                      ? "Każde konto ma już kartotekę"
                      : "Wybierz konto"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {options.map((account) => (
                <SelectItem key={account.user_id} value={String(account.user_id)}>
                  {account.name} · {account.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {accounts.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(accounts.error, "Nie udało się wczytać listy kont.")}
          </p>
        ) : null}
        <ProfileFieldsForm
          form={form}
          onChange={setForm}
          managers={managers}
          idPrefix="hr-add"
        />
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
