"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LockKeyhole, RotateCcw } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { invalidateCandidateMutation } from "./candidate-cache";
import { candidateQueryKeys } from "./candidate-query-keys";

type IdentityFieldName = "name" | "lastname";

interface RestoreIdentityFieldVariables {
  field: IdentityFieldName;
  expectedCurrentValue: string;
  expectedTraffitValue: string;
  expectedOverrideToken: string;
}

export interface IdentitySyncField {
  owner: "nexus" | "traffit";
  manual_lock: boolean;
  traffit_value: string | null;
  can_restore: boolean;
  overridden_at?: string | null;
  override_token?: string | null;
  overridden_by?: number | null;
  ownership_reason?: "manual_edit" | "bootstrap_mismatch" | null;
}

export interface IdentitySyncState {
  name: IdentitySyncField;
  lastname: IdentitySyncField;
}

export interface IdentityEditorCandidate {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
  phone?: string | null;
  identity_sync?: IdentitySyncState | null;
}

const FIELD_LABELS: Record<IdentityFieldName, string> = {
  name: "Imię",
  lastname: "Nazwisko",
};

function responseStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  const response = (error as { response?: { status?: unknown } }).response;
  return typeof response?.status === "number" ? response.status : null;
}

function identityFormSnapshot(candidate: IdentityEditorCandidate) {
  return {
    name: candidate.name ?? "",
    lastname: candidate.lastname ?? "",
    email: candidate.email ?? "",
    phone: candidate.phone ?? "",
  };
}

function IdentityFieldStatus({ state }: { state?: IdentitySyncField }) {
  if (!state) return null;

  if (state.manual_lock) {
    return (
      <Badge variant="soft" size="sm">
        <LockKeyhole className="h-3 w-3" aria-hidden="true" />
        {state.ownership_reason === "bootstrap_mismatch"
          ? "Do weryfikacji"
          : "Ręczna korekta"}
      </Badge>
    );
  }

  return (
    <Badge variant={state.owner === "traffit" ? "info" : "neutral"} size="sm">
      {state.owner === "traffit" ? "Traffit" : "NEXUS"}
    </Badge>
  );
}

function identityFieldHint(state?: IdentitySyncField): string | null {
  if (!state) return null;
  if (state.manual_lock) {
    if (state.ownership_reason === "bootstrap_mismatch") {
      return "Zachowano dotychczasową wartość NEXUS do weryfikacji; Traffit jej nie nadpisze.";
    }
    return "Chronione przed nadpisaniem przez synchronizację z Traffita.";
  }
  if (state.owner === "traffit") {
    return "Synchronizowane z Traffita. Zmiana stanie się ręczną korektą.";
  }
  return "Wartość utrzymywana w NEXUS.";
}

/**
 * Inline edycja tożsamości i kontaktu kandydata (imię, nazwisko, e-mail,
 * telefon) wprost w nagłówku profilu — bez otwierania pełnego modala "Edytuj".
 *
 * Szczególnie przydatne dla kandydatów zaimportowanych z Traffit jako "?"
 * (brak sparsowanego imienia): rekruter widzi profil i może od razu poprawić
 * dane. PATCH /api/candidates/{id} akceptuje te pola od dawna — brakowało tylko
 * widocznego, prostego wejścia w UI.
 */
