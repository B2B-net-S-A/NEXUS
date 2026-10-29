"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AGREEMENT_TERMINATION_MODES,
  AGREEMENT_TERMINATION_PARTIES,
  attachmentDocType,
  signedOnLabel,
} from "@/lib/contract-termination";
import {
  contractsApi,
  type AgreementTerminationMode,
  type AgreementTerminationParty,
} from "@/lib/api";
import { formatIsoDatePl } from "@/lib/date-pl";

const FIELD =
  "mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950";

interface Props {
  contractId: number;
  candidateName?: string | null;
  /** Koniec projektu — podpowiedź „Ostatniego dnia umowy”. */
  projectEnd: string | null;
  onClose: () => void;
}

/**
 * „Umowa rozwiązana poza NEXUSEM” (zgłoszenie zespołu 29.10.2026): porozumienie
 * albo wypowiedzenie podpisane bez generatora, dopisane do kontraktu już
 * zakończonego. Zapisuje same dane umowy — koniec projektu, zamówienia
 * i status zostają (`PUT /api/contracts/{id}/agreement-termination`).
 * Otwierają je przypomnienie na karcie kontraktu i wiersz listy
 * „Umowa nierozwiązana”.
 */
export function ContractAgreementRecordDialog({
  contractId,
  candidateName,
  projectEnd,
  onClose,
}: Props) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<AgreementTerminationMode>("mutual_agreement");
  const [party, setParty] = useState<AgreementTerminationParty | "">("");
  const [signedOn, setSignedOn] = useState("");
  const [lastDay, setLastDay] = useState(projectEnd?.slice(0, 10) ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const blocking =
    signedOn && lastDay && lastDay < signedOn
      ? `Ostatni dzień umowy nie może być wcześniejszy niż ${
          mode === "mutual_agreement"
            ? "data zawarcia porozumienia"
            : "data złożenia wypowiedzenia"
        }.`
      : null;
  const warning =
    projectEnd && lastDay && lastDay < projectEnd.slice(0, 10)
      ? "Ostatni dzień umowy jest przed końcem projektu — konsultant pracowałby bez obowiązującej umowy."
      : null;
  const ready = Boolean(party && signedOn && lastDay) && !blocking;
  const formId = `agreement-record-${contractId}`;

  const mut = useMutation({
    mutationFn: async () => {
      await contractsApi.recordAgreementTermination(contractId, {
        mode,
        party: party as AgreementTerminationParty,
        signed_on: signedOn,
        last_day: lastDay,
      });
      // Skan osobnym żądaniem — rozwiązanie jest już zapisane, więc padnięty
      // upload tylko się pokazuje (jak w „Zakończ współpracę”).
      if (!file) return null;
      const body = new FormData();
      body.append("file", file);
      body.append("doc_type", attachmentDocType(mode));
      try {
        await contractsApi.uploadDocument(contractId, body);
        return null;
      } catch (error: unknown) {
        return apiErrorMessage(error, "Nie udało się dodać skanu.");
      }
    },
    onSuccess: (failedUpload) => {
      qc.invalidateQueries({ queryKey: ["contract", contractId] });
      qc.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      qc.invalidateQueries({ queryKey: ["contract-documents", contractId] });
      qc.invalidateQueries({ queryKey: ["contract-docs", contractId] });
      // Lista „Umowa nierozwiązana” i Generator (umowa zmienia zakładkę).
      qc.invalidateQueries({ queryKey: ["contracts-v2"] });
      qc.invalidateQueries({ queryKey: ["b2b-generated"] });
      if (failedUpload) setUploadError(failedUpload);
      else onClose();
    },
  });

  if (uploadError) {
    return (
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        title="Rozwiązanie umowy zapisane"
        footer={
          <button
            type="button"
            onClick={onClose}
            className="text-sm bg-primary text-primary-foreground rounded-md px-4 py-2"
          >
            Zamknij
          </button>
        }
      >
        <p role="alert" className="text-sm text-destructive">
          Rozwiązanie umowy jest zapisane, ale skan nie trafił do dokumentów
          kontraktu: {uploadError} Dodaj go w zakładce „Dokumenty”.
        </p>
      </AppModal>
    );
  }

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Umowa rozwiązana poza NEXUSEM"
      description={candidateName ? `Konsultant: ${candidateName}` : undefined}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={mut.isPending}
            className="text-sm text-muted-foreground hover:underline disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={!ready || mut.isPending}
            className="text-sm bg-primary text-primary-foreground rounded-md px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mut.isPending ? "Zapisywanie…" : "Zapisz rozwiązanie umowy"}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) mut.mutate();
        }}
      >
        <p className="text-sm text-muted-foreground">
          {projectEnd
            ? `Projekt zakończył się ${formatIsoDatePl(projectEnd)}. `
            : ""}
          Zapisz, jak i kiedy rozwiązano umowę B2B — kontrakt zniknie z listy
          „Umowa nierozwiązana”, a zakończenie projektu zostaje bez zmian.
        </p>
        <fieldset>
          <legend className="text-xs text-muted-foreground">Tryb *</legend>
          <div className="mt-1 flex flex-wrap gap-4">
            {AGREEMENT_TERMINATION_MODES.map((m) => (
              <label key={m.value} className="flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name={`${formId}-mode`}
                  value={m.value}
                  checked={mode === m.value}
                  onChange={() => setMode(m.value)}
                />
                {m.label}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="text-xs text-muted-foreground">
            Strona * (kto wypowiedział albo zainicjował porozumienie)
          </legend>
          <div className="mt-1 flex flex-wrap gap-4">
            {AGREEMENT_TERMINATION_PARTIES.map((p) => (
              <label key={p.value} className="flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name={`${formId}-party`}
                  value={p.value}
                  checked={party === p.value}
                  onChange={() => setParty(p.value)}
                />
                {p.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs text-muted-foreground">{signedOnLabel(mode)} *</span>
            <input
              type="date"
              value={signedOn}
              onChange={(e) => setSignedOn(e.target.value)}
              className={FIELD}
            />
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">Ostatni dzień umowy *</span>
            <input
              type="date"
              value={lastDay}
              onChange={(e) => setLastDay(e.target.value)}
              className={FIELD}
            />
          </label>
        </div>
        <label className="block">
          <span className="text-xs text-muted-foreground">
            Skan porozumienia albo wypowiedzenia (PDF, obraz) — trafi do „Dokumentów”
          </span>
          <input
            type="file"
            accept="application/pdf,image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        {warning && (
          <p className="rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            {warning}
          </p>
        )}
        {blocking && (
          <p role="alert" className="text-xs text-destructive">
            {blocking}
          </p>
        )}
        {mut.isError && (
          <p role="alert" className="text-xs text-destructive">
            {apiErrorMessage(mut.error, "Nie udało się zapisać rozwiązania umowy.")}
          </p>
        )}
      </form>
    </AppModal>
  );
}
