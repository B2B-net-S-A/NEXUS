"use client";
// Okno aneksu dodawanego w zakładce „Aneksy” (wariant A, 19.11.2026): zmiana
// stawki, zakresu albo przedłużenie. Dawniej formularz rozwijał się nad
// tabelą w miejscu przycisków; pola, ostrzeżenia i zapis są te same.
import type { FormEvent } from "react";
import { AlertCircle } from "lucide-react";
import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { AnnexClientRateImpact } from "@/components/contracts/AnnexClientRateImpact";
import type { ManualAmendmentType } from "./AddAnnexMenu";
import { AMENDMENT_TYPE_LABELS } from "./amendments-timeline";

export interface AmendmentFormValues {
  amendment_type: ManualAmendmentType;
  effective_date: string;
  reason: string;
  new_end_date: string;
  new_rate_candidate: string;
  new_rate_client: string;
  new_project_name: string;
  new_team_name: string;
}

export interface AmendmentFormDialogProps {
  open: boolean;
  formId: string;
  form: AmendmentFormValues;
  onChange: (next: AmendmentFormValues) => void;
  onSubmit: (event: FormEvent) => void;
  onClose: () => void;
  error: string;
  pending: boolean;
  contractId: number;
  canAmendRates: boolean;
  canViewFinance: boolean;
  /** Aneks stawki z Generatora aneksów czeka na podpis — druga zmiana tej samej stawki. */
  waitingRateAnnex: boolean;
}

const FIELD = "w-full rounded-lg border border-border bg-card px-3 py-2 text-sm dark:bg-muted";
const LABEL = "mb-1 block text-xs text-muted-foreground";

export function AmendmentFormDialog({
  open,
  formId,
  form,
  onChange,
  onSubmit,
  onClose,
  error,
  pending,
  contractId,
  canAmendRates,
  canViewFinance,
  waitingRateAnnex,
}: AmendmentFormDialogProps) {
  const set = (patch: Partial<AmendmentFormValues>) => onChange({ ...form, ...patch });
  const rate = form.amendment_type === "rate_change";
  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="lg"
      title={AMENDMENT_TYPE_LABELS[form.amendment_type]}
      description="Aneks dodany tutaj działa od razu, bez dokumentu do podpisu."
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button type="submit" form={formId} disabled={pending}>
            {pending ? "Zapisywanie…" : "Zapisz aneks"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={onSubmit} className="space-y-3">
        {error ? (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden /> {error}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block">
            <span className={LABEL}>Data wejścia w życie</span>
            <input
              type="date"
              value={form.effective_date}
              onChange={(e) => set({ effective_date: e.target.value })}
              className={FIELD}
            />
          </label>

          {/* Wcześniejsze zakończenie nie jest już aneksem z tego formularza —
              idzie oknem „Zakończ współpracę” (audyt 24.09, S5: backend
              odmawia `termination_required`). */}
          {form.amendment_type === "extension" && (
            <label className="block">
              <span className={LABEL}>Nowa data zakończenia</span>
              <input
                type="date"
                value={form.new_end_date}
                onChange={(e) => set({ new_end_date: e.target.value })}
                className={FIELD}
              />
            </label>
          )}
        </div>

        {rate && waitingRateAnnex && (
          <p className="rounded-lg bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            Aneks zmiany stawki z Generatora aneksów czeka na podpis — po jego
            podpisaniu stawka zmieni się jeszcze raz. Jeśli to ta sama zmiana,
            oznacz tamten aneks jako podpisany zamiast zapisywać stawkę tutaj.
          </p>
        )}
        {rate && canAmendRates && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block">
              <span className={LABEL}>Nowa stawka kandydata</span>
              <input
                type="number"
                step="0.001"
                value={form.new_rate_candidate}
                onChange={(e) => set({ new_rate_candidate: e.target.value })}
                className={FIELD}
              />
            </label>
            <label className="block">
              <span className={LABEL}>Nowa stawka klienta</span>
              <input
                type="number"
                step="0.001"
                value={form.new_rate_client}
                onChange={(e) => set({ new_rate_client: e.target.value })}
                className={FIELD}
              />
            </label>
          </div>
        )}
        {rate && canAmendRates && canViewFinance && (
          <AnnexClientRateImpact
            contractId={contractId}
            effectiveDate={form.effective_date}
            newRateClient={form.new_rate_client}
          />
        )}

        {form.amendment_type === "scope_change" && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block">
              <span className={LABEL}>Nowy projekt</span>
              <input
                type="text"
                value={form.new_project_name}
                onChange={(e) => set({ new_project_name: e.target.value })}
                className={FIELD}
              />
            </label>
            <label className="block">
              <span className={LABEL}>Nowy zespół</span>
              <input
                type="text"
                value={form.new_team_name}
                onChange={(e) => set({ new_team_name: e.target.value })}
                className={FIELD}
              />
            </label>
          </div>
        )}

        <label className="block">
          <span className={LABEL}>Powód / uwagi</span>
          <textarea
            rows={2}
            value={form.reason}
            onChange={(e) => set({ reason: e.target.value })}
            className={FIELD}
          />
        </label>
      </form>
    </AppModal>
  );
}
