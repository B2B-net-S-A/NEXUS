"use client";

/**
 * „Dodaj / Edytuj umowę wykonawczą" — okno z sekcji „Struktura umów" na
 * profilu Centrum e-Zdrowia. Umowa wykonawcza wisi pod umową ramową (częścią);
 * przycisk „Dodaj" stoi przy KAŻDEJ ramowej, więc okno dostaje preselekcję
 * tej, przy której kliknięto — ale select zostaje edytowalny (pomyłka
 * w kliknięciu nie może wymuszać zamknięcia i ponownego otwarcia).
 *
 * Tryb edycji (`editing`): numer, notatka i status (Aktywna / Zakończona).
 * Ramowa jest tylko do odczytu — API aktualizacji jej nie zmienia, a
 * przepięcie umowy pod inną część przestawiłoby `project_part` wszystkim
 * przypisanym konsultantom. Odmowa serwera (409: umowa ma żywe przypisania,
 * więc nie da się jej zakończyć) zostaje w oknie, bez zamykania.
 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  executiveContractsApi,
  frameworkPartHeader,
  type ExecutiveContractRead,
  type ExecutiveContractStatus,
  type FrameworkPartRead,
} from "@/lib/api/executiveContracts";

interface Props {
  clientId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  frameworks: FrameworkPartRead[];
  /** Umowa ramowa, przy której kliknięto „Dodaj" — preselekcja, nie blokada. */
  initialFrameworkId: number | null;
  /** Umowa do edycji — `null`/`undefined` = tryb dodawania. */
  editing?: ExecutiveContractRead | null;
  onCreated: (created: ExecutiveContractRead) => void;
  onUpdated?: (updated: ExecutiveContractRead) => void;
}

export function AddExecutiveContractModal({
  clientId,
  open,
  onOpenChange,
  frameworks,
  initialFrameworkId,
  editing = null,
  onCreated,
  onUpdated,
}: Props) {
  const isEdit = editing != null;
  const [frameworkId, setFrameworkId] = useState<string>(
    initialFrameworkId != null ? String(initialFrameworkId) : "",
  );
  const [number, setNumber] = useState("");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<ExecutiveContractStatus>("active");
  const [error, setError] = useState<string | null>(null);

  // Każde otwarcie startuje od świeżego formularza z preselekcją klikniętej
  // ramowej (albo od wartości edytowanej umowy) — okno żyje w rodzicu przez
  // cały czas, więc sam `useState` pamiętałby wpisy z poprzedniego razu.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setFrameworkId(String(editing.framework_contract_id));
      setNumber(editing.number);
      setNotes(editing.notes ?? "");
      setStatus(editing.status);
    } else {
      setFrameworkId(initialFrameworkId != null ? String(initialFrameworkId) : "");
      setNumber("");
      setNotes("");
      setStatus("active");
    }
    setError(null);
  }, [open, initialFrameworkId, editing]);

  const mutation = useMutation({
    mutationFn: () =>
      editing
        ? executiveContractsApi.update(clientId, editing.id, {
            number: number.trim(),
            notes: notes.trim() || null,
            status,
          })
        : executiveContractsApi.create(clientId, {
            framework_contract_id: Number(frameworkId),
            number: number.trim(),
            notes: notes.trim() || null,
          }),
    onSuccess: (saved) => {
      if (editing) {
        onUpdated?.(saved);
      } else {
        onCreated(saved);
      }
      onOpenChange(false);
    },
    onError: (err: unknown) => {
      setError(
        apiErrorMessage(
          err,
          editing
            ? "Nie udało się zapisać zmian umowy wykonawczej."
            : "Nie udało się dodać umowy wykonawczej.",
        ),
      );
    },
  });

  const canSubmit = frameworkId !== "" && number.trim() !== "" && !mutation.isPending;
  const editedFramework = editing
    ? frameworks.find((fc) => fc.id === editing.framework_contract_id)
    : undefined;

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (mutation.isPending) return;
        onOpenChange(next);
      }}
      title={isEdit ? "Edytuj umowę wykonawczą" : "Dodaj umowę wykonawczą"}
      description={
        isEdit
          ? "Numer, notatka i status umowy wykonawczej. Umowy ramowej (części) nie da się zmienić — przypisani konsultanci dziedziczą z niej część."
          : "Umowa wykonawcza wisi pod umową ramową (częścią). Konsultanci i zamówienia są przypisywane do niej, nie do części."
      }
      footer={
        <>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Anuluj
          </Button>
          <Button
            type="submit"
            form="add-executive-contract-form"
            disabled={!canSubmit}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : null}
            {isEdit ? "Zapisz zmiany" : "Zapisz umowę wykonawczą"}
          </Button>
        </>
      }
    >
      <form
        id="add-executive-contract-form"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          setError(null);
          mutation.mutate();
        }}
      >
        {isEdit ? (
          <div>
            <span className="text-sm font-medium">Umowa ramowa (część)</span>
            <p className="mt-1 text-sm text-muted-foreground">
              {editedFramework
                ? frameworkPartHeader(editedFramework)
                : `Umowa ramowa #${editing.framework_contract_id}`}
            </p>
          </div>
        ) : (
          <label className="block">
            <span className="text-sm font-medium">Umowa ramowa (część) *</span>
            <select
              value={frameworkId}
              onChange={(e) => setFrameworkId(e.target.value)}
              aria-label="Umowa ramowa"
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="">— wybierz —</option>
              {frameworks.map((fc) => (
                <option key={fc.id} value={String(fc.id)}>
                  {frameworkPartHeader(fc)}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block">
          <span className="text-sm font-medium">Numer umowy wykonawczej *</span>
          <Input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            aria-label="Numer umowy wykonawczej"
            placeholder="np. CeZ/145/2025/UW-3"
            className="mt-1"
          />
        </label>

        {isEdit ? (
          <label className="block">
            <span className="text-sm font-medium">Status</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as ExecutiveContractStatus)}
              aria-label="Status umowy wykonawczej"
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              <option value="active">Aktywna</option>
              <option value="ended">Zakończona</option>
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Zakończonej umowy nie da się wybrać w formularzach zamówień.
              Umowy z aktywnymi przypisaniami serwer nie pozwoli zakończyć.
            </p>
          </label>
        ) : null}

        <label className="block">
          <span className="text-sm font-medium">Notatka</span>
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            aria-label="Notatka"
            rows={3}
            className="mt-1"
          />
        </label>

        {isEdit ? null : (
          <p className="text-xs text-muted-foreground" role="note">
            Nowa umowa wykonawcza dostaje status Aktywna.
          </p>
        )}

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </AppModal>
  );
}
