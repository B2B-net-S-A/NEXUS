"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderLineTakeoverInput,
} from "@/lib/api/orderGroups";
import { contractCostRatePerMd, defaultEntryDate } from "@/lib/order-takeover";
import { warsawToday } from "@/lib/warsaw-date";

import {
  TakeoverTermsFields,
  emptyTakeoverTerms,
  takeoverTermsError,
  toTakeoverInput,
  type TakeoverTermsValue,
} from "./TakeoverTermsFields";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: number;
  group: OrderGroupRead | null;
  line: OrderLineRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderLineTakeoverInput) => void;
}

/** „Zastąp kimś innym" na zamówieniu z pulą MD per osoba (ticket 09.2026):
 *  nowa osoba przejmuje pozostałe MD tej, która odeszła — ta sama reguła co
 *  „Wejdź za konsultanta" z karty szkicu. */
export function ReplaceWithTakeoverModal({
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
  const [terms, setTerms] = useState<TakeoverTermsValue>(
    emptyTakeoverTerms(warsawToday()),
  );
  const contracts = useQuery({
    queryKey: ["client-contracts-for-order-line", clientId],
    queryFn: async () =>
      (await dlPortalApi.listActiveContractsForExtension(clientId)).data,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setContractId("");
    setTerms(
      emptyTakeoverTerms(defaultEntryDate(line?.departure_date ?? null, warsawToday())),
    );
  }, [open, line?.id, line?.departure_date]);

  const person =
    contracts.data?.find((item) => String(item.contract_id) === contractId) ?? null;
  const costSuggestion = person
    ? contractCostRatePerMd(person.rate_candidate, person.rate_unit)
    : null;
  const termsError = takeoverTermsError(terms, line);
  const canSubmit = !submitting && person !== null && termsError === null;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Zastąp kimś innym"
      description={
        group && line
          ? `Zamówienie nr ${group.order_number} · za ${line.consultant_name}`
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
              person && line && onSubmit(toTakeoverInput(terms, person.contract_id, line))
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Zapisz zastępstwo"}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}
        <div>
          <label
            htmlFor="replace-takeover-contract"
            className="mb-1 block text-xs font-semibold text-muted-foreground"
          >
            Nowa osoba *
          </label>
          {contracts.isError ? (
            <p role="alert" className="text-sm text-destructive">
              Nie udało się wczytać listy konsultantów.{" "}
              <button
                type="button"
                onClick={() => contracts.refetch()}
                className="underline"
              >
                Ponów
              </button>
            </p>
          ) : (
            <select
              id="replace-takeover-contract"
              value={contractId}
              onChange={(event) => {
                setContractId(event.target.value);
                const next = contracts.data?.find(
                  (item) => String(item.contract_id) === event.target.value,
                );
                const suggestion = next
                  ? contractCostRatePerMd(next.rate_candidate, next.rate_unit)
                  : null;
                setTerms((current) => ({
                  ...current,
                  rateCost: suggestion ? String(suggestion.value) : current.rateCost,
                }));
              }}
              className={inputClass}
            >
              <option value="">
                {contracts.isLoading ? "Wczytywanie…" : "— wybierz konsultanta —"}
              </option>
              {contracts.data
                ?.filter((item) => item.contract_id !== line?.contract_id)
                .map((item) => (
                  <option key={item.contract_id} value={item.contract_id}>
                    {item.candidate_name}
                  </option>
                ))}
            </select>
          )}
        </div>
        {line ? (
          <TakeoverTermsFields
            idPrefix="replace-takeover"
            departing={line}
            incomingName={person?.candidate_name ?? ""}
            value={terms}
            onChange={setTerms}
            costNote={costSuggestion?.note ?? null}
          />
        ) : null}
      </div>
    </AppModal>
  );
}
