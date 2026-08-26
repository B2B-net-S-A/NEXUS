"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, FileSearch, Trash2 } from "lucide-react";

import { AppModal, FileDropZone } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  OrderGroupExtendInput,
  OrderGroupRead,
  OrderLineInput,
} from "@/lib/api/orderGroups";
import {
  extractionErrorMessage,
  findConflicts,
  numberToField,
  type ExtractionConflict,
} from "@/lib/order-extraction";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { ExtractionConflictDialog } from "./ExtractionConflictDialog";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ACCEPT = ".pdf";

/** Dzień po dacie — start przedłużenia domyślnie następuje po końcu poprzednika. */
function dayAfter(iso: string | null): string {
  if (!iso) return "";
  const parsed = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "";
  parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString().slice(0, 10);
}

interface CarryLine {
  lineId: number;
  contractId: number;
  consultantName: string;
  selected: boolean;
  rateCost: string;
  rateRevenue: string;
  /** Liczba MD nowego budżetu — puste na zamówieniu kosztowym. */
  mdTotal: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: number;
  group: OrderGroupRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderGroupExtendInput, file: File | null) => void;
}

/**
 * „Dodaj przedłużenie" dla zamówienia wielo-konsultantowego.
 *
 * Tworzy NOWE zamówienie kontynuujące poprzednie, a nie edytuje starego:
 * poprzednie musi zostać w rejestrze takie, jakie było, bo to na jego
 * podstawie rozliczono już wystawione faktury.
 *
 * Konsultanci są PRZENOSZENI świadomie, z zaznaczeniem — przedłużenie
 * zamówienia rzadko obejmuje dokładnie ten sam skład, a domyślne przepisanie
 * wszystkich zostawiałoby na nowym zamówieniu osoby, które już nie pracują.
 */
