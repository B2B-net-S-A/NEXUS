"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { AppModal } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderLineRead,
  SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { formatPLN } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: number;
  group: OrderGroupRead | null;
  line: OrderLineRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: SwapConsultantInput) => void;
}

export function SwapConsultantModal({
  open,
  onOpenChange,
  clientId,
  group,
  line,
  submitting,
  error,
  onSubmit,
}: Props) {
  const [contractId, setContractId] = useState("");
  const [rateCost, setRateCost] = useState("");
  const [rateRevenue, setRateRevenue] = useState("");
  const [swapDate, setSwapDate] = useState("");

  const contracts = useQuery({
    queryKey: ["client-contracts-for-order-line", clientId],
    queryFn: async () =>
      (await dlPortalApi.listActiveContractsForExtension(clientId)).data,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setContractId("");
    setRateCost("");
    setRateRevenue("");
    setSwapDate(new Date().toISOString().slice(0, 10));
  }, [open]);

  // Przeliczenie liczone też tutaj, żeby operator zobaczył wynik PRZED
  // zapisem. Autorytetem pozostaje serwer — to jest podgląd, nie źródło
  // wartości zapisywanej w bazie.
  const preview = useMemo(() => {
    const oldRemaining = line?.md_remaining ?? null;
    const oldRate = line?.rate_revenue ?? null;
    const newRate = parseDecimalInput(rateRevenue);
    if (oldRemaining === null || oldRate === null || !newRate || newRate <= 0) {
      return null;
    }
    const valuePln = oldRemaining * oldRate;
    return { valuePln, mdNew: valuePln / newRate };
  }, [line, rateRevenue]);

  const canSubmit =
    !submitting &&
    contractId !== "" &&
    parseDecimalInput(rateCost) !== null &&
    (parseDecimalInput(rateRevenue) ?? 0) > 0 &&
    swapDate !== "";

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Zamień kontraktora"
      description={
        group && line
          ? `Zamówienie nr ${group.order_number} · ${line.consultant_name}`
          : undefined
      }
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() =>
              onSubmit({
                contract_id: Number(contractId),
                rate_cost: parseDecimalInput(rateCost) as number,
                rate_revenue: parseDecimalInput(rateRevenue) as number,
                swap_date: swapDate,
              })
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zamienianie…" : "Zamień kontraktora"}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <div className="rounded-md bg-muted/50 px-3 py-2 text-sm">
          <p className="text-muted-foreground">Odchodzi</p>
          <p className="font-medium text-foreground">
            {line?.consultant_name} —{" "}
            {line?.rate_revenue === null || line?.rate_revenue === undefined
              ? "—"
              : `${formatPLN(line.rate_revenue)}/MD`}
            , pozostało {formatMd(line?.md_remaining ?? null)} MD
          </p>
        </div>

        <div>
          <label htmlFor="swap-contract" className={labelClass}>
            Nowy konsultant *
          </label>
          {contracts.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Nie udało się wczytać listy konsultantów.{" "}
              <button type="button" onClick={() => contracts.refetch()} className="underline">
                Ponów
              </button>
            </p>
          ) : (
            <select
              id="swap-contract"
              value={contractId}
              onChange={(e) => setContractId(e.target.value)}
              className={inputClass}
            >
              <option value="">
                {contracts.isLoading ? "Wczytywanie…" : "— wybierz konsultanta —"}
              </option>
              {contracts.data
                ?.filter((c) => c.contract_id !== line?.contract_id)
                .map((c) => (
                  <option key={c.contract_id} value={c.contract_id}>
                    {c.candidate_name}
                  </option>
                ))}
            </select>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="swap-cost" className={labelClass}>
              Stawka kosztowa (zł/MD) *
            </label>
            <input
              id="swap-cost"
              inputMode="decimal"
              value={rateCost}
              onChange={(e) => setRateCost(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="swap-revenue" className={labelClass}>
              Stawka przychodowa (zł/MD) *
            </label>
            <input
              id="swap-revenue"
              inputMode="decimal"
              value={rateRevenue}
              onChange={(e) => setRateRevenue(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="swap-date" className={labelClass}>
              Data zamiany *
            </label>
            <input
              id="swap-date"
              type="date"
              value={swapDate}
              onChange={(e) => setSwapDate(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-3 text-sm">
          <p className="mb-1 flex items-center gap-2 font-medium text-foreground">
            Przeliczenie MD <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </p>
          {preview === null ? (
            <p className="text-muted-foreground">
              Podaj stawkę przychodową nowego konsultanta, żeby zobaczyć przeliczenie.
            </p>
          ) : (
            <p className="text-muted-foreground">
              Wartość pozostała {formatPLN(preview.valuePln)} zostaje bez zmian →{" "}
              <strong className="text-foreground">{formatMd(preview.mdNew)} MD</strong> dla
              nowego konsultanta.
            </p>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            Zamiana działa od dnia zamiany w przód. MD zaraportowane wcześniej
            zostają rozliczone stawką poprzednika.
          </p>
        </div>
      </div>
    </AppModal>
  );
}
