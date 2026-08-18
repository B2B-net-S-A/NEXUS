"use client";

import { useEffect, useMemo, useState } from "react";

import { AppModal } from "@/components/ds";
import type {
  ConsultantOption,
  OrderGroupRead,
  OrderInputMode,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { ConsultantPicker } from "./ConsultantPicker";
import { formatMd } from "./MdBudgetBar";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass =
  "mb-1 block text-xs font-semibold text-muted-foreground";

export interface LineFormValues {
  /** Dokładnie jedno z pól. `contract_id` — osoba ma już kontrakt u tego
   *  klienta; `candidate_id` — osoba z bazy Nexus, kontrakt założy serwer. */
  contract_id?: number | null;
  candidate_id?: number | null;
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

  const [person, setPerson] = useState<ConsultantOption | null>(null);
  const [rateCost, setRateCost] = useState("");
  const [rateRevenue, setRateRevenue] = useState("");
  const [inputMode, setInputMode] = useState<OrderInputMode>("md");
  const [inputValue, setInputValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [remaining, setRemaining] = useState("");

  useEffect(() => {
    if (!open) return;
    setPerson(null);
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
    (editing || person !== null) &&
    parseDecimalInput(rateCost) !== null &&
    (parseDecimalInput(rateRevenue) ?? 0) > 0 &&
    parseDecimalInput(inputValue) !== null &&
    startDate !== "";

  const submit = () => {
    if (!canSubmit) return;
    onSubmit({
      // Edycja nie zmienia osoby, więc linia zostaje przy swoim kontrakcie.
      // Dodanie wysyła DOKŁADNIE JEDNO pole — dwa naraz serwer odrzuca, żeby
      // nie musiał zgadywać, kogo operator naprawdę wskazał.
      ...(editing
        ? { contract_id: line?.contract_id }
        : person?.contract_id != null
          ? { contract_id: person.contract_id }
          : { candidate_id: person?.candidate_id }),
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
            <span className={labelClass}>Konsultant *</span>
            <ConsultantPicker
              clientId={clientId}
              value={person}
              onChange={setPerson}
              enabled={open}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Osoby z rekrutacji u tego klienta oraz pozostali aktywni
              konsultanci z bazy Nexus. Wybór z obu źródeł działa tak samo.
            </p>
            {person && person.contract_id === null ? (
              /* Zapis założy tej osobie kontrakt u klienta — operator ma o tym
                 wiedzieć PRZED kliknięciem, a nie dowiedzieć się z rejestru
                 kontraktów. */
              <p className="mt-1 text-xs text-muted-foreground">
                Ta osoba nie ma jeszcze kontraktu u tego klienta — zapis założy
                go w statusie <strong>szkic</strong>.
              </p>
            ) : null}
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
