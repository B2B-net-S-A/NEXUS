"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileSearch,
  Loader2,
  Trash2,
} from "lucide-react";

import { AppModal, FileDropZone } from "@/components/ds";
import { OrderTypeSwitch } from "@/components/orders/OrderTypeSwitch";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OrderType } from "@/lib/api/dlPortal";
import {
  downloadAuthenticatedFile,
  openAuthenticatedFile,
} from "@/lib/authenticated-files";
import type { OrderGroupInput, OrderGroupRead } from "@/lib/api/orderGroups";
import { usesSharedMdPool } from "@/lib/client-order-list";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
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
const ACCEPT = ".pdf";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ustawione = edycja; puste = nowe zamówienie. */
  group: OrderGroupRead | null;
  clientId: number;
  orderType: Exclude<OrderType, "periodic">;
  onOrderTypeChange: (orderType: OrderType) => void;
  allowedOrderTypes?: readonly OrderType[];
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderGroupInput, file: File | null) => void;
  onDeleteFile: () => Promise<void>;
}

export function OrderGroupFormModal({
  open,
  onOpenChange,
  group,
  clientId,
  orderType,
  onOrderTypeChange,
  allowedOrderTypes,
  submitting,
  error,
  onSubmit,
  onDeleteFile,
}: Props) {
  const editing = Boolean(group);
  const [orderNumber, setOrderNumber] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [budgetAmount, setBudgetAmount] = useState("");
  const [mdBudgetTotal, setMdBudgetTotal] = useState("");
  const [consumptionMonth, setConsumptionMonth] = useState("");
  const [consumptionValue, setConsumptionValue] = useState("");
  const [sharedChoice, setSharedChoice] = useState(false);
  const [draftStatus, setDraftStatus] = useState<"draft" | "active">("draft");
  const modeLocked = Boolean(
    group &&
    (group.md_budget_mode_locked !== false || group.status !== "draft"),
  );
  const isCostBased = orderType === "cost";
  const isMdOrder = orderType === "md";
  const sharedMd = isMdOrder && sharedChoice;

  const [file, setFile] = useState<File | null>(null);
  const [hasExistingFile, setHasExistingFile] = useState(false);
  const [busyExistingFile, setBusyExistingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  // Numer ID konsultanta z dokumentu (polityka BNP) — PDF-y tego klienta
  // nie niosą imienia ani nazwiska. Informacyjnie, do potwierdzenia
  // przez operatora; Nexus nie przechowuje identyfikatorów klienta.
  const [consultantRef, setConsultantRef] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);

  useEffect(() => {
    if (!open) return;
    setOrderNumber(group?.order_number ?? "");
    setStartDate(group?.start_date ?? "");
    setEndDate(group?.end_date ?? "");
    setNotes(group?.notes ?? "");
    setBudgetAmount(numberToField(group?.budget_amount));
    setMdBudgetTotal(numberToField(group?.md_budget_total));
    setSharedChoice(group ? usesSharedMdPool(group) : false);
    setConsumptionMonth("");
    setConsumptionValue("");
    setDraftStatus(group?.status === "draft" || !group ? "draft" : "active");
    setFile(null);
    setHasExistingFile(Boolean(group?.has_file));
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
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
        if (sharedMd && data.md_total != null) {
          setMdBudgetTotal(String(data.md_total));
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
        ...(sharedMd
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
      setConsultantRef(data.consultant_ref ?? null);
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
        extractionErrorMessage(
          err,
          "Nie udało się odczytać danych z dokumentu.",
        ),
      );
    } finally {
      setExtracting(false);
    }
  }

  const budgetMissing =
    (isCostBased && (parseDecimalInput(budgetAmount) ?? 0) <= 0) ||
    (sharedMd && (parseDecimalInput(mdBudgetTotal) ?? 0) <= 0);
  const canSubmit =
    !submitting &&
    orderNumber.trim() !== "" &&
    startDate !== "" &&
    !budgetMissing &&
    ((!consumptionMonth && !consumptionValue) ||
      (Boolean(consumptionMonth) &&
        (parseDecimalInput(consumptionValue) ?? -1) >= 0));

  const fileEndpoint = group
    ? `/api/clients/${clientId}/order-groups/${group.id}/file`
    : null;

  async function withExistingFileBusy(
    action: () => Promise<void>,
    message: string,
  ) {
    setBusyExistingFile(true);
    setFileError(null);
    try {
      await action();
    } catch {
      setFileError(message);
    } finally {
      setBusyExistingFile(false);
    }
  }

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? "Uzupełnij zamówienie" : "Nowe zamówienie"}
      description={
        editing
          ? "Numer, okres i budżet. Linie konsultantów edytujesz osobno."
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
              onSubmit(
                {
                  order_number: orderNumber.trim(),
                  start_date: startDate,
                  end_date: endDate || null,
                  notes: notes.trim() || null,
                  ...(sharedMd && consumptionMonth && consumptionValue
                    ? {
                        md_consumption_month: consumptionMonth,
                        md_consumption_value:
                          parseDecimalInput(consumptionValue)!,
                      }
                    : {}),
                  ...(isMdOrder && !modeLocked
                    ? {
                        md_budget_mode: sharedMd ? "shared" : "per_person",
                        status: draftStatus,
                      }
                    : {}),
                  // Typ rozliczenia jest wybierany PRZY ZAKŁADANIU i nie zmienia
                  // się później. Zwykłe MD ma budżet przy liniach, a świadome
                  // warianty CP/Lotte wysyłają jedną pulę MD na grupie.
                  ...(editing
                    ? {}
                    : {
                        order_type: orderType,
                        ...(sharedMd
                          ? {
                              is_cost_based: false,
                              is_md_budget_based: true,
                            }
                          : {}),
                      }),
                  ...(isCostBased
                    ? { budget_amount: parseDecimalInput(budgetAmount) }
                    : {}),
                  ...(sharedMd
                    ? { md_budget_total: parseDecimalInput(mdBudgetTotal) }
                    : {}),
                },
                file,
              )
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

        <OrderTypeSwitch
          value={orderType}
          onChange={onOrderTypeChange}
          allowedTypes={allowedOrderTypes}
          disabled={editing}
        />

        {isMdOrder ? (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={sharedMd}
                disabled={modeLocked}
                onChange={(event) => setSharedChoice(event.target.checked)}
              />
              Budżet MD na całe zamówienie
            </label>
            {modeLocked ? (
              <p className="text-xs text-muted-foreground">
                Tryb budżetu jest zablokowany po aktywacji lub pierwszym wpisie
                zużycia MD.
              </p>
            ) : (
              <>
                <label className={labelClass}>
                  Status zamówienia
                  <select
                    aria-label="Status zamówienia"
                    className={inputClass}
                    value={draftStatus}
                    onChange={(event) =>
                      setDraftStatus(event.target.value as "draft" | "active")
                    }
                  >
                    <option value="draft">Draft — do uzupełnienia</option>
                    {editing ? (
                      <option value="active">
                        Active — aktywuj zamówienie
                      </option>
                    ) : null}
                  </select>
                </label>
                {editing && sharedMd !== usesSharedMdPool(group!) ? (
                  <p className="text-xs text-muted-foreground">
                    Zmiana trybu usuwa podział budżetu. Po powrocie do trybu per
                    osoba uzupełnij budżety konsultantów przed aktywacją.
                  </p>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {consultantRef !== null ? (
          <p
            role="status"
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground"
          >
            Numer ID konsultanta z dokumentu:{" "}
            <span className="font-semibold">{consultantRef}</span>
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

        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="mt-1 text-xs text-muted-foreground">
            {sharedMd
              ? "Wspólna pula MD dla całego zamówienia, bez dzielenia budżetu na konsultantów."
              : isMdOrder
                ? "Budżet MD ustawiasz osobno przy każdym konsultancie po utworzeniu zamówienia."
                : editing
                  ? "Typu rozliczenia nie zmienia się po założeniu zamówienia."
                  : "Rozliczane ustaloną kwotą, z której schodzą faktury — zamiast liczby MD per konsultant."}
          </p>

          {isCostBased ? (
            <div className="mt-3">
              <label htmlFor="group-budget" className={labelClass}>
                Budżet całkowity (PLN) *
              </label>
              <input
                id="group-budget"
                inputMode="decimal"
                value={budgetAmount}
                onChange={(e) =>
                  setBudgetAmount(sanitizeDecimalInput(e.target.value))
                }
                className={inputClass}
                placeholder="50000"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Wartość wyjściowa na cały czas trwania zamówienia. Zużycie i
                pozostałość przelicza import faktur.
              </p>
              <label htmlFor="group-invoiced" className={`${labelClass} mt-3`}>
                Zafakturowano
              </label>
              <input
                id="group-invoiced"
                value={numberToField(group?.budget_used ?? 0)}
                readOnly
                className={`${inputClass} bg-muted text-muted-foreground`}
              />
            </div>
          ) : null}

          {sharedMd ? (
            <div className="mt-3">
              <label htmlFor="group-md-budget" className={labelClass}>
                Budżet w MD *
              </label>
              <input
                id="group-md-budget"
                inputMode="decimal"
                value={mdBudgetTotal}
                onChange={(e) =>
                  setMdBudgetTotal(sanitizeDecimalInput(e.target.value))
                }
                className={inputClass}
                placeholder="100"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Zużycie wszystkich konsultantów pomniejsza tę jedną pulę MD.
              </p>
              {group && ["active", "exhausted"].includes(group.status) ? (
                <div className="my-3 space-y-2">
                  <label className={labelClass}>
                    Miesiąc rozliczenia
                    <input
                      aria-label="Miesiąc rozliczenia"
                      type="month"
                      value={consumptionMonth}
                      onChange={(event) =>
                        setConsumptionMonth(event.target.value)
                      }
                      className={inputClass}
                    />
                  </label>
                  <label className={labelClass}>
                    Łączne zużycie MD w miesiącu
                    <input
                      aria-label="Łączne zużycie MD w miesiącu"
                      inputMode="decimal"
                      value={consumptionValue}
                      onChange={(event) =>
                        setConsumptionValue(
                          sanitizeDecimalInput(event.target.value),
                        )
                      }
                      className={inputClass}
                    />
                  </label>
                  <p className="text-xs text-muted-foreground">
                    Wpisz sumę MD wszystkich konsultantów za wybrany miesiąc.
                    Zapis zastępuje dotychczasowe rozliczenie tego miesiąca,
                    także z importu.
                  </p>
                </div>
              ) : null}
              <label htmlFor="group-md-used" className={`${labelClass} mt-3`}>
                Wykorzystano MD
              </label>
              <input
                id="group-md-used"
                value={numberToField(group?.md_budget_used ?? 0)}
                readOnly
                className={`${inputClass} bg-muted text-muted-foreground`}
              />
            </div>
          ) : null}
        </div>

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
          {group && hasExistingFile && fileEndpoint ? (
            <div className="mb-2 flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">
                {group.filename ?? `${group.order_number}.pdf`}
              </span>
              {busyExistingFile ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Przetwarzanie pliku" />
              ) : (
                <>
                  <button
                    type="button"
                    aria-label="Otwórz plik PDF zamówienia"
                    title="Otwórz"
                    onClick={() =>
                      withExistingFileBusy(
                        () =>
                          openAuthenticatedFile(
                            fileEndpoint,
                            "application/pdf",
                            `${group.order_number}.pdf`,
                          ),
                        "Nie udało się otworzyć pliku PDF.",
                      )
                    }
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <ExternalLink className="h-4 w-4" aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label="Pobierz plik PDF zamówienia"
                    title="Pobierz"
                    onClick={() =>
                      withExistingFileBusy(
                        () =>
                          downloadAuthenticatedFile(
                            fileEndpoint,
                            `${group.order_number}.pdf`,
                          ),
                        "Nie udało się pobrać pliku PDF.",
                      )
                    }
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <Download className="h-4 w-4" aria-hidden />
                  </button>
                  <button
                    type="button"
                    aria-label="Usuń plik PDF zamówienia"
                    title="Usuń"
                    onClick={() => {
                      if (
                        !window.confirm(
                          "Czy na pewno chcesz usunąć plik PDF zamówienia?",
                        )
                      )
                        return;
                      void withExistingFileBusy(async () => {
                        await onDeleteFile();
                        setHasExistingFile(false);
                        setFile(null);
                        setCheckData(false);
                        setCheckReasons([]);
                      }, "Nie udało się usunąć pliku PDF.");
                    }}
                    className="rounded p-1 text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                </>
              )}
            </div>
          ) : null}
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
              setConsultantRef(null);
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
                  if (
                    !window.confirm(
                      "Czy na pewno chcesz usunąć plik PDF zamówienia?",
                    )
                  )
                    return;
                  setFile(null);
                  setFileError(null);
                  setExtractError(null);
                  setCheckData(false);
                  setCheckReasons([]);
                  setConsultantRef(null);
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
