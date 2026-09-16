"use client";

/**
 * „Dodaj umowę wykonawczą" — okno z sekcji „Struktura umów" na profilu
 * Centrum e-Zdrowia. Umowa wykonawcza wisi pod umową ramową (częścią);
 * przycisk stoi przy KAŻDEJ ramowej, więc okno dostaje preselekcję tej,
 * przy której kliknięto — ale select zostaje edytowalny (pomyłka w kliknięciu
 * nie może wymuszać zamknięcia i ponownego otwarcia).
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
  type FrameworkPartRead,
} from "@/lib/api/executiveContracts";

interface Props {
  clientId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  frameworks: FrameworkPartRead[];
  /** Umowa ramowa, przy której kliknięto „Dodaj" — preselekcja, nie blokada. */
  initialFrameworkId: number | null;
  onCreated: (created: ExecutiveContractRead) => void;
}

export function AddExecutiveContractModal({
  clientId,
  open,
  onOpenChange,
  frameworks,
  initialFrameworkId,
  onCreated,
}: Props) {
  const [frameworkId, setFrameworkId] = useState<string>(
    initialFrameworkId != null ? String(initialFrameworkId) : "",
  );
  const [number, setNumber] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Każde otwarcie startuje od świeżego formularza z preselekcją klikniętej
  // ramowej — okno żyje w rodzicu przez cały czas, więc sam `useState`
  // pamiętałby wpisy z poprzedniego razu.
  useEffect(() => {
    if (!open) return;
    setFrameworkId(initialFrameworkId != null ? String(initialFrameworkId) : "");
    setNumber("");
    setNotes("");
    setError(null);
  }, [open, initialFrameworkId]);

  const mutation = useMutation({
    mutationFn: () =>
      executiveContractsApi.create(clientId, {
        framework_contract_id: Number(frameworkId),
        number: number.trim(),
        notes: notes.trim() || null,
      }),
    onSuccess: (created) => {
      onCreated(created);
      onOpenChange(false);
    },
    onError: (err: unknown) => {
      setError(apiErrorMessage(err, "Nie udało się dodać umowy wykonawczej."));
    },
  });

  const canSubmit = frameworkId !== "" && number.trim() !== "" && !mutation.isPending;

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (mutation.isPending) return;
        onOpenChange(next);
      }}
      title="Dodaj umowę wykonawczą"
      description="Umowa wykonawcza wisi pod umową ramową (częścią). Konsultanci i zamówienia są przypisywane do niej, nie do części."
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
            Zapisz umowę wykonawczą
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

        <p className="text-xs text-muted-foreground" role="note">
          Nowa umowa wykonawcza dostaje status Aktywna.
        </p>

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
      </form>
    </AppModal>
  );
}