export function ExtendOrderGroupModal({
  open,
  onOpenChange,
  clientId,
  group,
  submitting,
  error,
  onSubmit,
}: Props) {
  const costBased = Boolean(group?.is_cost_based);
  const sharedMdBased = Boolean(group?.is_md_budget_based);

  const [orderNumber, setOrderNumber] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [budgetAmount, setBudgetAmount] = useState("");
  const [mdBudgetTotal, setMdBudgetTotal] = useState("");
  const [lines, setLines] = useState<CarryLine[]>([]);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);

  useEffect(() => {
    if (!open) return;
    setOrderNumber("");
    setStartDate(dayAfter(group?.end_date ?? null));
    setEndDate("");
    setNotes("");
    setBudgetAmount("");
    setMdBudgetTotal("");
    setLines(
      (group?.lines ?? [])
        .filter((line) => line.is_active)
        .map((line) => ({
          lineId: line.id,
          contractId: line.contract_id,
          consultantName: line.consultant_name,
          selected: true,
          rateCost: numberToField(line.rate_cost),
          rateRevenue: numberToField(line.rate_revenue),
          mdTotal: "",
        })),
    );
    setFile(null);
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConflicts([]);
    setPendingApply(null);
  }, [open, group]);

  async function handleExtract() {
    if (!file || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(clientId, file);
      const apply = () => {
        if (data.title) setOrderNumber(data.title);
        if (data.start_date) setStartDate(data.start_date.slice(0, 10));
        if (data.end_date) setEndDate(data.end_date.slice(0, 10));
        if (costBased && data.total_value != null) {
          setBudgetAmount(String(data.total_value));
        }
        if (sharedMdBased && data.md_total != null) {
          setMdBudgetTotal(String(data.md_total));
        } else if (!costBased && data.md_total != null) {
          // Liczba MD z dokumentu dotyczy CAŁEGO zamówienia; przy jednej
          // przenoszonej osobie jest jej budżetem, przy kilku operator dzieli
          // ją sam — dlatego wpisujemy ją tylko wtedy, gdy nie ma czego dzielić.
          setLines((prev) =>
            prev.length === 1
              ? prev.map((l) => ({ ...l, mdTotal: String(data.md_total) }))
              : prev,
          );
        }
      };
      const found = findConflicts([
        {
          key: "title",
          label: "Numer zamówienia",
          current: orderNumber,
          incoming: data.title ?? null,
        },
        {
          key: "start_date",
          label: "Obowiązuje od",
          current: startDate,
          incoming: data.start_date ? data.start_date.slice(0, 10) : null,
        },
        {
          key: "end_date",
          label: "Obowiązuje do",
          current: endDate,
          incoming: data.end_date ? data.end_date.slice(0, 10) : null,
        },
        ...(costBased
          ? [
              {
                key: "total_value" as const,
                label: "Kwota zamówienia",
                current: budgetAmount,
                incoming: numberToField(data.total_value) || null,
              },
            ]
          : []),
        ...(sharedMdBased
          ? [
              {
                key: "md_total" as const,
                label: "Budżet w MD",
                current: mdBudgetTotal,
                incoming: numberToField(data.md_total) || null,
              },
            ]
          : []),
      ]);
      setCheckData(Boolean(data.uncertain));
      setCheckReasons(data.uncertain_reasons ?? []);
      if (found.length > 0) {
        setConflicts(found);
        setPendingApply(() => apply);
      } else {
        apply();
      }
    } catch (err: unknown) {
      setExtractError(
        extractionErrorMessage(err, "Nie udało się odczytać danych z dokumentu."),
      );
    } finally {
      setExtracting(false);
    }
  }

  const selected = lines.filter((line) => line.selected);
  const linesValid = selected.every(
    (line) =>
      parseDecimalInput(line.rateCost) !== null &&
      (parseDecimalInput(line.rateRevenue) ?? 0) > 0 &&
      (costBased || sharedMdBased || parseDecimalInput(line.mdTotal) !== null),
  );
  const canSubmit =
    !submitting &&
    orderNumber.trim() !== "" &&
    startDate !== "" &&
    (!costBased || budgetAmount.trim() !== "") &&
    (!sharedMdBased || (parseDecimalInput(mdBudgetTotal) ?? 0) > 0) &&
    linesValid;

  function buildLines(): OrderLineInput[] {
    return selected.map((line) => ({
      contract_id: line.contractId,
      rate_cost: parseDecimalInput(line.rateCost) as number,
      rate_revenue: parseDecimalInput(line.rateRevenue) as number,
      ...(costBased || sharedMdBased
        ? {}
        : {
            input_mode: "md" as const,
            input_value: parseDecimalInput(line.mdTotal) as number,
          }),
      start_date: startDate,
      end_date: endDate || null,
    }));
  }

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Dodaj przedłużenie"
      description={
        group
          ? `Nowe zamówienie kontynuujące zamówienie nr ${group.order_number}.`
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
                order_number: orderNumber.trim(),
                start_date: startDate,
                end_date: endDate || null,
                notes: notes.trim() || null,
                ...(costBased
                  ? { budget_amount: Number(budgetAmount.replace(",", ".")) }
                  : {}),
                ...(sharedMdBased
                  ? { md_budget_total: parseDecimalInput(mdBudgetTotal) }
                  : {}),
                lines: buildLines(),
              }, file)
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Utwórz przedłużenie"}
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

        {checkData ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900"
          >
            <AlertTriangle
              className="mt-0.5 h-4 w-4 shrink-0 text-orange-500"
              aria-hidden
            />
            <div>
              <p className="font-semibold">Sprawdź dane!</p>
              {checkReasons.length > 0 ? (
                <ul className="mt-1 list-disc pl-4">
                  {checkReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        ) : null}

        <div>
          <label htmlFor="extend-number" className={labelClass}>
            Numer zamówienia *
          </label>
          <input
            id="extend-number"
            value={orderNumber}
            onChange={(e) => setOrderNumber(e.target.value)}
            className={inputClass}
            placeholder="446"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="extend-start" className={labelClass}>
              Obowiązuje od *
            </label>
            <input
              id="extend-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="extend-end" className={labelClass}>
              Obowiązuje do (puste = bezterminowo)
            </label>
            <input
              id="extend-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {costBased ? (
          <div>
            <label htmlFor="extend-budget" className={labelClass}>
              Kwota zamówienia (zł) *
            </label>
            <input
              id="extend-budget"
              inputMode="decimal"
              value={budgetAmount}
              onChange={(e) => setBudgetAmount(e.target.value)}
              className={inputClass}
              placeholder="50000"
            />
          </div>
        ) : null}

        {sharedMdBased ? (
          <div>
            <label htmlFor="extend-md-budget" className={labelClass}>
              Budżet w MD *
            </label>
            <input
              id="extend-md-budget"
              inputMode="decimal"
              value={mdBudgetTotal}
              onChange={(e) =>
                setMdBudgetTotal(sanitizeDecimalInput(e.target.value))
              }
              className={inputClass}
              placeholder="100"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              Nowa wspólna pula MD dla całego przedłużenia.
            </p>
          </div>
        ) : null}

        <fieldset className="rounded-md border border-border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">
            Konsultanci do przeniesienia
          </legend>
          {lines.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Poprzednie zamówienie nie ma aktywnych konsultantów — dodasz ich
              po utworzeniu przedłużenia.
            </p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {lines.map((line, index) => (
                <li key={line.lineId} className="flex flex-wrap items-end gap-3 py-2">
                  <label className="flex min-w-[12rem] flex-1 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={line.selected}
                      onChange={(e) =>
                        setLines((prev) =>
                          prev.map((item, i) =>
                            i === index
                              ? { ...item, selected: e.target.checked }
                              : item,
                          ),
                        )
                      }
                      className="h-4 w-4 rounded border-border"
                    />
                    {line.consultantName}
                  </label>
                  <div className="w-28">
                    <span className={labelClass}>Kosztowa</span>
                    <input
                      aria-label={`Stawka kosztowa — ${line.consultantName}`}
                      inputMode="decimal"
                      disabled={!line.selected}
                      value={line.rateCost}
                      onChange={(e) =>
                        setLines((prev) =>
                          prev.map((item, i) =>
                            i === index
                              ? {
                                  ...item,
                                  rateCost: sanitizeDecimalInput(e.target.value),
                                }
                              : item,
                          ),
                        )
                      }
                      className={inputClass}
                    />
                  </div>
                  <div className="w-28">
                    <span className={labelClass}>Przychodowa</span>
                    <input
                      aria-label={`Stawka przychodowa — ${line.consultantName}`}
                      inputMode="decimal"
                      disabled={!line.selected}
                      value={line.rateRevenue}
                      onChange={(e) =>
                        setLines((prev) =>
                          prev.map((item, i) =>
                            i === index
                              ? {
                                  ...item,
                                  rateRevenue: sanitizeDecimalInput(e.target.value),
                                }
                              : item,
                          ),
                        )
                      }
                      className={inputClass}
                    />
                  </div>
                  {!costBased && !sharedMdBased ? (
                    <div className="w-24">
                      <span className={labelClass}>Liczba MD</span>
                      <input
                        aria-label={`Liczba MD — ${line.consultantName}`}
                        inputMode="decimal"
                        disabled={!line.selected}
                        value={line.mdTotal}
                        onChange={(e) =>
                          setLines((prev) =>
                            prev.map((item, i) =>
                              i === index
                                ? {
                                    ...item,
                                    mdTotal: sanitizeDecimalInput(e.target.value),
                                  }
                                : item,
                            ),
                          )
                        }
                        className={inputClass}
                      />
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </fieldset>

        <div>
          <label htmlFor="extend-notes" className={labelClass}>
            Notatki
          </label>
          <textarea
            id="extend-notes"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <p className={labelClass}>PDF zamówienia od klienta</p>
          <FileDropZone
            inputId="extend-po"
            file={file}
            onPick={(picked) => {
              setFile(picked);
              setFileError(null);
              setExtractError(null);
              setCheckData(false);
              setCheckReasons([]);
            }}
            onError={setFileError}
            error={fileError ?? extractError}
            accept={ACCEPT}
            maxBytes={MAX_UPLOAD_BYTES}
            label="Zamień plik PDF"
            hint=".pdf · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={handleExtract}
              disabled={!file || extracting}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-orange-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              <FileSearch className="h-4 w-4" aria-hidden />
              {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
            </button>
            {file ? (
              <button
                type="button"
                aria-label="Usuń wybrany plik PDF zamówienia"
                title="Usuń wybrany plik"
                onClick={() => {
                  if (!window.confirm("Czy na pewno chcesz usunąć plik PDF zamówienia?")) return;
                  setFile(null);
                  setFileError(null);
                  setExtractError(null);
                  setCheckData(false);
                  setCheckReasons([]);
                }}
                className="rounded-md border border-destructive/40 p-2 text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <ExtractionConflictDialog
        open={conflicts.length > 0}
        conflicts={conflicts}
        onConfirm={() => {
          pendingApply?.();
          setConflicts([]);
          setPendingApply(null);
        }}
        onCancel={() => {
          setConflicts([]);
          setPendingApply(null);
        }}
      />
    </AppModal>
  );
}
