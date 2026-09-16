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
import { OrderTypeSwitch } from "@/components/orders/OrderTypeSwitch";
import type { OrderType } from "@/lib/api/dlPortal";
import {
  downloadAuthenticatedFile,
  openAuthenticatedFile,
} from "@/lib/authenticated-files";
import {
  orderGroupsApi,
  type OrderGroupExtraction,
  type OrderGroupInput,
  type OrderGroupRead,
} from "@/lib/api/orderGroups";
import { useExecutiveContractOptions } from "@/lib/api/executiveContracts";
import { usesSharedMdPool } from "@/lib/client-order-list";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import {
  extractedEndDate,
  extractionErrorMessage,
  typedByUser,
  type DocumentFieldValues,
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
  splitPlanForGroup,
  toLineInput,
  usesLineMd,
  type OrderLineDraft,
  type PersonAlreadyOnOrder,
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
  /** Zmiana typu przekazuje wgrany plik i wpisany numer, żeby przejście na
   *  „Okresowe" (inny formularz) nie kazało wgrywać PDF-a ani wpisywać numeru
   *  drugi raz (UAT B03). */
  onOrderTypeChange: (
    orderType: OrderType,
    file: File | null,
    orderNumber: string,
  ) => void;
  allowedOrderTypes?: readonly OrderType[];
  /** Plik przeniesiony z formularza, z którego przełączono typ. */
  initialFile?: File | null;
  /** Numer zamówienia przeniesiony z formularza, z którego przełączono typ. */
  initialOrderNumber?: string;
  /** PDF z kolejki zamówień z maila („Rozstrzygnij w oknie zamówienia"):
   *  trafia do okna w OBU trybach i jest od razu odczytywany — Delivery Lead
   *  widzi karty osób, w tym tę nieaktywną/nieznalezioną, bez ręcznego
   *  pobierania i wgrywania pliku. */
  autoReadFile?: File | null;
  /** Informacja, skąd pochodzi PDF (dokument z maila). */
  sourceNotice?: string | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderGroupInput, file: File | null) => void;
  onDeleteFile: () => Promise<void>;
}

