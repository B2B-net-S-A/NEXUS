"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useCancelAgreement, useMarkSigned, type Agreement } from "@/lib/api/hr-agreements";
import { warsawToday } from "@/lib/warsaw-date";

const SCAN_MAX_BYTES = 20 * 1024 * 1024;
const SCAN_TYPES = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/** Sprawdzenie skanu przed wysłaniem — serwer sprawdza treść pliku, nie nazwę. */
export function scanProblem(file: File | null): string | null {
  if (!file) return "Dołącz skan podpisanej umowy (PDF, JPG albo PNG).";
  if (!/\.(pdf|jpe?g|png)$/i.test(file.name)) return "Skan musi być plikiem PDF, JPG albo PNG.";
  if (file.size === 0 || file.size > SCAN_MAX_BYTES) return "Skan jest pusty albo większy niż 20 MB.";
  return null;
}

/**
 * „Oznacz jako podpisaną” — druga ścieżka, gdy Autenti nie jest ustawione albo
 * osoba podpisała na papierze. Skan, data podpisu i powód idą do śladu;
 * podpis i przepisanie do kartoteki dzieją się razem albo wcale.
 */
export function MarkSignedDialog({ agreement, onClose }: { agreement: Agreement; onClose: () => void }) {
  const { showToast } = useToast();
  const mark = useMarkSigned();
  const today = warsawToday();
  const [file, setFile] = useState<File | null>(null);
  const [signedOn, setSignedOn] = useState(today);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const id = `mark-signed-${agreement.id}`;

  const submit = () => {
    const problem =
      scanProblem(file) ??
      (!signedOn || signedOn > today ? "Data podpisu nie może być z przyszłości." : null) ??
      (reason.trim() ? null : "Wpisz, dlaczego podpis jest oznaczany ręcznie.");
    if (problem || !file) {
      setError(problem);
      return;
    }
    setError(null);
    mark.mutate(
      { id: agreement.id, file, signedOn, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Umowa podpisana — stawka, forma i dokument są w kartotece", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się oznaczyć podpisu.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Oznacz jako podpisaną"
      description={`${agreement.title}. Skan trafi do dokumentów osoby, a dane umowy do kartoteki.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={mark.isPending}>
            {mark.isPending ? "Zapisywanie…" : "Oznacz jako podpisaną"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <FormField label="Skan podpisanej umowy" htmlFor={`${id}-file`} required>
          <Input
            id={`${id}-file`}
            type="file"
            accept={SCAN_TYPES}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </FormField>
        <FormField label="Data podpisu" htmlFor={`${id}-date`} required>
          <Input
            id={`${id}-date`}
            type="date"
            max={today}
            value={signedOn}
            onChange={(event) => setSignedOn(event.target.value)}
          />
        </FormField>
        <FormField
          label="Powód podpisu poza Autenti"
          htmlFor={`${id}-reason`}
          description="Np. podpis na papierze w biurze. Zostaje w śladzie zmian."
          required
        >
          <Textarea
            id={`${id}-reason`}
            rows={2}
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** Anulowanie szkicu albo umowy wysłanej do podpisu (wysłaną wycofuje w Autenti). */
export function CancelAgreementDialog({ agreement, onClose }: { agreement: Agreement; onClose: () => void }) {
  const { showToast } = useToast();
  const cancel = useCancelAgreement();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!reason.trim()) {
      setError("Wpisz, dlaczego umowa jest anulowana.");
      return;
    }
    setError(null);
    cancel.mutate(
      { id: agreement.id, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Umowa anulowana", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się anulować umowy.")),
      },
    );
  };

  return (
    <AppModal
      open
      size="sm"
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Anulować umowę?"
      description={
        agreement.status === "sent"
          ? "Umowa czeka na podpis — NEXUS wycofa ją z Autenti. Zostaje na liście jako anulowana."
          : "Szkic zostaje na liście jako anulowany."
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button variant="destructive" onClick={submit} disabled={cancel.isPending}>
            {cancel.isPending ? "Anulowanie…" : "Anuluj umowę"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor={`cancel-agreement-${agreement.id}`} required>
        <Textarea
          id={`cancel-agreement-${agreement.id}`}
          rows={2}
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