export function IdentityEditor({
  candidate,
  onClose,
}: {
  candidate: IdentityEditorCandidate;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const initialForm = identityFormSnapshot(candidate);
  const [form, setForm] = useState(initialForm);
  const [persistedForm, setPersistedForm] = useState(initialForm);
  const [identitySync, setIdentitySync] = useState(candidate.identity_sync ?? null);
  const [restoreField, setRestoreField] = useState<IdentityFieldName | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const buildChangedPayload = () => {
    const next = {
      name: form.name.trim(),
      lastname: form.lastname.trim(),
      // Pusty string → null: pozwala WYCZYŚCIĆ pole. Backend EmailStr
      // odrzuca "" (422), a null kasuje wartość. Trim, by nie zapisać spacji.
      email: form.email.trim() || null,
      phone: form.phone.trim() || null,
    };
    const previous = {
      name: persistedForm.name.trim(),
      lastname: persistedForm.lastname.trim(),
      email: persistedForm.email.trim() || null,
      phone: persistedForm.phone.trim() || null,
    };
    return Object.fromEntries(
      (Object.keys(next) as Array<keyof typeof next>)
        .filter((field) => next[field] !== previous[field])
        .map((field) => [field, next[field]]),
    );
  };

  const save = useMutation({
    mutationFn: (changedPayload: Record<string, string | null>) =>
      api.patch(`/api/candidates/${candidate.id}`, changedPayload),
    onSuccess: () => {
      showSuccess("Zapisano dane kandydata");
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      onClose();
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się zapisać danych kandydata"),
  });

  const restore = useMutation({
    mutationFn: ({
      field,
      expectedCurrentValue,
      expectedTraffitValue,
      expectedOverrideToken,
    }: RestoreIdentityFieldVariables) =>
      api.post<IdentityEditorCandidate>(
        `/api/candidates/${candidate.id}/identity/restore-from-traffit`,
        {
          fields: [field],
          expected_current_values: { [field]: expectedCurrentValue },
          expected_traffit_values: { [field]: expectedTraffitValue },
          expected_override_tokens: { [field]: expectedOverrideToken },
        },
      ),
    onSuccess: (response, { field }) => {
      const restoredCandidate = response.data;
      setForm((current) => ({
        ...current,
        [field]: restoredCandidate[field] ?? "",
      }));
      setPersistedForm((current) => ({
        ...current,
        [field]: restoredCandidate[field] ?? "",
      }));
      setIdentitySync(restoredCandidate.identity_sync ?? null);
      setRestoreError(null);
      setRestoreField(null);
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      showSuccess(`${FIELD_LABELS[field]} przywrócone z Traffita`);
    },
    onError: async (error, { field }) => {
      const message =
        extractErrorMsg(error) || "Nie udało się przywrócić danych z Traffita";
      if (responseStatus(error) !== 409) {
        setRestoreError(message);
        showError(message);
        return;
      }

      try {
        const response = await api.get<IdentityEditorCandidate>(
          `/api/candidates/${candidate.id}`,
        );
        const refreshedCandidate = response.data;
        const refreshedForm = identityFormSnapshot(refreshedCandidate);
        const refreshedFieldState = refreshedCandidate.identity_sync?.[field];

        setForm(refreshedForm);
        setPersistedForm(refreshedForm);
        setIdentitySync(refreshedCandidate.identity_sync ?? null);
        queryClient.setQueryData(
          candidateQueryKeys.detail(candidate.id),
          refreshedCandidate,
        );

        if (
          refreshedFieldState?.manual_lock &&
          refreshedFieldState.can_restore &&
          refreshedFieldState.traffit_value?.trim()
        ) {
          setRestoreError(
            `${message} Profil został odświeżony — sprawdź aktualne wartości i potwierdź ponownie.`,
          );
        } else {
          setRestoreError(null);
          setRestoreField(null);
        }
        showError(`${message} Profil został odświeżony.`);
      } catch {
        setRestoreError(message);
        showError(message);
      }
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.lastname.trim()) {
      showError("Imię i nazwisko są wymagane");
      return;
    }
    const changedPayload = buildChangedPayload();
    if (Object.keys(changedPayload).length === 0) {
      onClose();
      return;
    }
    save.mutate(changedPayload);
  };

  const openRestore = (field: IdentityFieldName) => {
    setRestoreError(null);
    setRestoreField(field);
  };

  const closeRestore = () => {
    if (restore.isPending) return;
    setRestoreError(null);
    setRestoreField(null);
  };

  const busy = save.isPending || restore.isPending;
  const hasUnsavedChanges = (Object.keys(form) as Array<keyof typeof form>).some(
    (field) => form[field] !== persistedForm[field],
  );
  const restoreState = restoreField ? identitySync?.[restoreField] : undefined;
  // OCC musi dostać dokładnie te snapshoty, które użytkownik potwierdza. Nie
  // trimujemy ich przed wysłaniem, żeby porównanie pod row lockiem było 1:1 i
  // nie generowało fałszywego konfliktu.
  const restoreCurrentValue = restoreField ? persistedForm[restoreField] : "";
  const restoreTraffitValue = restoreState?.traffit_value ?? "";

  const renderIdentityMeta = (field: IdentityFieldName) => {
    const state = identitySync?.[field];
    const hint = identityFieldHint(state);
    const canRestore =
      state?.manual_lock &&
      state.can_restore &&
      Boolean(state.traffit_value?.trim()) &&
      Boolean(state.override_token);

    if (!hint && !canRestore) return null;

    return (
      <div className="mt-1 flex min-h-11 items-start justify-between gap-2">
        <div className="space-y-1 pt-1">
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
          {canRestore && hasUnsavedChanges ? (
            <p
              id={`candidate-identity-${field}-restore-reason`}
              className="text-xs font-medium text-warning-muted-foreground"
            >
              Najpierw zapisz albo anuluj niezapisane zmiany.
            </p>
          ) : null}
        </div>
        {canRestore ? (
          <Button
            type="button"
            size="sm"
            variant="tertiary"
            className="min-h-11 min-w-11 shrink-0 px-2"
            disabled={busy || hasUnsavedChanges}
            aria-label={`Przywróć ${FIELD_LABELS[field].toLowerCase()} z Traffita`}
            aria-describedby={
              hasUnsavedChanges
                ? `candidate-identity-${field}-restore-reason`
                : undefined
            }
            onClick={() => openRestore(field)}
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Przywróć z Traffita
          </Button>
        ) : null}
      </div>
    );
  };

  return (
    <>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="candidate-identity-name" className="text-xs">
                Imię
              </Label>
              <IdentityFieldStatus state={identitySync?.name} />
            </div>
            <Input
              id="candidate-identity-name"
              className="min-h-11"
              autoFocus
              value={form.name}
              disabled={busy}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Jan"
            />
            {renderIdentityMeta("name")}
          </div>
          <div>
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="candidate-identity-lastname" className="text-xs">
                Nazwisko
              </Label>
              <IdentityFieldStatus state={identitySync?.lastname} />
            </div>
            <Input
              id="candidate-identity-lastname"
              className="min-h-11"
              value={form.lastname}
              disabled={busy}
              onChange={(e) =>
                setForm((f) => ({ ...f, lastname: e.target.value }))
              }
              placeholder="Kowalski"
            />
            {renderIdentityMeta("lastname")}
          </div>
          <div>
            <Label htmlFor="candidate-identity-email" className="text-xs">
              E-mail
            </Label>
            <Input
              id="candidate-identity-email"
              className="min-h-11"
              type="email"
              value={form.email}
              disabled={busy}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              placeholder="jan.kowalski@firma.pl"
            />
          </div>
          <div>
            <Label htmlFor="candidate-identity-phone" className="text-xs">
              Telefon
            </Label>
            <Input
              id="candidate-identity-phone"
              className="min-h-11"
              type="tel"
              value={form.phone}
              disabled={busy}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
              placeholder="+48 500 600 700"
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="submit"
            size="sm"
            variant="primary"
            className="min-h-11 min-w-11"
            disabled={busy}
          >
            {save.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={onClose}
            disabled={busy}
          >
            Anuluj
          </Button>
        </div>
      </form>

      <Dialog
        open={restoreField !== null}
        onOpenChange={(open) => {
          if (!open) closeRestore();
        }}
      >
        <DialogContent
          size="sm"
          hideClose={restore.isPending}
          onEscapeKeyDown={(event) => {
            if (restore.isPending) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (restore.isPending) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              Przywrócić {restoreField ? FIELD_LABELS[restoreField].toLowerCase() : "pole"}{" "}
              z Traffita?
            </DialogTitle>
            <DialogDescription>
              Ręczna ochrona zostanie usunięta. Kolejne synchronizacje z Traffita
              będą mogły ponownie zmienić to pole.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-3">
            <div className="grid gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm sm:grid-cols-[1fr_auto_1fr] sm:items-center">
              <div>
                <p className="text-xs text-muted-foreground">Obecnie w NEXUS</p>
                <p className="font-medium [overflow-wrap:anywhere]">
                  {restoreCurrentValue.trim() || "—"}
                </p>
              </div>
              <span className="hidden text-muted-foreground sm:block" aria-hidden="true">
                →
              </span>
              <div>
                <p className="text-xs text-muted-foreground">Wartość z Traffita</p>
                <p className="font-medium [overflow-wrap:anywhere]">
                  {restoreTraffitValue.trim() || "—"}
                </p>
              </div>
            </div>
            {restoreError ? (
              <p
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
              >
                {restoreError}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              className="min-h-11 min-w-11"
              disabled={restore.isPending}
              onClick={closeRestore}
            >
              Anuluj
            </Button>
            <Button
              type="button"
              className="min-h-11 min-w-11"
              loading={restore.isPending}
              disabled={!restoreField || !restoreTraffitValue.trim()}
              onClick={() => {
                if (!restoreField || !restoreTraffitValue.trim()) return;
                setRestoreError(null);
                restore.mutate({
                  field: restoreField,
                  expectedCurrentValue: restoreCurrentValue,
                  expectedTraffitValue: restoreTraffitValue,
                  expectedOverrideToken: restoreState?.override_token ?? "",
                });
              }}
            >
              {restore.isPending ? "Przywracanie…" : "Potwierdź przywrócenie"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