/** Czym wiersz PDF-a różni się od linii na zamówieniu (MD, stawka) — opis albo `null`. */
function documentDiffers(
  draft: OrderLineDraft,
  line: PersonAlreadyOnOrder["line"],
): string | null {
  const parts: string[] = [];
  const md = parseDecimalInput(draft.md);
  if (md !== null && line.md_total != null && Math.abs(md - line.md_total) > 1e-6) {
    parts.push("MD");
  }
  const rate = parseDecimalInput(draft.rateRevenue);
  if (
    rate !== null &&
    draft.revenueUnit === "md" &&
    line.rate_revenue != null &&
    Math.abs(rate - line.rate_revenue) > 0.005
  ) {
    parts.push("stawkę");
  }
  return parts.length > 0 ? parts.join(" i ") : null;
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
  initialOrderNumber = "",
  autoReadFile = null,
  sourceNotice = null,
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
  // Centrum e-Zdrowia: zamówienie wisi pod KONKRETNĄ umową wykonawczą, nie
  // pod częścią. Bramka po `client_id` — u innych klientów hook jest wyłączony
  // (backend odpowiada tam 422), a select nie renderuje się wcale.
  const ezdrowie = isEzdrowieClient(clientId);
  const [executiveContractId, setExecutiveContractId] = useState("");
  const executiveContracts = useExecutiveContractOptions(ezdrowie ? clientId : null);
  const executiveContractMissing = ezdrowie && !editing && executiveContractId === "";

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
  // „Uzupełnij zamówienie": osoby z PDF-a, które JUŻ są na zamówieniu — bez
  // drugiej karty; decyzje wobec nich zapadają przy ich linii.
  const [alreadyOnOrder, setAlreadyOnOrder] = useState<PersonAlreadyOnOrder[]>([]);
  // PDF z maila przy uzupełnianiu zamówienia, które MA już swój PDF: domyślnie
  // służy tylko do odczytu. Podmiana pliku zamówienia (także w dokumentach
  // wszystkich konsultantów) to osobna, świadoma decyzja.
  const [replaceWithMailFile, setReplaceWithMailFile] = useState(false);
  // Wariant liczby MD rozpoznany w dokumencie — przy każdej osobie albo jedna
  // liczba na całe zamówienie. Ustawia tryb budżetu MD, zamiast zgłaszać
  // „brak MD" tam, gdzie dokument podał je w drugim wariancie.
  const [mdScope, setMdScope] = useState<OrderGroupExtraction["md_scope"]>(null);
  const [clientPolicy, setClientPolicy] = useState<string | null | undefined>(
    undefined,
  );
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);
  // Karty konsultantów z PDF-a. W nowym zamówieniu — cała obsada; przy
  // uzupełnianiu — wyłącznie osoby, których na zamówieniu jeszcze nie ma
  // (ten sam mechanizm dopasowania i te same decyzje wobec osoby nieaktywnej
  // albo nieznalezionej).
  const [lines, setLines] = useState<OrderLineDraft[]>([]);
  const [planned, setPlanned] = useState(false);

  // Odpowiedź odczytu porównujemy ze stanem z chwili ODPOWIEDZI, nie
  // kliknięcia — w trakcie kilkusekundowego odczytu użytkownik może coś
  // wpisać, a taka zmiana musi przejść przez pytanie o rozbieżność.
  const formRef = useRef({ orderNumber, startDate, endDate, budgetAmount, mdBudgetTotal });
  formRef.current = { orderNumber, startDate, endDate, budgetAmount, mdBudgetTotal };
  // Wartości pól wpisane przez POPRZEDNI odczyt dokumentu. Pole, które nadal
  // je trzyma, nie jest „wpisane ręcznie": kolejny odczyt innego PDF-a może je
  // nadpisać bez pytania (a pytanie nie podpisuje ich jako „wpisano"). Bez
  // tego kwota z pierwszego PDF-a zostawała po odczycie drugiego (UAT M07-B02).
  const documentValuesRef = useRef<DocumentFieldValues>({});

  useEffect(() => {
    if (!open) return;
    setOrderNumber(group?.order_number ?? initialOrderNumber);
    setExecutiveContractId(
      group?.executive_contract ? String(group.executive_contract.id) : "",
    );
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
    setFile(autoReadFile ?? (group ? null : initialFile));
    setHasExistingFile(Boolean(group?.has_file));
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
    setAlreadyOnOrder([]);
    setReplaceWithMailFile(false);
    setMdScope(null);
    setClientPolicy(undefined);
    setConflicts([]);
    setPendingApply(null);
    setLines([]);
    setPlanned(false);
    documentValuesRef.current = {};
    // `initialFile`/`initialOrderNumber` celowo poza zależnościami: przejmujemy
    // je raz, przy otwarciu — późniejsza zmiana w rodzicu nie może nadpisać
    // wyboru tutaj.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, group]);

  // PDF z maila odczytujemy SAM raz na otwarcie — reszta jak przy ręcznym
  // „Zczytaj": pytanie o rozbieżność pól nagłówka, karty osób do decyzji.
  const autoReadDone = useRef<File | null>(null);
  useEffect(() => {
    if (!open) {
      autoReadDone.current = null;
      return;
    }
    if (!autoReadFile || file !== autoReadFile) return;
    if (autoReadDone.current === autoReadFile) return;
    autoReadDone.current = autoReadFile;
    void handleExtractPlan();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, autoReadFile, file]);

  const planContext = {
    orderType,
    sharedMd,
    groupStart: startDate,
    groupEnd: endDate || null,
  };
  const lineMd = usesLineMd(planContext);
  const duplicated = useMemo(() => duplicatePersonKeys(lines), [lines]);
  // Przy uzupełnianiu: osoba wskazana ręcznie na karcie może już pracować na
  // tym zamówieniu (karta bez dopasowania, „kilka osób"). Druga linia tej
  // samej osoby to drugi budżet MD — karta tego nie zapisze (serwer też nie).
  const liveContractIds = new Set(
    (group?.lines ?? [])
      .filter((line) => !line.removed_from_order && ["active", "draft", "paused"].includes(line.status))
      .map((line) => line.contract_id),
  );
  const issuesByKey = new Map(
    lines.map((line) => [
      line.key,
      [
        ...lineIssues(line, planContext),
        ...(line.person?.contractId != null && liveContractIds.has(line.person.contractId)
          ? ["ta osoba jest już na zamówieniu — usuń kartę, stawkę albo MD zmienisz przy jej linii"]
          : []),
      ],
    ]),
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

  /** Jeden odczyt PDF-a: nagłówek + karta dla każdej osoby z dokumentu.
   *
   *  Ten sam odczyt i to samo dopasowanie osób w obu trybach okna. W nowym
   *  zamówieniu karty to cała obsada; przy uzupełnianiu — osoby, których na
   *  zamówieniu jeszcze nie ma (osoba nieaktywna/nieznaleziona dostaje ten sam
   *  komunikat i ten sam wybór: zostaw / wznów / zastąp / usuń). */
  async function handleExtractPlan() {
    if (!file || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await orderGroupsApi.extractPlan(clientId, file);
      const current = formRef.current;
      const allDrafts = draftsFromPlan(data);
      // Przy uzupełnianiu karta bez nazwiska z dokumentu (BNP: tylko numer ID
      // konsultanta) nie jest osobą do dopisania — to pola nagłówka.
      const split = group
        ? splitPlanForGroup(
            allDrafts.filter((draft) => draft.documentName !== null),
            group.lines,
          )
        : { toAdd: allDrafts, onOrder: [] };
      const drafts = split.toAdd;
      setAlreadyOnOrder(split.onOrder);
      const sumMd = allDrafts.reduce<number | null>((sum, line) => {
        const md = parseDecimalInput(line.md);
        return sum === null || md === null ? null : sum + md;
      }, 0);
      const poolMd = data.md_total ?? (allDrafts.length > 0 ? sumMd : null);
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
      const documentBudget =
        data.total_value != null && documentCurrency === "PLN"
          ? numberToField(data.total_value)
          : null;
      const documentPool = poolMd != null ? String(poolMd) : null;
      const previousDocument = documentValuesRef.current;
      const typed = {
        title: typedByUser(current.orderNumber, previousDocument.title),
        start_date: typedByUser(current.startDate, previousDocument.start_date),
        end_date: typedByUser(current.endDate, previousDocument.end_date),
        total_value: typedByUser(current.budgetAmount, previousDocument.total_value),
        md_total: typedByUser(current.mdBudgetTotal, previousDocument.md_total),
      };
      const nextDocument: DocumentFieldValues = { ...previousDocument };
      if (!group) {
        // Pole puste albo z poprzedniego dokumentu → bierze wartość z TEGO
        // dokumentu (także brak — stara kwota z innego PDF-a nie zostaje).
        // Kwota wpisana ręcznie → pytanie o rozbieżność niżej.
        if (!typed.total_value) {
          setBudgetAmount(documentBudget ?? "");
          nextDocument.total_value = documentBudget ?? "";
        }
        if (!typed.md_total) {
          setMdBudgetTotal(documentPool ?? "");
          nextDocument.md_total = documentPool ?? "";
        }
      }
      documentValuesRef.current = nextDocument;
      // BIK: brak daty końca to poprawny odczyt („bezterminowo — do
      // wyczerpania MD"), więc pole „do" jest czyszczone jawnie.
      const extractedEnd = extractedEndDate(data);
      // Przy uzupełnianiu kwota i pula MD istniejącego zamówienia to pola jak
      // każde inne: nadpisanie wpisanej wartości wymaga zgody (pytanie niżej).
      const applyBudget = Boolean(group);
      const apply = () => {
        const applied: DocumentFieldValues = { ...documentValuesRef.current };
        if (data.order_number) {
          setOrderNumber(data.order_number);
          applied.title = data.order_number;
        }
        if (data.start_date) {
          setStartDate(data.start_date.slice(0, 10));
          applied.start_date = data.start_date.slice(0, 10);
        }
        if (extractedEnd) {
          setEndDate(extractedEnd.value);
          applied.end_date = extractedEnd.value;
        }
        if ((applyBudget ? isCostBased : true) && documentBudget !== null) {
          setBudgetAmount(documentBudget);
          applied.total_value = documentBudget;
        }
        if (applyBudget && sharedMd && data.md_total != null) {
          setMdBudgetTotal(numberToField(data.md_total));
          applied.md_total = numberToField(data.md_total);
        } else if (!applyBudget && documentPool !== null) {
          setMdBudgetTotal(documentPool);
          applied.md_total = documentPool;
        }
        documentValuesRef.current = applied;
      };
      const found = findConflicts([
        {
          key: "title",
          label: "Numer zamówienia",
          current: typed.title,
          incoming: data.order_number ?? null,
        },
        {
          key: "start_date",
          label: "Obowiązuje od",
          current: typed.start_date,
          incoming: data.start_date ? data.start_date.slice(0, 10) : null,
        },
        {
          key: "end_date",
          label: "Obowiązuje do",
          current: typed.end_date,
          incoming: extractedEnd?.display ?? null,
        },
        ...(!group || isCostBased
          ? [
              {
                key: "total_value" as const,
                label: "Kwota zamówienia",
                current: typed.total_value,
                incoming: documentBudget,
              },
            ]
          : []),
        ...(group && sharedMd
          ? [
              {
                key: "md_total" as const,
                label: "Budżet w MD",
                current: typed.md_total,
                incoming: numberToField(data.md_total) || null,
              },
            ]
          : !group
            ? [
                {
                  key: "md_total" as const,
                  label: "Budżet w MD",
                  current: typed.md_total,
                  incoming: documentPool,
                },
              ]
            : []),
      ]);
      setConsultantRef(data.consultant_ref ?? null);
      setClientPolicy(data.client_policy);
      setMdScope(data.md_scope ?? null);
      // Tryb budżetu ustawia odczyt tylko przy zakładaniu — przy uzupełnianiu
      // zmienia go wyłącznie świadomy przełącznik (kasuje podział budżetu).
      if (!group && !modeLocked && data.md_scope) {
        setSharedChoice(data.md_scope === "order");
      }
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
    readyCount < lines.length ||
    (!editing &&
      isMdOrder &&
      !sharedMd &&
      draftStatus === "active" &&
      lines.length === 0);
  const canSubmit =
    !submitting &&
    orderNumber.trim() !== "" &&
    startDate !== "" &&
    !budgetMissing &&
    !linesBlocked &&
    !executiveContractMissing &&
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
    setAlreadyOnOrder([]);
    setLines((existing) => existing.filter((line) => line.ordinal === null));
    setPlanned(false);
  }

  // Plik z maila przy zamówieniu z PDF-em — bez zgody nie podmienia pliku.
  const mailFileReadOnly =
    Boolean(group?.has_file) &&
    autoReadFile !== null &&
    file === autoReadFile &&
    !replaceWithMailFile;

  function submit() {
    if (!canSubmit) return;
    onSubmit(
      {
        order_number: orderNumber.trim(),
        start_date: startDate,
        end_date: endDate || null,
        notes: notes.trim() || null,
        // Umowa wykonawcza tylko przy ZAKŁADANIU — `OrderGroupPatch` jej nie
        // niesie, a przepięcie zamówienia pod inną umowę to osobna decyzja.
        ...(ezdrowie && !editing && executiveContractId
          ? { executive_contract_id: Number(executiveContractId) }
          : {}),
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
          ? // Uzupełnienie z PDF-a: osoby spoza zamówienia — rodzic dopisuje
            // je jednym zapisem (`…/lines/batch`), razem albo wcale.
            lines.length > 0
            ? { lines: lines.map((line) => toLineInput(line, planContext)) }
            : {}
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
      mailFileReadOnly ? null : file,
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
          setAlreadyOnOrder([]);
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
          onClick={handleExtractPlan}
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
      <p className="mt-1 text-xs text-muted-foreground">
        {editing
          ? "Odczytuje numer, datę i konsultantów z dokumentu. Osoby, których nie ma jeszcze na zamówieniu, pojawią się niżej do dopisania — w tym te bez aktywnej współpracy albo nieznalezione w systemie, z wyborem, co z nimi zrobić."
          : "Odczytuje numer, datę i wszystkich konsultantów z dokumentu, dopasowuje ich do kontraktów u klienta i uzupełnia stawki oraz MD w tym samym oknie."}
      </p>
    </div>
  );

  const onOrderNote =
    editing && alreadyOnOrder.length > 0 ? (
      <div
        role="status"
        className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
      >
        <p className="font-medium text-foreground">
          Już na zamówieniu ({alreadyOnOrder.length}):
        </p>
        <ul className="mt-1 space-y-0.5">
          {alreadyOnOrder.map(({ draft, line }) => {
            const ended =
              draft.match === "inactive" ||
              (Boolean(line.cooperation_ended_on) && !line.is_active);
            const differs = documentDiffers(draft, line);
            return (
              <li key={draft.key}>
                {line.consultant_name}
                {ended
                  ? " — nie ma już aktywnej współpracy; zostaw / zastąp / usuń tę osobę przy jej linii na karcie zamówienia (jej wykorzystana kwota i MD nie wrócą do puli)"
                  : differs
                    ? ` — dokument podaje inne ${differs} niż linia na zamówieniu; zmień je w „Edytuj linię”`
                    : " — jest na zamówieniu, nic nie dopisujemy"}
              </li>
            );
          })}
        </ul>
      </div>
    ) : null;

  const linesSection =
    !editing || planned || lines.length > 0 ? (
    <section aria-label="Konsultanci na zamówieniu" className="space-y-3">
      {onOrderNote}
      {planned || lines.length > 0 ? (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" aria-hidden />
          {lines.length > 0
            ? editing
              ? `${lines.length} ${lines.length === 1 ? "osoba" : "osoby"} z dokumentu do dopisania`
              : `${lines.length} ${lines.length === 1 ? "konsultant" : "konsultantów"} na zamówieniu`
            : editing
              ? "Wszystkie osoby z dokumentu są już na zamówieniu"
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
      {!editing ? (
        <button
          type="button"
          onClick={() => setLines((current) => [...current, emptyDraft()])}
          className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
        >
          <Plus className="h-4 w-4" aria-hidden /> Dodaj konsultanta
        </button>
      ) : null}
      {lines.length > 0 && !editing ? (
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
      size={editing && lines.length === 0 ? "md" : "lg"}
      title={editing ? "Uzupełnij zamówienie" : "Nowe zamówienie"}
      description={
        editing
          ? "Numer, okres i budżet. Z PDF-a dopiszesz osoby, których nie ma jeszcze na zamówieniu; istniejące linie edytujesz osobno."
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
          onChange={(next) => onOrderTypeChange(next, file, orderNumber)}
          allowedTypes={allowedOrderTypes}
          disabled={editing}
        />
        {!editing ? (
          <p className="-mt-2 text-xs text-muted-foreground">
            Podpowiadamy typ najczęstszy u tego klienta. Każdy typ jest dostępny —
            możesz go zmienić w każdej chwili, także po odczycie PDF-a.
          </p>
        ) : null}

        {sourceNotice ? (
          <div
            role="status"
            className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground"
          >
            <p>{sourceNotice}</p>
            {group?.has_file && autoReadFile && file === autoReadFile ? (
              <label className="mt-2 flex items-start gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={replaceWithMailFile}
                  onChange={(event) => setReplaceWithMailFile(event.target.checked)}
                />
                Zastąp PDF tego zamówienia plikiem z maila (także w dokumentach
                konsultantów). Bez zaznaczenia plik z maila służy tylko do
                odczytu.
              </label>
            ) : null}
          </div>
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
            {!editing && mdScope ? (
              <p className="text-xs text-muted-foreground">
                {mdScope === "order"
                  ? "Dokument podaje jedną liczbę MD na całe zamówienie — ustawiono wspólny budżet MD dzielony między konsultantów."
                  : "Dokument podaje limit MD przy każdej osobie — budżet MD jest per konsultant."}
              </p>
            ) : null}
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

        {ezdrowie && !editing ? (
          <div>
            <label htmlFor="group-executive-contract" className={labelClass}>
              Umowa wykonawcza *
            </label>
            {executiveContracts.isError ? (
              <p role="alert" className="text-xs text-destructive">
                Nie udało się wczytać umów wykonawczych.{" "}
                <button
                  type="button"
                  onClick={() => executiveContracts.refetch()}
                  className="font-medium underline underline-offset-2"
                >
                  Ponów
                </button>
              </p>
            ) : executiveContracts.isSuccess && executiveContracts.groups.length === 0 ? (
              // Pusty select udawałby listę do wyboru; brak aktywnych umów to
              // stan do naprawienia gdzie indziej.
              <p className="text-xs text-muted-foreground">
                Brak aktywnych umów wykonawczych. Dodaj umowę wykonawczą w sekcji
                Struktura umów na profilu klienta.
              </p>
            ) : (
              <select
                id="group-executive-contract"
                value={executiveContractId}
                onChange={(e) => setExecutiveContractId(e.target.value)}
                className={inputClass}
                disabled={!executiveContracts.isSuccess}
              >
                <option value="">
                  {executiveContracts.isSuccess ? "— wybierz —" : "Wczytywanie…"}
                </option>
                {executiveContracts.groups.map((part) => (
                  <optgroup key={part.framework_contract_id} label={part.label}>
                    {part.options.map((contract) => (
                      <option key={contract.id} value={contract.id}>
                        {contract.number}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            )}
            {executiveContractMissing && executiveContracts.groups.length > 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Wybierz umowę wykonawczą.
              </p>
            ) : null}
          </div>
        ) : null}
        {ezdrowie && editing && group?.executive_contract ? (
          <p className="text-xs text-muted-foreground">
            Umowa wykonawcza:{" "}
            <span className="font-medium text-foreground">
              {group.executive_contract.number}
            </span>
          </p>
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

        {!editing ? linesSection : null}

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
        {editing ? linesSection : null}
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
