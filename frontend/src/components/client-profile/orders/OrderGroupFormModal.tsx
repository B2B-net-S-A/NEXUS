"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Download,
  ExternalLink,
  FileSearch,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";

import { AppModal, FileDropZone } from "@/components/ds";
import {
  ExtractedConsultants,
  type ExtractedConsultantRows,
} from "@/components/orders/ExtractedConsultants";
import { OrderTypeSwitch } from "@/components/orders/OrderTypeSwitch";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OrderType } from "@/lib/api/dlPortal";
import {
  downloadAuthenticatedFile,
  openAuthenticatedFile,
} from "@/lib/authenticated-files";
import {
  orderGroupsApi,
  type OrderGroupInput,
  type OrderGroupRead,
} from "@/lib/api/orderGroups";
import { usesSharedMdPool } from "@/lib/client-order-list";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import {
  extractedEndDate,
  extractionErrorMessage,
  findConflicts,
  numberToField,
  type ExtractionConflict,
} from "@/lib/order-extraction";
import {
  draftsFromPlan,
  duplicatePersonKeys,
  emptyDraft,
  lineIssues,
  lineValuePln,
  toLineInput,
  usesLineMd,
  type OrderLineDraft,
} from "@/lib/order-plan";

import { ExtractionConflictDialog } from "./ExtractionConflictDialog";
import { OrderPlanLineCard } from "./OrderPlanLineCard";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

