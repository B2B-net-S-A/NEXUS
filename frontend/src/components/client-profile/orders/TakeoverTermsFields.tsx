"use client";

import type {
  MdTransferMethod,
  OrderLineRead,
  OrderLineTakeoverInput,
} from "@/lib/api/orderGroups";
import {
  effectiveTransferMethod,
  sourceDepartingRate,
  sourceRemainingMd,
  transferPreview,
} from "@/lib/order-takeover";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { formatDate } from "@/types/client-profile";

import { MdTransferChoice } from "./MdTransferChoice";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

/** Warunki wejścia nowej osoby za odchodzącą — wspólne dla karty szkicu,
 *  decyzji o MD i „Zastąp kimś innym". */
export interface TakeoverTermsValue {
  entryDate: string;
  rateCost: string;
  rateRevenue: string;
  method: MdTransferMethod | null;
}

export function emptyTakeoverTerms(entryDate: string, rateCost = ""): TakeoverTermsValue {
  return { entryDate, rateCost, rateRevenue: "", method: null };
}

/** Czy da się zapisać — ta sama reguła, której pilnuje serwer. */
export function takeoverTermsError(
  value: TakeoverTermsValue,
  departing: OrderLineRead | null,
): string | null {
  if (!departing) return "Wybierz osobę, za którą wchodzi.";
  if (!value.entryDate) return "Podaj datę wejścia.";
  if (
    departing.takeover_source === "leaving" &&
    departing.departure_date &&
    value.entryDate <= departing.departure_date
  ) {
    return `Data wejścia musi przypadać po ${formatDate(departing.departure_date)}.`;
  }
  if (parseDecimalInput(value.rateCost) == null) return "Podaj stawkę kosztową.";
  if ((parseDecimalInput(value.rateRevenue) ?? 0) <= 0) {
    return "Podaj stawkę przychodową.";
  }
  if (effectiveTransferMethod(departing.pool_unit, value.method) == null) {
    return "Wybierz sposób przeliczenia pozostałych MD.";
  }
  return null;
}

export function toTakeoverInput(
  value: TakeoverTermsValue,
  contractId: number,
  departing: OrderLineRead,
): OrderLineTakeoverInput {
  return {
    contract_id: contractId,
    departing_order_id: departing.id,
    entry_date: value.entryDate,
    rate_cost: parseDecimalInput(value.rateCost) as number,
    rate_revenue: parseDecimalInput(value.rateRevenue) as number,
    md_transfer_method: effectiveTransferMethod(departing.pool_unit, value.method),
    expected_case_version:
      departing.offboarding_case?.status === "pending"
        ? departing.offboarding_case.version
        : null,
  };
}

interface Props {
  idPrefix: string;
  departing: OrderLineRead;
  incomingName: string;
  value: TakeoverTermsValue;
  onChange: (value: TakeoverTermsValue) => void;
  /** Podpowiedź pod stawką kosztową, np. „Z kontraktu: 85 PLN/h × 8". */
  costNote?: string | null;
}

export function TakeoverTermsFields({
  idPrefix,
  departing,
  incomingName,
  value,
  onChange,
  costNote,
}: Props) {
  const preview = transferPreview({
    unit: departing.pool_unit,
    remaining: sourceRemainingMd(departing),
    departingRate: sourceDepartingRate(departing),
    incomingRate: parseDecimalInput(value.rateRevenue),
  });
  const set = (patch: Partial<TakeoverTermsValue>) => onChange({ ...value, ...patch });
  const scheduled = departing.takeover_source === "leaving";

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor={`${idPrefix}-entry`} className={labelClass}>
            Data wejścia *
          </label>
          <input
            id={`${idPrefix}-entry`}
            type="date"
            value={value.entryDate}
            onChange={(event) => set({ entryDate: event.target.value })}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor={`${idPrefix}-cost`} className={labelClass}>
            Stawka koszt (zł/MD) *
          </label>
          <input
            id={`${idPrefix}-cost`}
            inputMode="decimal"
            value={value.rateCost}
            onChange={(event) =>
              set({ rateCost: sanitizeDecimalInput(event.target.value) })
            }
            className={inputClass}
          />
          {costNote ? (
            <p className="mt-1 text-xs text-muted-foreground">{costNote}</p>
          ) : null}
        </div>
        <div>
          <label htmlFor={`${idPrefix}-revenue`} className={labelClass}>
            Stawka przychód (zł/MD) *
          </label>
          <input
            id={`${idPrefix}-revenue`}
            inputMode="decimal"
            value={value.rateRevenue}
            onChange={(event) =>
              set({ rateRevenue: sanitizeDecimalInput(event.target.value) })
            }
            className={inputClass}
          />
        </div>
      </div>

      <MdTransferChoice
        name={`${idPrefix}-method`}
        preview={preview}
        incomingName={incomingName}
        departingName={departing.consultant_name}
        value={value.method}
        onChange={(method) => set({ method })}
      />

      {scheduled ? (
        <p
          role="status"
          className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
        >
          Zastępstwo zaplanowane: {departing.consultant_name} pracuje do{" "}
          {formatDate(departing.departure_date ?? null)}. W dniu wejścia system
          aktywuje {incomingName || "nową osobę"} i przeniesie pozostałe na ten
          dzień MD.
        </p>
      ) : null}
    </div>
  );
}
