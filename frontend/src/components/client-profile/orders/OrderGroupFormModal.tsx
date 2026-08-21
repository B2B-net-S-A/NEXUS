"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, FileSearch } from "lucide-react";

import { AppModal, FileDropZone } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OrderGroupInput, OrderGroupRead } from "@/lib/api/orderGroups";
import {
  extractionErrorMessage,
  findConflicts,
  numberToField,
  type ExtractionConflict,
} from "@/lib/order-extraction";

import { ExtractionConflictDialog } from "./ExtractionConflictDialog";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

/** Ten sam limit co na endpointach zamówień (25 MB) i te same rozszerzenia. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.doc";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ustawione = edycja; puste = nowe zamówienie. */
  group: OrderGroupRead | null;
  clientId: number;
  /** Czy u tego klienta wolno zakładać zamówienia kosztowe (flaga z serwera). */
  costOrdersEnabled: boolean;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderGroupInput) => void;
}

export function OrderGroupFormModal({
  open,
  onOpenChange,
  group,
  clientId,
  costOrdersEnabled,
  submitting,
  error,
  onSubmit,
}: Props) {
  const editing = Boolean(group);
  const [orderNumber, setOrderNumber] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [isCostBased, setIsCostBased] = useState(false);
  const [budgetAmount, setBudgetAmount] = useState("");

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
    setOrderNumber(group?.order_number ?? "");
    setStartDate(group?.start_date ?? "");
    setEndDate(group?.end_date ?? "");
    setNotes(group?.notes ?? "");
    setIsCostBased(group?.is_cost_based ?? false);
    setBudgetAmount(numberToField(group?.budget_amount));
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
        if (isCostBased && data.total_value != null) {
          setBudgetAmount(String(data.total_value));
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
        ...(isCostBased
          ? [
              {
                key: "total_value" as const,
                label: "Kwota zamówienia",
                current: budgetAmount,
                incoming: numberToField(data.total_value) || null,
              },
            ]
          : []),
      ]);
      setCheckData(Boolean(data.uncertain));
      setCheckReasons(data.uncertain_reasons ?? []);
      if (found.length > 0) {
        // Nic jeszcze nie zmieniamy — dopiero potwierdzenie użytkownika.
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

  const budgetMissing = isCostBased && budgetAmount.trim() === "";
  const canSubmit =
    !submitting && orderNumber.trim() !== "" && startDate !== "" && !budgetMissing;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? "Edytuj zamówienie" : "Nowe zamówienie"}
      description={
        editing
          ? "Numer i okres obowiązywania. Linie konsultantów edytujesz osobno."
          : "Po zapisaniu dodasz do zamówienia konsultantów."
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
                // Typ rozliczenia jest wybierany PRZY ZAKŁADANIU i nie zmienia
                // się później: zamówienie z rozliczonymi fakturami, które
                // nagle staje się MD-owe, zostawia kwoty bez puli, z której
                // zeszły. Przy edycji wysyłamy więc tylko kwotę.
                ...(editing
                  ? {}
                  : { is_cost_based: isCostBased }),
                ...(isCostBased
                  ? { budget_amount: Number(budgetAmount.replace(",", ".")) }
                  : {}),
              })
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : editing ? "Zapisz" : "Utwórz zamówienie"}
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
          <label htmlFor="group-number" className={labelClass}>
            Numer zamówienia *
          </label>
          <input
            id="group-number"
            value={orderNumber}
            onChange={(e) => setOrderNumber(e.target.value)}
            className={inputClass}
            placeholder="445"
          />
        </div>

        {costOrdersEnabled ? (
          <div className="rounded-md border border-border bg-muted/30 p-3">
            <label className="flex items-center gap-2 text-sm font-medium text-foreground">
              <input
                type="checkbox"
                checked={isCostBased}
                disabled={editing}
                onChange={(e) => {
                  setIsCostBased(e.target.checked);
                  if (!e.target.checked) setBudgetAmount("");
                }}
                className="h-4 w-4 rounded border-border"
              />
              Zamówienie kosztowe
            </label>
            <p className="mt-1 text-xs text-muted-foreground">
              {editing
                ? "Typu rozliczenia nie zmienia się po założeniu zamówienia."
                : "Rozliczane ustaloną kwotą, z której schodzą faktury — zamiast liczby MD per konsultant."}
            </p>

            {isCostBased ? (
              <div className="mt-3">
                <label htmlFor="group-budget" className={labelClass}>
                  Kwota zamówienia (zł) *
                </label>
                <input
                  id="group-budget"
                  inputMode="decimal"
                  value={budgetAmount}
                  onChange={(e) => setBudgetAmount(e.target.value)}
                  className={inputClass}
                  placeholder="50000"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Wartość wyjściowa na cały czas trwania zamówienia. Zużycie
                  i pozostałość przelicza import faktur.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="group-start" className={labelClass}>
              Obowiązuje od *
            </label>
            <input
              id="group-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="group-end" className={labelClass}>
              Obowiązuje do (puste = bezterminowo)
            </label>
            <input
              id="group-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        <div>
          <label htmlFor="group-notes" className={labelClass}>
            Notatki
          </label>
          <textarea
            id="group-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={inputClass}
          />
        </div>

        <div>
          <p className={labelClass}>PDF zamówienia od klienta</p>
          <FileDropZone
            inputId="group-po"
            file={file}
            onPick={(picked) => {
              // Dodanie pliku NIE zmienia żadnego pola — odczyt jest osobną,
              // świadomą akcją. Czyścimy tylko baner z poprzedniego odczytu.
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
            label="Dodaj PDF do zamówienia"
            hint=".pdf / .docx · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
          />
          <button
            type="button"
            onClick={handleExtract}
            disabled={!file || extracting}
            className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-orange-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <FileSearch className="h-4 w-4" aria-hidden />
            {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
          </button>
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