/** Ten sam limit co na endpointach zamówień (25 MB) i te same rozszerzenia. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ACCEPT = ".pdf";

const plnFormatter = new Intl.NumberFormat("pl-PL", {
  style: "currency",
  currency: "PLN",
  maximumFractionDigits: 2,
});

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ustawione = edycja; puste = nowe zamówienie. */
  group: OrderGroupRead | null;
  clientId: number;
  orderType: Exclude<OrderType, "periodic">;
  /** Zmiana typu przekazuje wgrany plik, żeby przejście na „Okresowe" (inny
   *  formularz) nie kazało wgrywać PDF-a drugi raz. */
  onOrderTypeChange: (orderType: OrderType, file: File | null) => void;
  allowedOrderTypes?: readonly OrderType[];
  /** Plik przeniesiony z formularza, z którego przełączono typ. */
  initialFile?: File | null;
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
  initialFile = null,
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
  // Tabela osób z dokumentu (BIK) w trybie EDYCJI — informacyjnie: linie
  // konsultantów istniejącego zamówienia edytujesz osobno.
  const [extractedRows, setExtractedRows] = useState<ExtractedConsultantRows>([]);
  const [extractedOpenEnded, setExtractedOpenEnded] = useState(false);
  const [clientPolicy, setClientPolicy] = useState<string | null | undefined>(
    undefined,
  );
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);
  // Karty konsultantów — tylko w nowym zamówieniu. Edycja istniejącego
  // zamówienia zostawia linie w ich własnych formularzach.
  const [lines, setLines] = useState<OrderLineDraft[]>([]);
  const [planned, setPlanned] = useState(false);

  // Odpowiedź odczytu porównujemy ze stanem z chwili ODPOWIEDZI, nie
  // kliknięcia — w trakcie kilkusekundowego odczytu użytkownik może coś
  // wpisać, a taka zmiana musi przejść przez pytanie o rozbieżność.
  const formRef = useRef({ orderNumber, startDate, endDate, budgetAmount, mdBudgetTotal });
  formRef.current = { orderNumber, startDate, endDate, budgetAmount, mdBudgetTotal };

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
    // Nowe zamówienie powstaje od razu z konsultantami, więc domyślnie jest
    // aktywne. Szkic zostaje świadomym wyborem („do uzupełnienia").
    setDraftStatus(group ? (group.status === "draft" ? "draft" : "active") : "active");
    setFile(group ? null : initialFile);
    setHasExistingFile(Boolean(group?.has_file));
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
    setExtractedRows([]);
    setExtractedOpenEnded(false);
    setClientPolicy(undefined);
    setConflicts([]);
    setPendingApply(null);
    setLines([]);
    setPlanned(false);
    // `initialFile` celowo poza zależnościami: plik przejmujemy raz, przy
    // otwarciu — późniejsza zmiana w rodzicu nie może nadpisać wyboru tutaj.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, group]);

  const planContext = {
    orderType,
    sharedMd,
    groupStart: startDate,
    groupEnd: endDate || null,
  };
  const lineMd = usesLineMd(planContext);
  const duplicated = useMemo(() => duplicatePersonKeys(lines), [lines]);
  const issuesByKey = new Map(
    lines.map((line) => [line.key, lineIssues(line, planContext)]),
  );
  const readyCount = lines.filter(
    (line) => (issuesByKey.get(line.key) ?? []).length === 0,
  ).length;
  const orderValue = isCostBased
    ? parseDecimalInput(budgetAmount)
    : lineMd && lines.length > 0
      ? lines.reduce<number | null>((sum, line) => {
          const value = lineValuePln(line);
          return sum === null || value === null ? null : sum + value;
        }, 0)
      : null;

  /** Tryb edycji — odczyt pól nagłówka zamówienia (bez konsultantów). */
  async function handleExtractHeader() {
    if (!file || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(clientId, file);
      const extractedEnd = extractedEndDate(data);
      const apply = () => {
        if (data.title) setOrderNumber(data.title);
        if (data.start_date) setStartDate(data.start_date.slice(0, 10));
        if (extractedEnd) setEndDate(extractedEnd.value);
        if (isCostBased && data.total_value != null) {
          setBudgetAmount(String(data.total_value));
        }
        if (sharedMd && data.md_total != null) {
          setMdBudgetTotal(String(data.md_total));
        }
      };
      const found = findConflicts([
        { key: "title", label: "Numer zamówienia", current: orderNumber, incoming: data.title ?? null },
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
          incoming: extractedEnd?.display ?? null,
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
      setExtractedRows(data.consultant_rows ?? []);
      setExtractedOpenEnded(Boolean(data.open_ended));
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

  /** Nowe zamówienie — jeden odczyt: nagłówek + karta dla każdej osoby. */
  async function handleExtractPlan() {
    if (!file || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await orderGroupsApi.extractPlan(clientId, file);
      const current = formRef.current;
      const drafts = draftsFromPlan(data);
      const sumMd = drafts.reduce<number | null>((sum, line) => {
        const md = parseDecimalInput(line.md);
        return sum === null || md === null ? null : sum + md;
      }, 0);
      const poolMd = data.md_total ?? (drafts.length > 0 ? sumMd : null);
      // Karty konsultantów wchodzą zawsze — pytanie o rozbieżność dotyczy
      // wyłącznie pól nagłówka wpisanych wcześniej ręcznie. Karty dodane
      // ręcznie zostają; poprzedni odczyt PDF-a jest zastępowany.
      setLines((existing) => [
        ...drafts,
        ...existing.filter((line) => line.ordinal === null),
      ]);
      setPlanned(true);
      // Kwota i pula MD wypełniają się niezależnie od wybranego typu —
      // zmiana typu po odczycie nie gubi tego, co dokument podał. Kwota
      // w obcej walucie NIE trafia do „Budżet całkowity (PLN)".
      const documentCurrency = (data.currency ?? "PLN").toUpperCase();
      if (
        data.total_value != null &&
        documentCurrency === "PLN" &&
        !current.budgetAmount.trim()
      ) {
        setBudgetAmount(String(data.total_value));
      }
      if (poolMd != null && !current.mdBudgetTotal.trim()) {
        setMdBudgetTotal(String(poolMd));
      }
      // BIK: brak daty końca to poprawny odczyt („bezterminowo — do
      // wyczerpania MD"), więc pole „do" jest czyszczone jawnie.
      const extractedEnd = extractedEndDate(data);
      const apply = () => {
        if (data.order_number) setOrderNumber(data.order_number);
        if (data.start_date) setStartDate(data.start_date.slice(0, 10));
        if (extractedEnd) setEndDate(extractedEnd.value);
      };
      const found = findConflicts([
        {
          key: "title",
          label: "Numer zamówienia",
          current: current.orderNumber,
          incoming: data.order_number ?? null,
        },
        {
          key: "start_date",
          label: "Obowiązuje od",
          current: current.startDate,
          incoming: data.start_date ? data.start_date.slice(0, 10) : null,
        },
        {
          key: "end_date",
          label: "Obowiązuje do",
          current: current.endDate,
          incoming: extractedEnd?.display ?? null,
        },
      ]);
      setConsultantRef(data.consultant_ref ?? null);
      setClientPolicy(data.client_policy);
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

  const budgetMissing =
    (isCostBased && (parseDecimalInput(budgetAmount) ?? 0) <= 0) ||
    (sharedMd && (parseDecimalInput(mdBudgetTotal) ?? 0) <= 0);
  const linesBlocked =
    !editing &&
    (readyCount < lines.length ||
      (isMdOrder && !sharedMd && draftStatus === "active" && lines.length === 0));
  const canSubmit =
    !submitting &&
    orderNumber.trim() !== "" &&
    startDate !== "" &&
    !budgetMissing &&
    !linesBlocked &&
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

  function clearPickedFile() {
    setFile(null);
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
  }

  function submit() {
    if (!canSubmit) return;
    onSubmit(
      {
        order_number: orderNumber.trim(),
        start_date: startDate,
        end_date: endDate || null,
        notes: notes.trim() || null,
        ...(sharedMd && consumptionMonth && consumptionValue
          ? {
              md_consumption_month: consumptionMonth,
              md_consumption_value: parseDecimalInput(consumptionValue)!,
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
                ? { is_cost_based: false, is_md_budget_based: true }
                : {}),
              // Wszyscy konsultanci w TYM SAMYM zapisie — bez pośredniego,
              // pustego zamówienia i bez osobnego „Dodaj konsultanta".
              ...(lines.length > 0
                ? { lines: lines.map((line) => toLineInput(line, planContext)) }
                : {}),
            }),
        ...(isCostBased
          ? { budget_amount: parseDecimalInput(budgetAmount) }
          : {}),
        ...(sharedMd ? { md_budget_total: parseDecimalInput(mdBudgetTotal) } : {}),
      },
      file,
    );
  }

  const pdfSection = (
    <div>
      <p className={labelClass}>PDF zamówienia od klienta</p>
      {group && hasExistingFile && fileEndpoint ? (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1 truncate">
            {group.filename ?? `${group.order_number}.pdf`}
          </span>
          {busyExistingFile ? (
            <Loader2
              className="h-4 w-4 animate-spin text-muted-foreground"
              aria-label="Przetwarzanie pliku"
            />
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
                  if (!window.confirm("Czy na pewno chcesz usunąć plik PDF zamówienia?"))
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
          // świadomą akcją. Czyścimy baner z poprzedniego odczytu i karty
          // osób z POPRZEDNIEGO dokumentu: zapisane z nowym plikiem opisywałyby
          // zamówienie, którego ten plik nie dotyczy. Karty dodane ręcznie zostają.
          setFile(picked);
          setExtractedRows([]);
          setLines((existing) => existing.filter((line) => line.ordinal === null));
          setPlanned(false);
          setClientPolicy(undefined);
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
        label={editing ? "Zamień plik PDF" : "Wgraj PDF zamówienia"}
        hint={
          editing
            ? ".pdf · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
            : ".pdf · po zapisaniu trafi też do Dokumentów kontraktów · maks. 25 MB"
        }
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={editing ? handleExtractHeader : handleExtractPlan}
          disabled={!file || extracting}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {extracting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <FileSearch className="h-4 w-4" aria-hidden />
          )}
          {extracting
            ? "Odczytywanie…"
            : editing
              ? "Zczytaj dane z dokumentu"
              : "Zczytaj i uzupełnij całe zamówienie"}
        </button>
        {file ? (
          <button
            type="button"
            aria-label="Usuń wybrany plik PDF zamówienia"
            title="Usuń wybrany plik"
            onClick={() => {
              if (!window.confirm("Czy na pewno chcesz usunąć plik PDF zamówienia?"))
                return;
              clearPickedFile();
            }}
            className="rounded-md border border-destructive/40 p-2 text-destructive hover:bg-destructive/10"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>
      {!editing ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Odczytuje numer, datę i wszystkich konsultantów z dokumentu, dopasowuje
          ich do kontraktów u klienta i uzupełnia stawki oraz MD w tym samym
          oknie.
        </p>
      ) : null}
    </div>
  );

  const linesSection = !editing ? (
    <section aria-label="Konsultanci na zamówieniu" className="space-y-3">
      {planned || lines.length > 0 ? (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" aria-hidden />
          {lines.length > 0
            ? `${lines.length} ${lines.length === 1 ? "konsultant" : "konsultantów"} na zamówieniu`
            : "W dokumencie nie rozpoznano konsultantów — dodaj ich ręcznie"}
          <span className="h-px flex-1 bg-border" aria-hidden />
        </div>
      ) : null}
      {lines.map((line) => (
        <OrderPlanLineCard
          key={line.key}
          clientId={clientId}
          draft={line}
          showMd={lineMd}
          duplicated={duplicated.has(line.key)}
          issues={issuesByKey.get(line.key) ?? []}
          onChange={(next) =>
            setLines((current) =>
              current.map((item) => (item.key === line.key ? next : item)),
            )
          }
          onRemove={() =>
            setLines((current) => current.filter((item) => item.key !== line.key))
          }
        />
      ))}
      <button
        type="button"
        onClick={() => setLines((current) => [...current, emptyDraft()])}
        className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
      >
        <Plus className="h-4 w-4" aria-hidden /> Dodaj konsultanta
      </button>
      {lines.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
          <span className="text-muted-foreground">
            {readyCount} z {lines.length} pozycji gotowe do zapisania
          </span>
          {orderValue !== null ? (
            <span className="font-semibold text-foreground">
              {plnFormatter.format(orderValue)} łącznej wartości zamówienia
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  ) : null;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size={editing ? "md" : "lg"}
      title={editing ? "Uzupełnij zamówienie" : "Nowe zamówienie"}
      description={
        editing
          ? "Numer, okres i budżet. Linie konsultantów edytujesz osobno."
          : "Wgraj PDF, a Nexus uzupełni całe zamówienie — z konsultantami — w tym oknie."
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
            onClick={submit}
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
          onChange={(next) => onOrderTypeChange(next, file)}
          allowedTypes={allowedOrderTypes}
          disabled={editing}
        />
        {!editing ? (
          <p className="-mt-2 text-xs text-muted-foreground">
            Podpowiadamy typ najczęstszy u tego klienta. Każdy typ jest dostępny —
            możesz go zmienić w każdej chwili, także po odczycie PDF-a.
          </p>
        ) : null}

        {!editing ? pdfSection : null}

        {clientPolicy !== undefined ? (
          <p className="text-xs text-muted-foreground">
            {clientPolicy
              ? `Zastosowano reguły klienta: ${clientPolicy}.`
              : "Ten klient nie ma jeszcze własnych reguł odczytu — sprawdź pola."}
          </p>
        ) : null}

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
                    {!editing ? (
                      <option value="active">Aktywne — od razu po zapisaniu</option>
                    ) : null}
                    <option value="draft">Draft — do uzupełnienia</option>
                    {editing ? (
                      <option value="active">Active — aktywuj zamówienie</option>
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

        {editing ? (
          <ExtractedConsultants rows={extractedRows} openEnded={extractedOpenEnded} />
        ) : null}

        {checkData ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
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

        {isCostBased || sharedMd || editing ? (
          <div className="rounded-md border border-border bg-muted/30 p-3">
            <p className="mt-1 text-xs text-muted-foreground">
              {sharedMd
                ? "Wspólna pula MD dla całego zamówienia, bez dzielenia budżetu na konsultantów."
                : isMdOrder
                  ? "Budżet MD ustawiasz przy każdym konsultancie."
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
                  onChange={(e) => setBudgetAmount(sanitizeDecimalInput(e.target.value))}
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
                  onChange={(e) => setMdBudgetTotal(sanitizeDecimalInput(e.target.value))}
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
                        onChange={(event) => setConsumptionMonth(event.target.value)}
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
                          setConsumptionValue(sanitizeDecimalInput(event.target.value))
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
        ) : null}

        {linesSection}

        <div>
          <label htmlFor="group-notes" className={labelClass}>
            Notatki
          </label>
          <textarea
            id="group-notes"
            rows={editing ? 3 : 2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={inputClass}
          />
        </div>

        {editing ? pdfSection : null}
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
