"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw, UserPlus } from "lucide-react";
import {
  contractsApi,
  type ContractTerminationReversalPlan,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { AppModal } from "@/components/ds/AppModal";

/**
 * Dwie osobne akcje na zakończonym kontrakcie (ticket 09.2026):
 *
 * - „Cofnij zakończenie" — kontrakt zakończono przez pomyłkę; kontrakt
 *   i zamówienia wracają do stanu sprzed zakończenia,
 * - „Powrót po przerwie" — konsultant naprawdę odszedł i wraca; powstaje
 *   nowy kontrakt (szkic) powiązany z tym.
 *
 * O dostępności akcji mówi backend (`can_reverse_termination`,
 * `can_return_after_break`), o roli — `canRecoverContractTermination`.
 */

const ORDER_STATUS_LABEL: Record<string, string> = {
  draft: "Szkic",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

const CONTRACT_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  ready_for_signature: "Do podpisu",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
  void: "Anulowany",
};

function dateOrIndefinite(value: string | null): string {
  return value ? formatIsoDatePl(value) : "bezterminowo";
}

function invalidateAfterRecovery(
  qc: ReturnType<typeof useQueryClient>,
  contractId: number,
) {
  qc.invalidateQueries({ queryKey: ["contract", contractId] });
  qc.invalidateQueries({ queryKey: ["contract-activities", contractId] });
  qc.invalidateQueries({ queryKey: ["contracts-v2"] });
  qc.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
  qc.invalidateQueries({ queryKey: ["contractors-v2"] });
  qc.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
  qc.invalidateQueries({ queryKey: ["client-profile"] });
  qc.invalidateQueries({ queryKey: ["client-order-groups"] });
  qc.invalidateQueries({ queryKey: ["dl-orders-grouped"] });
  qc.invalidateQueries({ queryKey: ["order-group-events"] });
  qc.invalidateQueries({ queryKey: ["dl-alerts"] });
}

interface PanelProps {
  contractId: number;
  canReverse: boolean;
  canReturn: boolean;
}

export function ContractTerminationRecoveryPanel({
  contractId,
  canReverse,
  canReturn,
}: PanelProps) {
  const [open, setOpen] = useState<"reverse" | "return" | null>(null);
  if (!canReverse && !canReturn) return null;
  return (
    <div
      className="rounded-lg border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 p-4 space-y-3"
      data-testid="termination-recovery"
    >
      <div>
        <h3 className="text-sm font-semibold">Zakończenie współpracy — korekta</h3>
        <p className="text-xs text-muted-foreground">
          Wybierz, co się naprawdę wydarzyło. To dwie różne operacje.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {canReverse && (
          <button
            type="button"
            onClick={() => setOpen("reverse")}
            className="text-left rounded-md border border-border bg-card p-3 hover:border-primary"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <RotateCcw className="w-4 h-4" /> Cofnij zakończenie
            </span>
            <span className="block text-xs text-muted-foreground mt-1">
              Kontrakt zakończono przez pomyłkę. Kontrakt i zamówienia wracają do
              stanu sprzed zakończenia, tak jakby go nie było.
            </span>
          </button>
        )}
        {canReturn && (
          <button
            type="button"
            onClick={() => setOpen("return")}
            className="text-left rounded-md border border-border bg-card p-3 hover:border-primary"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <UserPlus className="w-4 h-4" /> Powrót po przerwie
            </span>
            <span className="block text-xs text-muted-foreground mt-1">
              Konsultant zakończył współpracę i wraca. Powstaje nowy kontrakt
              (Draft) powiązany z tym; ten zostaje zakończony bez zmian.
            </span>
          </button>
        )}
      </div>
      {open === "reverse" && (
        <ReverseTerminationDialog
          contractId={contractId}
          onClose={() => setOpen(null)}
        />
      )}
      {open === "return" && (
        <ReturnAfterBreakDialog
          contractId={contractId}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

export function ReverseTerminationPlanView({
  plan,
}: {
  plan: ContractTerminationReversalPlan;
}) {
  const c = plan.contract;
  return (
    <div className="space-y-4 text-sm">
      {plan.blockers.length > 0 && (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 p-3 space-y-1"
        >
          <p className="flex items-center gap-2 font-medium text-destructive">
            <AlertTriangle className="w-4 h-4" /> Cofnięcie jest zablokowane
          </p>
          <ul className="list-disc pl-5 text-xs">
            {plan.blockers.map((b, i) => (
              <li key={`${b.code}-${i}`}>{b.message}</li>
            ))}
          </ul>
        </div>
      )}
      <section>
        <h4 className="text-xs font-semibold uppercase text-muted-foreground">Kontrakt</h4>
        <ul className="mt-1 space-y-0.5">
          <li>
            Status: {CONTRACT_STATUS_LABEL[c.status_now] ?? c.status_now} →{" "}
            <strong>{CONTRACT_STATUS_LABEL[c.status_target] ?? c.status_target}</strong>
          </li>
          <li>
            Data końca umowy: {dateOrIndefinite(c.end_date_now)} →{" "}
            <strong>{dateOrIndefinite(c.end_date_target)}</strong>
          </li>
          {c.clears_termination && (
            <li>Powód i data zakończenia zostaną usunięte z karty kontraktu.</li>
          )}
        </ul>
      </section>
      <section>
        <h4 className="text-xs font-semibold uppercase text-muted-foreground">
          Zamówienia do przywrócenia
        </h4>
        {plan.orders.length === 0 ? (
          <p className="text-muted-foreground mt-1">
            Zakończenie nie zmieniło żadnego zamówienia.
          </p>
        ) : (
          <ul className="mt-1 space-y-2">
            {plan.orders.map((o) => (
              <li key={o.order_id} className="rounded-md border border-border p-2">
                <div className="font-medium">
                  {o.order_label} · {o.consultant}
                </div>
                <div className="text-xs text-muted-foreground">
                  Status: {ORDER_STATUS_LABEL[o.status_now] ?? o.status_now} →{" "}
                  {ORDER_STATUS_LABEL[o.status_target] ?? o.status_target} · Koniec
                  przypisania: {dateOrIndefinite(o.end_date_now)} →{" "}
                  {dateOrIndefinite(o.end_date_target)}
                  {o.end_date_source === "history" && " (z historii zmian)"}
                  {o.end_date_source === "order_end" && " (data końca zamówienia)"}
                </div>
                {o.removes_decision_case && (
                  <div className="text-xs text-muted-foreground">
                    Znika „Wymagana decyzja o pozostałej puli MD” i jej alerty.
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Zużycie MD, pula podstawowa i opcja oraz stawki zostają bez zmian.
        </p>
      </section>
      {plan.md_imports.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Importy MD do przeliczenia
          </h4>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {plan.md_imports.map((m) => (
              <li key={m.row_id}>
                {m.period_month} · {m.filename ?? `import #${m.import_id}`} ·{" "}
                {m.md_reported} MD → {m.order_label}
                {m.skipped ? ` — pominięty: ${m.skipped}` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}
      {plan.skipped.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Bez zmian
          </h4>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {plan.skipped.map((s) => (
              <li key={s.order_id}>
                {s.order_label}: {s.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ReverseTerminationDialog({
  contractId,
  onClose,
}: {
  contractId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const preview = useQuery({
    queryKey: ["contract-termination-reversal", contractId],
    queryFn: async () =>
      (await contractsApi.terminationReversalPreview(contractId)).data,
    staleTime: 0,
  });
  const mut = useMutation({
    mutationFn: async () => (await contractsApi.reverseTermination(contractId)).data,
    onSuccess: () => {
      invalidateAfterRecovery(qc, contractId);
      onClose();
    },
  });
  const plan = preview.data;
  const blocked = !plan || plan.blockers.length > 0;
  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Cofnij zakończenie"
      description="Kontrakt zakończono przez pomyłkę — wszystko wróci do stanu sprzed zakończenia."
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-muted-foreground hover:underline"
          >
            Anuluj
          </button>
          <button
            type="button"
            disabled={blocked || mut.isPending}
            onClick={() => mut.mutate()}
            className="text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-md px-4 py-2"
          >
            {mut.isPending ? "Przywracanie…" : "Cofnij zakończenie"}
          </button>
        </>
      }
    >
      {preview.isLoading && (
        <p className="text-sm text-muted-foreground">Liczę, co wróci…</p>
      )}
      {preview.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(preview.error, "Nie udało się przygotować podglądu.")}
        </p>
      )}
      {preview.isSuccess && plan && <ReverseTerminationPlanView plan={plan} />}
      {mut.isError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {apiErrorMessage(mut.error, "Nie udało się cofnąć zakończenia.")}
        </p>
      )}
    </AppModal>
  );
}

function ReturnAfterBreakDialog({
  contractId,
  onClose,
}: {
  contractId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const [startDate, setStartDate] = useState(warsawToday());
  const mut = useMutation({
    mutationFn: async () =>
      (await contractsApi.returnAfterBreak(contractId, startDate)).data,
    onSuccess: (result) => {
      invalidateAfterRecovery(qc, contractId);
      onClose();
      router.push(`/contracts/${result.contract_id}`);
    },
  });
  const formId = `return-after-break-${contractId}`;
  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Powrót po przerwie"
      description="Konsultant wraca po zakończonej współpracy — powstanie nowy kontrakt."
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-muted-foreground hover:underline"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={!startDate || mut.isPending}
            className="text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-md px-4 py-2"
          >
            {mut.isPending ? "Tworzenie…" : "Utwórz nowy kontrakt"}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="space-y-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          mut.mutate();
        }}
      >
        <ul className="list-disc pl-5 text-xs text-muted-foreground space-y-1">
          <li>
            Nowy kontrakt w statusie Draft z plakietką „POWRÓT PO PRZERWIE” i linkiem
            do tego kontraktu. Ten kontrakt zostaje zakończony bez zmian.
          </li>
          <li>
            Na zamówieniu konsultant pojawi się jako nowe przypisanie Draft — do
            uzupełnienia (budżet, stawki). Poprzednie przypisanie zostaje
            w „Zakończonych” razem ze swoim zużyciem.
          </li>
        </ul>
        <label className="block">
          <span className="text-xs text-muted-foreground">Data startu po przerwie *</span>
          <input
            type="date"
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="mt-1 w-full border border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
          />
        </label>
        {mut.isError && (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(mut.error, "Nie udało się utworzyć kontraktu.")}
          </p>
        )}
      </form>
    </AppModal>
  );
}
