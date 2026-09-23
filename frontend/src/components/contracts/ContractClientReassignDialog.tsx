"use client";

/**
 * „Przepnij na innego klienta” — tylko admin. Wybór klienta → podgląd z serwera
 * (co przejdzie, co blokuje) → potwierdzenie z odciskiem. Blokery pokazujemy
 * listą po polsku; „Przepnij” jest wyłączone, dopóki plan ich nie ma zero.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
import { apiErrorMessage } from "@/lib/api-error";
import {
  applyReassign,
  contractReassignKeys,
  fetchReassignPreview,
  planFromConflict,
  type ReassignPlan,
} from "@/lib/api/contractClientReassign";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contractId: number;
  currentClientName: string | null;
  onDone?: (plan: ReassignPlan) => void;
}

export function ReassignPlanView({ plan }: { plan: ReassignPlan }) {
  const movedOrders = plan.orders.filter((o) => o.client_id === plan.from_client.id);
  return (
    <div className="space-y-3 text-sm">
      <p className="flex flex-wrap items-center gap-2 font-medium">
        {plan.from_client.name}
        <ArrowRight className="h-4 w-4 text-muted-foreground" aria-hidden />
        {plan.to_client.name}
      </p>
      {plan.blockers.length > 0 ? (
        <div role="alert" className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 p-3">
          <p className="flex items-center gap-2 font-medium text-destructive">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            Przepięcie jest zablokowane — najpierw rozwiąż:
          </p>
          <ul className="list-disc space-y-1 pl-5 text-foreground">
            {plan.blockers.map((b) => (
              <li key={b.code}>{b.message}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted-foreground">Zamówienia</dt>
        <dd>{movedOrders.length ? movedOrders.map((o) => `${o.title} (#${o.id})`).join(", ") : "brak"}</dd>
        <dt className="text-muted-foreground">Umowy B2B</dt>
        <dd>
          {plan.b2b_documents.length
            ? plan.b2b_documents.map((d) => d.contract_number).join(", ")
            : "brak"}
        </dd>
        <dt className="text-muted-foreground">Otwarte braki zamówień</dt>
        <dd>{plan.open_gaps.length || "brak"}</dd>
        <dt className="text-muted-foreground">Alerty do zamknięcia</dt>
        <dd>{plan.alerts.length || "brak"}</dd>
      </dl>
      {plan.warnings.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {plan.warnings.map((w) => (
            <li key={w.code}>{w.message}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ContractClientReassignDialog({ open, onOpenChange, contractId, currentClientName, onDone }: Props) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<ClientRef | null>(null);
  const [override, setOverride] = useState<ReassignPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const preview = useQuery({
    queryKey: contractReassignKeys.preview(contractId, target?.id ?? null),
    queryFn: () => fetchReassignPreview(contractId, target!.id),
    enabled: open && target !== null,
    staleTime: 0,
  });
  const plan = override && override.to_client.id === target?.id ? override : preview.data ?? null;

  const apply = useMutation({
    mutationFn: (p: ReassignPlan) => applyReassign(contractId, p.to_client.id, p.fingerprint),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      void queryClient.invalidateQueries({ queryKey: ["contract", String(contractId)] });
      void queryClient.invalidateQueries({ queryKey: ["contracts"] });
      onDone?.(result);
      onOpenChange(false);
    },
    onError: (err) => {
      const fresh = planFromConflict(err);
      if (fresh) {
        setOverride(fresh);
        setError(
          fresh.blockers.length
            ? "Przepięcie jest zablokowane — lista poniżej."
            : "Od podglądu coś się zmieniło. Sprawdź podgląd jeszcze raz i potwierdź.",
        );
        return;
      }
      setError(apiErrorMessage(err, "Nie udało się przepiąć kontraktu."));
    },
  });

  const close = (next: boolean) => {
    if (!next) {
      setTarget(null);
      setOverride(null);
      setError(null);
    }
    onOpenChange(next);
  };

  return (
    <AppModal
      open={open}
      onOpenChange={close}
      title="Przepnij kontrakt na innego klienta"
      description={`Obecny klient: ${currentClientName ?? "—"}. Zmienia się klient kontraktu, jego zamówień i wygenerowanych umów B2B — treść podpisanych dokumentów zostaje bez zmian.`}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={() => close(false)}>
            Anuluj
          </Button>
          <Button
            variant="primary"
            disabled={!plan || !plan.can_apply || apply.isPending || preview.isFetching}
            onClick={() => plan && apply.mutate(plan)}
          >
            {apply.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Przepnij
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1">
          <p className="text-sm font-medium">Klient docelowy</p>
          <ClientSinglePicker
            value={target}
            onChange={(c) => {
              setTarget(c);
              setOverride(null);
              setError(null);
            }}
            queryKey="contract-reassign-clients"
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {target === null ? (
          <p className="text-sm text-muted-foreground">Wybierz klienta, żeby zobaczyć, co zostanie przeniesione.</p>
        ) : preview.isError && !override ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(preview.error, "Nie udało się policzyć podglądu.")}
          </p>
        ) : plan ? (
          <ReassignPlanView plan={plan} />
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Liczę podgląd…
          </p>
        )}
      </div>
    </AppModal>
  );
}
