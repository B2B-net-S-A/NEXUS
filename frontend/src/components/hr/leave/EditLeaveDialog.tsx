"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
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
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEditLeave,
  useSubstitutes,
  type LeaveRequestRow,
  type LeaveType,
} from "@/lib/api/hr-leave";
import { reportsAbsence } from "@/lib/hr-employment-terms";
import { useDebounced } from "@/lib/use-debounced";

import {
  FULL_DAY,
  LEAVE_TYPE_LABELS,
  NO_SUBSTITUTE,
  editChanges,
  editValuesFrom,
  formatRange,
  validRange,
  type LeaveEditValues,
} from "./leave-format";

const ALL_TYPES = Object.keys(LEAVE_TYPE_LABELS) as LeaveType[];

interface EditLeaveDialogProps {
  request: LeaveRequestRow | null;
  onClose: (saved: LeaveRequestRow | null) => void;
}

/**
 * „Edytuj” w Akceptacjach (Compass `updateTeamLeave`): rodzaj, daty, pół dnia
 * i zastępca. Dni i pulę przelicza serwer tą samą drogą co przy złożeniu;
 * zgoda osoby na przekierowanie i jej tekst autoodpowiedzi zostają.
 */
export function EditLeaveDialog({ request, onClose }: EditLeaveDialogProps) {
  const edit = useEditLeave();
  const [values, setValues] = useState<LeaveEditValues | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValues(request ? editValuesFrom(request) : null);
    setError(null);
  }, [request]);

  const rangeOk = values ? validRange(values.start, values.end) : false;
  const range = useDebounced(
    values && rangeOk ? { start: values.start, end: values.end } : null,
    300,
  );
  const substitutes = useSubstitutes(request ? range : null, request?.user_id ?? null);

  const close = (saved: LeaveRequestRow | null) => {
    setError(null);
    onClose(saved);
  };

  if (!request || !values) return null;

  const report = reportsAbsence(request.employment_type);
  const types = report ? (["vacation"] as LeaveType[]) : ALL_TYPES;
  const singleDay = values.start === values.end;
  const changes = editChanges(request, values);
  const set = (patch: Partial<LeaveEditValues>) => setValues({ ...values, ...patch });
  // Obecny zastępca zostaje na liście, nawet gdy podpowiedzi go nie mają.
  const options = [...(substitutes.data ?? [])];
  if (
    request.substitute_user_id &&
    !options.some((row) => row.user_id === request.substitute_user_id)
  ) {
    options.unshift({
      user_id: request.substitute_user_id,
      name: request.substitute_name ?? "Obecny zastępca",
      job_title: null,
      department: null,
      same_department: false,
      shared_role: false,
      suggested: false,
    });
  }

  const submit = () => {
    if (!changes) return;
    setError(null);
    edit.mutate(
      { id: request.id, changes },
      {
        onSuccess: (saved) => close(saved),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zmian.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : close(null))}
      size="lg"
      title={report ? "Zmień zgłoszenie" : "Zmień wniosek"}
      description={`${request.user_name ?? "Osoba"} · teraz ${formatRange(
        request.start_date,
        request.end_date,
      )}. Osoba dostanie powiadomienie; autoodpowiedź i kalendarz przesuną się same.`}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(null)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={!changes || edit.isPending}>
            {edit.isPending ? "Zapisywanie…" : "Zapisz zmiany"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {report || request.leave_type === null ? null : (
          <FormField label="Rodzaj" htmlFor="leave-edit-type">
            <Select
              value={values.leaveType}
              onValueChange={(value) => set({ leaveType: value as LeaveType })}
            >
              <SelectTrigger id="leave-edit-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {types.map((type) => (
                  <SelectItem key={type} value={type}>
                    {LEAVE_TYPE_LABELS[type]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Od" htmlFor="leave-edit-start">
            <Input
              id="leave-edit-start"
              type="date"
              value={values.start}
              onChange={(event) =>
                set({
                  start: event.target.value,
                  end: event.target.value > values.end ? event.target.value : values.end,
                })
              }
            />
          </FormField>
          <FormField label="Do" htmlFor="leave-edit-end">
            <Input
              id="leave-edit-end"
              type="date"
              value={values.end}
              min={values.start}
              onChange={(event) => set({ end: event.target.value })}
            />
          </FormField>
          <FormField label="Wymiar" htmlFor="leave-edit-half">
            <Select
              value={singleDay ? values.halfDay : FULL_DAY}
              onValueChange={(value) => set({ halfDay: value })}
              disabled={!singleDay}
            >
              <SelectTrigger id="leave-edit-half">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FULL_DAY}>Cały dzień</SelectItem>
                <SelectItem value="morning">Pół dnia (rano)</SelectItem>
                <SelectItem value="afternoon">Pół dnia (po południu)</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField
          label={report ? "Kto przejmie bieżące sprawy" : "Zastępca"}
          htmlFor="leave-edit-substitute"
          description={
            request.forward_mail_consent
              ? "Osoba zgodziła się na przekierowanie poczty — reguła przejdzie na nowego zastępcę, a bez zastępcy zniknie."
              : undefined
          }
        >
          <Select value={values.substitute} onValueChange={(value) => set({ substitute: value })}>
            <SelectTrigger id="leave-edit-substitute">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_SUBSTITUTE}>Bez zastępcy</SelectItem>
              {options.map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                  {row.suggested ? " · proponowany" : row.department ? ` · ${row.department}` : ""}
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
