"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  OrderGroupRead,
  OrderInputMode,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { formatMd } from "./MdBudgetBar";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass =
  "mb-1 block text-xs font-semibold text-muted-foreground";

export interface LineFormValues {
  contract_id: number;
  rate_cost: number;
  rate_revenue: number;
  input_mode: OrderInputMode;
  input_value: number;
  start_date: string;
  end_date: string | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: number;
  group: OrderGroupRead | null;
  /** Ustawione = edycja istniejącej linii; puste = dodanie konsultanta. */
  line?: OrderLineRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: LineFormValues) => void;
  /** Ręczna korekta pozostałych MD — tylko w trybie edycji. */
  onAdjustRemaining?: (mdRemaining: number) => void;
}

export function ConsultantLineModal({
  open,
  onOpenChange,
  clientId,
  group,
  line,
  submitting,
  error,
  onSubmit,
  onAdjustRemaining,
}: Props) {
  const editing = Boolean(line);

  const [contractId, setContractId] = useState<string>("");
  const [rateCost, setRateCost] = useState("");
  const [rateRevenue, setRateRevenue] = useState("");
  const [inputMode, setInputMode] = useState<OrderInputMode>("md");
  const [inputValue, setInputValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [remaining, setRemaining] = useState("");

  const contracts = useQuery({
    queryKey: ["client-contracts-for-order-line", clientId],
    queryFn: async () =>
      (await dlPortalApi.listActiveContractsForExtension(clientId)).data,
    enabled: open && !editing,
  });

  useEffect(() => {
    if (!open) return;
    setContractId(line ? String(line.contract_id) : "");
    setRateCost(line?.rate_cost != null ? String(line.rate_cost) : "");
    setRateRevenue(line?.rate_revenue != null ? String(line.rate_revenue) : "");
    setInputMode(line?.input_mode ?? "md");
    setInputValue(line?.input_value != null ? String(line.input_value) : "");
    setStartDate(line?.start_date ?? group?.start_date ?? "");
    setEndDate(line?.end_date ?? "");
    setRemaining(line?.md_remaining != null ? String(line.md_remaining) : "");
  }, [open, line, group]);

  // Podgląd MD liczony na żywo — operator widzi, ile MD kupuje za wpisaną
  // kwotę, ZANIM zapisze. Bez tego tryb „kwota" jest zapisem w ciemno.
  const previewMd = useMemo(() => {
    const value = parseDecimalInput(inputValue);
    const rate = parseDecimalInput(rateRevenue);
    if (value === null) return null;
    if (inputMode === "md") return value;
    if (rate === null || rate <= 0) return null;
    return value / rate;
  }, [inputValue, rateRevenue, inputMode]);

  const canSubmit =
    !submitting &&
    (editing || contractId !== "") &&
    parseDecimalInput(rateCost) !== null &&
    (parseDecimalInput(rateRevenue) ?? 0) > 0 &&
    parseDecimalInput(inputValue) !== null &&
    startDate !== "";

  const submit = () => {
    if (!canSubmit) return;
    onSubmit({
      contract_id: Number(contractId || line?.contract_id),
      rate_cost: parseDecimalInput(rateCost) as number,
      rate_revenue: parseDecimalInput(rateRevenue) as number,
      input_mode: inputMode,
      input_value: parseDecimalInput(inputValue) as number,
      start_date: startDate,
      end_date: endDate || null,
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={editing ? "Edytuj linię konsultanta" : "Dodaj konsultanta do zamówienia"}
      description={
        group ? `Zamówienie nr ${group.order_number}` : undefined
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
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : editing ? "Zapisz" : "Dodaj konsultanta"}
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

        {!editing ? (
          <div>
            <label htmlFor="line-contract" className={labelClass}>
              Konsultant *
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
                id="line-contract"
                value={contractId}
                onChange={(e) => setContractId(e.target.value)}
                className={inputClass}
              >
                <option value="">
                  {contracts.isLoading ? "Wczytywanie…" : "— wybierz konsultanta —"}
                </option>
                {contracts.data?.map((c) => (
                  <option key={c.contract_id} value={c.contract_id}>
                    {c.candidate_name}
                    {c.initial_job_title ? ` — ${c.initial_job_title}` : ""}
                  </option>
                ))}
              </select>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              Lista zawiera konsultantów z kontraktem u tego klienta.
            </p>
          </div>
        ) : (
          <p className="text-sm text-foreground">
            Konsultant: <strong>{line?.consultant_name}</strong>
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="line-cost" className={labelClass}>
              Stawka kosztowa (zł/MD) *
            </label>
            <input
              id="line-cost"
              inputMode="decimal"
              value={rateCost}
              onChange={(e) => setRateCost(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
              placeholder="1000"
            />
          </div>
          <div>
            <label htmlFor="line-revenue" className={labelClass}>
              Stawka przychodowa (zł/MD) *
            </label>
            <input
              id="line-revenue"
              inputMode="decimal"
              value={rateRevenue}
              onChange={(e) => setRateRevenue(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
              placeholder="1200"
            />
          </div>
        </div>

        <fieldset className="rounded-md border border-border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">
            Budżet
          </legend>
          <div className="mb-3 flex gap-4">
            {(["md", "amount"] as OrderInputMode[]).map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="input-mode"
                  checked={inputMode === mode}
                  onChange={() => setInputMode(mode)}
                />
                {mode === "md" ? "Liczba MD" : "Kwota zamówienia (zł)"}
              </label>
            ))}
          </div>
          <input
            aria-label={inputMode === "md" ? "Liczba MD" : "Kwota zamówienia"}
            inputMode="decimal"
            value={inputValue}
            onChange={(e) => setInputValue(sanitizeDecimalInput(e.target.value))}
            className={inputClass}
            placeholder={inputMode === "md" ? "50" : "60000"}
          />
          <p className="mt-2 text-xs text-muted-foreground">
            {inputMode === "amount"
              ? `Budżet MD: ${previewMd === null ? "—" : formatMd(previewMd)} MD (kwota ÷ stawka przychodowa)`
              : `Budżet MD: ${previewMd === null ? "—" : formatMd(previewMd)} MD`}
          </p>
        </fieldset>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {!editing ? (
            <div>
              <label htmlFor="line-start" className={labelClass}>
                Start *
              </label>
              <input
                id="line-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className={inputClass}
              />
            </div>
          ) : null}
          <div>
            <label htmlFor="line-end" className={labelClass}>
              Koniec (puste = bezterminowo)
            </label>
            <input
              id="line-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {editing && onAdjustRemaining ? (
          <fieldset className="rounded-md border border-dashed border-border p-3">
            <legend className="px-1 text-xs font-semibold text-muted-foreground">
              Korekta ręczna
            </legend>
            <p className="mb-2 text-xs text-muted-foreground">
              Zmienia wyłącznie pozostałe MD (korekta historyczna). Zapisywana jako
              różnica, więc kolejny import miesiąca jej nie skasuje.
            </p>
            <div className="flex gap-2">
              <input
                aria-label="Pozostałe MD"
                inputMode="decimal"
                value={remaining}
                onChange={(e) => setRemaining(sanitizeDecimalInput(e.target.value))}
                className={inputClass}
              />
              <button
                type="button"
                disabled={submitting || parseDecimalInput(remaining) === null}
                onClick={() =>
                  onAdjustRemaining(parseDecimalInput(remaining) as number)
                }
                className="shrink-0 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
              >
                Skoryguj
              </button>
            </div>
          </fieldset>
        ) : null}
      </div>
    </AppModal>
  );
}
