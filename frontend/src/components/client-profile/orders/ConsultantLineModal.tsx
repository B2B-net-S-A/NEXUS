"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, FileSearch } from "lucide-react";

import { OrderCurrencySelect } from "@/components/orders/OrderRateUnitToggle";
import { AppModal, FileDropZone } from "@/components/ds";
import { dlPortalApi } from "@/lib/api/dlPortal";
import {
  extractionErrorMessage,
  findConflicts,
  numberToField,
  type ExtractionConflict,
} from "@/lib/order-extraction";
import type {
  ConsultantOption,
  OrderGroupRead,
  OrderInputMode,
  OrderLineRead,
} from "@/lib/api/orderGroups";
import { usesSharedMdPool } from "@/lib/client-order-list";
import {
  contractRateUnitToInputUnit,
  convertRate,
  rateUnitLabel,
  toMdRate,
  type RateUnit,
} from "@/lib/rate-unit";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { ConsultantPicker } from "./ConsultantPicker";
import { ExtractionConflictDialog } from "./ExtractionConflictDialog";
import { formatMd } from "./MdBudgetBar";

/** Ten sam limit i te same rozszerzenia co na endpointach zamówień. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.doc";
const INCOMPLETE_PROFILE_NAME_DETAIL =
  "Kandydat nie ma imienia i nazwiska do dopasowania";
const INCOMPLETE_PROFILE_NAME_MESSAGE =
  "Uzupełnij brakujące imię lub nazwisko w profilu konsultanta, aby odczytać dane z dokumentu.";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass =
  "mb-1 block text-xs font-semibold text-muted-foreground";
const COST_RATE_UNITS: readonly RateUnit[] = ["hour", "md", "month"];
const REVENUE_RATE_UNITS: readonly RateUnit[] = ["hour", "md", "month"];

function extractionRateUnit(value: string | null): RateUnit | null {
  if (value === "hour") return "hour";
  if (value === "day") return "md";
  if (value === "month") return "month";
  return null;
}

function isIncompleteProfileNameError(err: unknown): boolean {
  const response = (
    err as {
      response?: { status?: number; data?: { detail?: unknown } };
    }
  )?.response;
  return (
    response?.status === 422 &&
    response.data?.detail === INCOMPLETE_PROFILE_NAME_DETAIL
  );
}

export interface LineFormValues {
  rate_candidate_currency?: string;
  rate_client_currency?: string;
  /** Dokładnie jedno z pól. `contract_id` — osoba ma już kontrakt u tego
   *  klienta; `candidate_id` — osoba z bazy Nexus, kontrakt założy serwer. */
  contract_id?: number | null;
  candidate_id?: number | null;
  rate_cost: number;
  rate_revenue: number;
  /** Pomijane na zamówieniu KOSZTOWYM — pula jest wspólna i mieszka na
   *  zamówieniu, a nie przy osobie (backend odrzuca komplet). */
  input_mode?: OrderInputMode | null;
  input_value?: number | null;
  start_date: string;
  end_date: string | null;
}

interface AutoExtractedValues {
  candidateId: number;
  rateRevenue: string | null;
  rateRevenueUnit: RateUnit | null;
  inputValue: string | null;
  inputMode: OrderInputMode | null;
  startDate: string | null;
  endDate: string | null;
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

/**
 * Przełącznik jednostki przy polu stawki.
 *
 * Przeliczenie odpala się PRZY ZMIANIE jednostki, a nie przy zapisie: operator
 * ma zobaczyć nową liczbę od razu i móc ją poprawić. Puste pole zostaje puste —
 * przeliczanie niczego na zero wpisałoby wartość, której nikt nie podał.
 */
function RateUnitToggle({
  id,
  unit,
  onUnitChange,
  value,
  onValueChange,
  units,
  currency,
  ariaLabel,
}: {
  id: string;
  unit: RateUnit;
  onUnitChange: (next: RateUnit) => void;
  value: string;
  onValueChange: (next: string) => void;
  units: readonly RateUnit[];
  currency: string;
  ariaLabel: string;
}) {
  const switchTo = (next: RateUnit) => {
    if (next === unit) return;
    const parsed = parseDecimalInput(value);
    if (parsed !== null) {
      const converted = convertRate(parsed, unit, next);
      if (converted !== null) onValueChange(String(converted));
    }
    onUnitChange(next);
  };

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="mt-1 inline-flex max-w-full flex-wrap rounded-md border border-border p-0.5"
    >
      {units.map((option) => (
        <button
          key={option}
          id={`${id}-${option}`}
          type="button"
          aria-pressed={unit === option}
          onClick={() => switchTo(option)}
          className={
            "rounded px-2 py-1 text-xs font-medium transition-colors " +
            (unit === option
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground")
          }
        >
          {rateUnitLabel(option, currency)}
        </button>
      ))}
    </div>
  );
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
  // Jednostka WPROWADZANIA, niezależna dla każdej stawki: kosztowa przychodzi
  // zwykle z kontraktu (godzinowa), przychodowa z zamówienia klienta (MD).
  // Wysyłamy stawkę MD w wybranej walucie. Backend zachowuje ją wraz
  // z walutą i oblicza osobno pomocniczą stawkę PLN/MD.
  const [costUnit, setCostUnit] = useState<RateUnit>("md");
  const [costCurrency, setCostCurrency] = useState("PLN");
  const [revenueCurrency, setRevenueCurrency] = useState("PLN");
  const [, setCostRateToPln] = useState(1);
  const [revenueUnit, setRevenueUnit] = useState<RateUnit>("md");
  const [inputMode, setInputMode] = useState<OrderInputMode>("md");
  const [inputValue, setInputValue] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [remaining, setRemaining] = useState("");

  // Zamówienie kosztowe: jedna wspólna pula na zamówieniu, więc linia NIE ma
  // własnego budżetu MD. Wymuszanie go zmuszałoby operatora do wymyślenia
  // liczby, której nikt nigdy nie rozliczy.
  const costBased = Boolean(group?.is_cost_based);
  // Wspólna pula MD jest świadomym wariantem tylko dla CP/Lotte. Każdy inny
  // klient ma niezależny budżet przy linii, nawet gdy stary rekord nosi flagę.
  const sharedMdBased = group ? usesSharedMdPool(group) : false;

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  // Numer ID konsultanta z dokumentu (polityka BNP). PDF-y tego klienta
  // nie niosą imienia ani nazwiska, więc to JEDYNY ślad tożsamości
  // w pliku — pokazujemy go do wzrokowego potwierdzenia, że dokument
  // dotyczy wybranej osoby. Nexus nie przechowuje identyfikatorów
  // nadanych przez klienta, więc nie ma tego z czym zestawić
  // automatycznie i pole jest świadomie informacyjne.
  const [consultantRef, setConsultantRef] = useState<string | null>(null);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  const [unitChangeNotice, setUnitChangeNotice] = useState<string | null>(null);
  const [grossConversion, setGrossConversion] = useState<{
    gross: string;
    net: string;
  } | null>(null);
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);
  const [autoExtracted, setAutoExtracted] =
    useState<AutoExtractedValues | null>(null);
  // Odpowiedź sieciowa musi porównać się ze stanem z chwili ODPOWIEDZI, nie ze
  // stanem zamkniętym w async handlerze przy starcie requestu. Użytkownik może
  // w tym czasie poprawić pole ręcznie i taka zmiana wymaga dialogu konfliktu.
  const extractionFormRef = useRef({
    rateCost,
    costUnit,
    rateRevenue,
    revenueUnit,
    inputValue,
    inputMode,
    startDate,
    endDate,
    autoExtracted,
  });
  extractionFormRef.current = {
    rateCost,
    costUnit,
    rateRevenue,
    revenueUnit,
    inputValue,
    inputMode,
    startDate,
    endDate,
    autoExtracted,
  };

  const targetCandidateId = line?.candidate_id ?? person?.candidate_id ?? null;
  const missingProfileName = person
    ? !person.first_name?.trim() && !person.last_name?.trim()
      ? "imię i nazwisko"
      : !person.first_name?.trim()
        ? "imię"
        : !person.last_name?.trim()
          ? "nazwisko"
          : null
    : null;
  // W edycji picker nie istnieje, więc nie mamy osobnych pól imienia i
  // nazwiska. Jedno puste/jednoelementowe `consultant_name` jednoznacznie
  // oznacza niekompletny profil. Wieloczłonowych nazwisk nie zgadujemy — ich
  // autorytatywną walidację zwróci backend i mapujemy ją niżej z 422.
  const editProfileNameIncomplete = Boolean(
    line &&
      line.consultant_name
        .trim()
        .split(/\s+/)
        .filter(Boolean).length < 2,
  );
  const profileNameMessage = missingProfileName
    ? `Uzupełnij ${missingProfileName} w profilu konsultanta, aby odczytać dane z dokumentu.`
    : editProfileNameIncomplete
      ? INCOMPLETE_PROFILE_NAME_MESSAGE
      : null;
  // Każda zmiana pliku, osoby, linii lub ponowne otwarcie unieważnia starszy
  // request. Sam candidate_id nie wystarcza: dwa PDF-y mogą dotyczyć tej samej
  // osoby, a wolniejsza odpowiedź starego pliku nie może wygrać wyścigu.
  const extractionEpochRef = useRef(0);

  const clearAutoExtractedValues = (includeDates: boolean) => {
    if (!autoExtracted) return;
    if (
      autoExtracted.rateRevenue != null &&
      autoExtracted.rateRevenueUnit != null &&
      rateRevenue === autoExtracted.rateRevenue &&
      revenueUnit === autoExtracted.rateRevenueUnit
    ) {
      setRateRevenue("");
      setRevenueUnit("md");
    }
    if (
      autoExtracted.inputValue != null &&
      autoExtracted.inputMode != null &&
      inputValue === autoExtracted.inputValue &&
      inputMode === autoExtracted.inputMode
    ) {
      setInputValue("");
    }
    if (includeDates) {
      if (
        autoExtracted.startDate != null &&
        startDate === autoExtracted.startDate
      ) {
        setStartDate(line?.start_date ?? group?.start_date ?? "");
      }
      if (
        autoExtracted.endDate != null &&
        endDate === autoExtracted.endDate
      ) {
        setEndDate(line?.end_date ?? "");
      }
      setAutoExtracted(null);
      return;
    }
    // Daty dotyczą całego dokumentu, nie osoby. Zachowujemy informację o ich
    // pochodzeniu, aby późniejsza zmiana PDF nadal potrafiła je wyczyścić.
    setAutoExtracted(
      autoExtracted.startDate != null || autoExtracted.endDate != null
        ? {
            ...autoExtracted,
            rateRevenue: null,
            rateRevenueUnit: null,
            inputValue: null,
            inputMode: null,
          }
        : null,
    );
  };

  const handlePersonChange = (next: ConsultantOption | null) => {
    const nextCandidateId = next?.candidate_id ?? null;
    if (nextCandidateId !== person?.candidate_id) {
      // Stawka i MD są danymi OSOBY. Przy zmianie konsultanta nie przenosimy
      // ani automatycznego, ani ręcznego wpisu poprzedniej osoby.
      setRateRevenue("");
      setRevenueUnit("md");
      setInputValue("");
      setInputMode("md");
      setGrossConversion(null);
      const extractedDates =
        autoExtracted &&
        (autoExtracted.startDate != null || autoExtracted.endDate != null)
          ? {
              ...autoExtracted,
              candidateId: nextCandidateId ?? autoExtracted.candidateId,
              rateRevenue: null,
              rateRevenueUnit: null,
              inputValue: null,
              inputMode: null,
            }
          : null;
      setAutoExtracted(extractedDates);
    }
    extractionEpochRef.current += 1;
    setExtracting(false);
    // Konflikty i ostrzeżenia opisują poprzednią osobę; nie mogą przeżyć zmiany
    // targetu i zostać potwierdzone dla nowego konsultanta.
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
    setUnitChangeNotice(null);
    setGrossConversion(null);
    setConflicts([]);
    setPendingApply(null);
    setExtractError(null);
    setPerson(next);
    // Każda zmiana osoby resetuje poprzednią wartość. Podpowiedź pochodzi
    // wyłącznie z aktywnego kontraktu tej osoby u bieżącego klienta;
    // `null` (brak kontraktu albo brak zapisanej stawki) zostawia puste pole.
    // Dalsze wpisywanie jest zwykłą lokalną edycją linii zamówienia.
    // Nowy payload niesie SUROWĄ wartość kontraktu w osobnym polu. Legacy
    // `suggested_rate_cost` MUSI pozostać PLN/MD, bo starszy frontend zapisuje
    // je bez metadanych. Nowe pole wybieramy tylko, gdy rzeczywiście istnieje.
    const hasRawSuggestion = next?.suggested_contract_rate_cost != null;
    setCostUnit(
      hasRawSuggestion
        ? contractRateUnitToInputUnit(next?.suggested_rate_cost_unit)
        : "md",
    );
    setCostCurrency(
      hasRawSuggestion
        ? next?.suggested_rate_cost_currency?.trim().toUpperCase() || "PLN"
        : "PLN",
    );
    const rateToPln = hasRawSuggestion
      ? next?.suggested_rate_cost_rate_to_pln
      : 1;
    setCostRateToPln(
      typeof rateToPln === "number" && Number.isFinite(rateToPln) && rateToPln > 0
        ? rateToPln
        : 1,
    );
    setRateCost(
      hasRawSuggestion
        ? String(next.suggested_contract_rate_cost)
        : next?.suggested_rate_cost != null
          ? String(next.suggested_rate_cost)
          : "",
    );
  };

  useEffect(() => {
    extractionEpochRef.current += 1;
    setExtracting(false);
    if (!open) return;
    setPerson(null);
    const sourceCost = line?.source_rate_cost ?? line?.rate_cost;
    setRateCost(sourceCost != null ? String(sourceCost) : "");
    const sourceRevenue = line?.source_rate_revenue ?? line?.rate_revenue;
    setRateRevenue(sourceRevenue != null ? String(sourceRevenue) : "");
    // Wartości z API są w zł/MD, więc formularz otwiera się w tej jednostce —
    // inaczej pierwszy render pokazywałby liczbę ośmiokrotnie za dużą pod
    // etykietą „zł/h”.
    setCostUnit("md");
    setCostCurrency(
      line?.rate_candidate_currency ?? "PLN",
    );
    setRevenueCurrency(line?.rate_client_currency ?? "PLN");
    setCostRateToPln(1);
    setRevenueUnit("md");
    setInputMode(line?.input_mode ?? "md");
    setInputValue(line?.input_value != null ? String(line.input_value) : "");
    setStartDate(line?.start_date ?? group?.start_date ?? "");
    setEndDate(line?.end_date ?? "");
    setRemaining(line?.md_remaining != null ? String(line.md_remaining) : "");
    setFile(null);
    setFileError(null);
    setExtractError(null);
    setCheckData(false);
    setCheckReasons([]);
    setConsultantRef(null);
    setUnitChangeNotice(null);
    setGrossConversion(null);
    setConflicts([]);
    setPendingApply(null);
    setAutoExtracted(null);
  }, [open, line, group]);

  async function handleExtract() {
    const candidateId = targetCandidateId;
    if (!file || extracting || candidateId == null || profileNameMessage) return;
    const requestEpoch = extractionEpochRef.current + 1;
    extractionEpochRef.current = requestEpoch;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(
        clientId,
        file,
        candidateId,
      );
      if (extractionEpochRef.current !== requestEpoch) return;
      const extractedRateUnit = extractionRateUnit(data.rate_unit);
      const invalidRateUnit =
        data.rate_client != null && extractedRateUnit == null;
      const extractedRate =
        data.rate_client != null && extractedRateUnit != null
          ? String(data.rate_client)
          : null;
      const explicitUnitMismatch =
        extractedRate != null &&
        extractedRateUnit != null &&
        extractedRateUnit !== extractionFormRef.current.revenueUnit;
      const extractedMd =
        !costBased && !sharedMdBased && data.md_total != null
          ? String(data.md_total)
          : null;
      const extractedStart = data.start_date
        ? data.start_date.slice(0, 10)
        : null;
      const extractedEnd = data.end_date ? data.end_date.slice(0, 10) : null;
      const currentForm = extractionFormRef.current;
      const apply = () => {
        if (extractionEpochRef.current !== requestEpoch) return;
        const previousAutoRateStillPresent =
          currentForm.autoExtracted?.candidateId === candidateId &&
          currentForm.autoExtracted.rateRevenue != null &&
          currentForm.autoExtracted.rateRevenueUnit != null &&
          currentForm.rateRevenue === currentForm.autoExtracted.rateRevenue &&
          currentForm.revenueUnit ===
            currentForm.autoExtracted.rateRevenueUnit;
        const previousAutoMdStillPresent =
          currentForm.autoExtracted?.candidateId === candidateId &&
          currentForm.autoExtracted.inputValue != null &&
          currentForm.autoExtracted.inputMode != null &&
          currentForm.inputValue === currentForm.autoExtracted.inputValue &&
          currentForm.inputMode === currentForm.autoExtracted.inputMode;
        const previousAutoStartStillPresent =
          currentForm.autoExtracted?.candidateId === candidateId &&
          currentForm.autoExtracted.startDate != null &&
          currentForm.startDate === currentForm.autoExtracted.startDate;
        const previousAutoEndStillPresent =
          currentForm.autoExtracted?.candidateId === candidateId &&
          currentForm.autoExtracted.endDate != null &&
          currentForm.endDate === currentForm.autoExtracted.endDate;
        // Zapamiętujemy wyłącznie pola, które odczyt faktycznie zmienił. Gdy
        // dokument powtórzył wartość istniejącą wcześniej, wybór kolejnego PDF
        // nie może usunąć tej ręcznej/zapisanej wartości jako „automatycznej".
        const changedRate =
          extractedRate != null &&
          (currentForm.rateRevenue !== extractedRate ||
            currentForm.revenueUnit !== extractedRateUnit);
        const changedMd =
          extractedMd != null &&
          (currentForm.inputMode !== "md" ||
            currentForm.inputValue !== extractedMd);
        const changedStart =
          extractedStart != null && currentForm.startDate !== extractedStart;
        const changedEnd =
          extractedEnd != null && currentForm.endDate !== extractedEnd;
        const sameAutoCandidate =
          currentForm.autoExtracted?.candidateId === candidateId;
        // Ponowny odczyt tego samego dokumentu nie może zgubić informacji, że
        // wartości nadal pochodzą z PDF. Zachowujemy provenance tylko wtedy,
        // gdy poprzedni auto-wynik, formularz i nowy wynik są identyczne.
        const retainedRate =
          sameAutoCandidate &&
          extractedRate != null &&
          extractedRateUnit != null &&
          currentForm.autoExtracted?.rateRevenue === extractedRate &&
          currentForm.autoExtracted.rateRevenueUnit === extractedRateUnit &&
          currentForm.rateRevenue === extractedRate &&
          currentForm.revenueUnit === extractedRateUnit;
        const retainedMd =
          sameAutoCandidate &&
          extractedMd != null &&
          currentForm.autoExtracted?.inputValue === extractedMd &&
          currentForm.autoExtracted.inputMode === "md" &&
          currentForm.inputValue === extractedMd &&
          currentForm.inputMode === "md";
        const retainedStart =
          sameAutoCandidate &&
          extractedStart != null &&
          currentForm.autoExtracted?.startDate === extractedStart &&
          currentForm.startDate === extractedStart;
        const retainedEnd =
          sameAutoCandidate &&
          extractedEnd != null &&
          currentForm.autoExtracted?.endDate === extractedEnd &&
          currentForm.endDate === extractedEnd;
        const trackedRate = changedRate || retainedRate;
        const trackedMd = changedMd || retainedMd;
        const trackedStart = changedStart || retainedStart;
        const trackedEnd = changedEnd || retainedEnd;
        if (extractedStart != null) setStartDate(extractedStart);
        else if (previousAutoStartStillPresent) {
          setStartDate(line?.start_date ?? group?.start_date ?? "");
        }
        if (extractedEnd != null) setEndDate(extractedEnd);
        else if (previousAutoEndStillPresent) setEndDate(line?.end_date ?? "");
        if (extractedRate != null) {
          if (explicitUnitMismatch && extractedRateUnit != null) {
            const parsedCost = parseDecimalInput(currentForm.rateCost);
            if (parsedCost !== null) {
              const convertedCost = convertRate(
                parsedCost,
                currentForm.costUnit,
                extractedRateUnit,
              );
              if (convertedCost !== null) setRateCost(String(convertedCost));
            }
            setCostUnit(extractedRateUnit);
            setUnitChangeNotice(
              `Jednostkę stawki zmieniono na ${extractedRateUnit === "md" ? "MD" : extractedRateUnit === "hour" ? "godzinową" : "miesięczną"} na podstawie dodanej pozycji. Stawkę kosztową przeliczono automatycznie.`,
            );
          }
          setRevenueUnit(extractedRateUnit as RateUnit);
          setRateRevenue(extractedRate);
          setGrossConversion(
            data.rate_client_gross != null
              ? {
                  gross: String(data.rate_client_gross),
                  net: extractedRate,
                }
              : null,
          );
        } else if (previousAutoRateStillPresent) {
          setRateRevenue("");
          setRevenueUnit("md");
          setGrossConversion(null);
        }
        if (extractedMd != null) {
          setInputMode("md");
          setInputValue(extractedMd);
        } else if (previousAutoMdStillPresent) {
          setInputValue("");
        }
        setAutoExtracted(
          trackedRate || trackedMd || trackedStart || trackedEnd
            ? {
                candidateId,
                rateRevenue: trackedRate ? extractedRate : null,
                rateRevenueUnit: trackedRate ? extractedRateUnit : null,
                inputValue: trackedMd ? extractedMd : null,
                inputMode: trackedMd ? "md" : null,
                startDate: trackedStart ? extractedStart : null,
                endDate: trackedEnd ? extractedEnd : null,
              }
            : null,
        );
      };
      // Rozbieżność → PYTAMY (ticket §5). W widoku jednoosobowym odczyt
      // nadpisuje bez pytania — to dwa różne scenariusze, nie niespójność.
      const found = findConflicts([
        {
          key: "start_date",
          label: "Start",
          current: currentForm.startDate,
          incoming: extractedStart,
        },
        {
          key: "end_date",
          label: "Koniec",
          current: currentForm.endDate,
          incoming: extractedEnd,
        },
        ...(explicitUnitMismatch
          ? []
          : [
              {
                key: "rate_client" as const,
                label: "Stawka przychodowa",
                current: currentForm.rateRevenue,
                incoming: extractedRate,
              },
              {
                key: "rate_unit" as const,
                label: "Jednostka stawki przychodowej",
                current:
                  currentForm.rateRevenue.trim() && extractedRate != null
                    ? rateUnitLabel(currentForm.revenueUnit, "PLN")
                    : "",
                incoming:
                  extractedRate != null && extractedRateUnit != null
                    ? rateUnitLabel(extractedRateUnit, "PLN")
                    : null,
              },
            ]),
        ...(costBased || sharedMdBased
          ? []
          : [
              {
                key: "md_total" as const,
                label: "Liczba MD",
                current:
                  currentForm.inputMode === "md" ? currentForm.inputValue : "",
                incoming: numberToField(data.md_total) || null,
              },
            ]),
      ]);
      if (
        !costBased &&
        !sharedMdBased &&
        extractedMd != null &&
        currentForm.inputValue.trim() &&
        currentForm.inputMode !== "md"
      ) {
        found.push({
          key: "md_input_mode",
          label: "Budżet konsultanta",
          current: `${currentForm.inputValue} zł (kwota zamówienia)`,
          incoming: `${extractedMd} MD (liczba MD)`,
        });
      }
      const reasons = [...(data.uncertain_reasons ?? [])];
      if (invalidRateUnit) {
        reasons.push(
          "Nie znaleziono jednostki stawki przychodowej — wpisz ją ręcznie",
        );
      }
      setConsultantRef(data.consultant_ref ?? null);
      setCheckData(Boolean(data.uncertain) || invalidRateUnit);
      setCheckReasons(reasons);
      if (found.length > 0) {
        setConflicts(found);
        setPendingApply(() => apply);
      } else {
        apply();
      }
    } catch (err: unknown) {
      if (extractionEpochRef.current === requestEpoch) {
        setExtractError(
          isIncompleteProfileNameError(err)
            ? INCOMPLETE_PROFILE_NAME_MESSAGE
            : extractionErrorMessage(
                err,
                "Nie udało się odczytać danych z dokumentu.",
              ),
        );
      }
    } finally {
      if (extractionEpochRef.current === requestEpoch) setExtracting(false);
    }
  }

  // Podgląd MD liczony na żywo — operator widzi, ile MD kupuje za wpisaną
  // kwotę, ZANIM zapisze. Bez tego tryb „kwota" jest zapisem w ciemno.
  const previewMd = useMemo(() => {
    const value = parseDecimalInput(inputValue);
    const revenue = parseDecimalInput(rateRevenue);
    // Kwota zamówienia ÷ stawka za 1 MD. Dzielnikiem MUSI być stawka w zł/MD,
    // a nie liczba wpisana w polu: przy jednostce „zł/h" dzielenie przez nią
    // dałoby podgląd ośmiokrotnie za duży wobec tego, co zaraz się zapisze.
    const rate = revenue === null ? null : toMdRate(revenue, revenueUnit);
    if (value === null) return null;
    if (inputMode === "md") return value;
    if (revenueCurrency !== "PLN") return null;
    if (rate === null || rate <= 0) return null;
    return value / rate;
  }, [inputValue, rateRevenue, revenueUnit, inputMode, revenueCurrency]);

  const canSubmit =
    !submitting &&
    (editing || person !== null) &&
    parseDecimalInput(rateCost) !== null &&
    (parseDecimalInput(rateRevenue) ?? 0) > 0 &&
    (costBased || sharedMdBased || parseDecimalInput(inputValue) !== null) &&
    startDate !== "";

  const submit = () => {
    if (!canSubmit) return;
    // Wartości liczbowe wyprowadzone RAZ i sprawdzone, zamiast `as number`
    // w ładunku. Rzutowanie ukrywało przed kompilatorem, że
    // `parseDecimalInput` zwraca `number | null`, a `toMdRate(null, …)` też
    // oddaje `null` — pusta stawka jechała wtedy do API jako
    // `rate_cost: null`. W praktyce zasłaniał to `canSubmit`, ale bramka
    // i ładunek to dwa różne miejsca: rozjazd między nimi byłby cichy.
    const costMd = toMdRate(
      parseDecimalInput(rateCost) ?? Number.NaN,
      costUnit,
    );
    const revenueMd = toMdRate(
      parseDecimalInput(rateRevenue) ?? Number.NaN,
      revenueUnit,
    );
    const budgetValue = parseDecimalInput(inputValue);
    if (costMd === null || revenueMd === null) return;
    if (!costBased && !sharedMdBased && budgetValue === null) return;
    onSubmit({
      // Edycja nie zmienia osoby, więc linia zostaje przy swoim kontrakcie.
      // Dodanie wysyła DOKŁADNIE JEDNO pole — dwa naraz serwer odrzuca, żeby
      // nie musiał zgadywać, kogo operator naprawdę wskazał.
      ...(editing
        ? { contract_id: line?.contract_id }
        : person?.contract_id != null
          ? { contract_id: person.contract_id }
          : { candidate_id: person?.candidate_id }),
      // ZAWSZE zł/MD — jednostka rozliczeniowa modułu. Przełącznik zmienia
      // tylko to, w czym operator wpisuje.
      rate_candidate_currency: costCurrency,
      rate_client_currency: revenueCurrency,
      rate_cost: costMd,
      rate_revenue: revenueMd,
      ...(costBased || sharedMdBased
        ? {}
        : { input_mode: inputMode, input_value: budgetValue as number }),
      start_date: startDate,
      end_date: endDate || null,
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={
        editing ? "Edytuj linię konsultanta" : "Dodaj konsultanta do zamówienia"
      }
      description={group ? `Zamówienie nr ${group.order_number}` : undefined}
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
              onChange={handlePersonChange}
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
              {costCurrency === "PLN"
                ? "Stawka kosztowa *"
                : `Stawka kosztowa (${costCurrency}) *`}
            </label>
            <input
              id="line-cost"
              inputMode="decimal"
              value={rateCost}
              onChange={(e) => setRateCost(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
              placeholder={
                costUnit === "hour"
                  ? "125"
                  : costUnit === "month"
                    ? "10000"
                    : "1000"
              }
            />
            <OrderCurrencySelect
              value={costCurrency}
              onChange={setCostCurrency}
              label="Waluta stawki kosztowej"
            />
            <RateUnitToggle
              id="line-cost-unit"
              unit={costUnit}
              onUnitChange={setCostUnit}
              value={rateCost}
              onValueChange={setRateCost}
              units={COST_RATE_UNITS}
              currency={costCurrency}
              ariaLabel="Jednostka stawki kosztowej"
            />
            {costUnit !== "md" ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Zapis w {costCurrency}/MD:{" "}
                {toMdRate(parseDecimalInput(rateCost) ?? 0, costUnit)}{" "}
                {costCurrency === "PLN" ? "zł" : costCurrency}
              </p>
            ) : null}
            {/* Obie flagi wracają z backendu NIEZALEŻNIE od siebie:
                podpowiedź liczy się wyłącznie z kontraktu `active`/`ending`,
                a ostrzeżenie porównuje WSZYSTKIE nieanulowane, także `ended`
                i `draft`. Konsultant wracający do klienta (stary `ended` +
                nowy `draft`, zero żywych) daje więc `has_different = true`
                przy `suggested_rate_cost = null`. Jeden wspólny komunikat
                twierdził wtedy, że stawkę wstawiono z aktywnego kontraktu —
                pod PUSTYM polem i bez żadnego aktywnego kontraktu. */}
            {person?.has_different_client_contract_rates ? (
              <p
                role="status"
                className="mt-2 flex items-start gap-1.5 text-xs text-amber-700"
              >
                <AlertTriangle
                  className="mt-0.5 h-3.5 w-3.5 shrink-0"
                  aria-hidden="true"
                />
                {person.suggested_contract_rate_cost != null ||
                person.suggested_rate_cost != null ? (
                  <>
                    Uwaga: ten konsultant ma u klienta kontrakty z różnymi
                    stawkami. Wstawiono stawkę z aktywnego kontraktu —
                    sprawdź, którą zastosować.
                  </>
                ) : (
                  <>
                    Uwaga: ten konsultant ma u klienta kontrakty z różnymi
                    stawkami, ale żaden nie jest aktywny — wpisz stawkę dla
                    tej linii.
                  </>
                )}
              </p>
            ) : null}
          </div>
          <div>
            <label htmlFor="line-revenue" className={labelClass}>
              Stawka przychodowa *
            </label>
            <input
              id="line-revenue"
              inputMode="decimal"
              value={rateRevenue}
              onChange={(e) => setRateRevenue(sanitizeDecimalInput(e.target.value))}
              className={inputClass}
              placeholder={revenueUnit === "hour" ? "150" : "1200"}
            />
            <OrderCurrencySelect
              value={revenueCurrency}
              onChange={setRevenueCurrency}
              label="Waluta stawki przychodowej"
            />
            <RateUnitToggle
              id="line-revenue-unit"
              unit={revenueUnit}
              onUnitChange={setRevenueUnit}
              value={rateRevenue}
              onValueChange={setRateRevenue}
              units={REVENUE_RATE_UNITS}
              currency={revenueCurrency}
              ariaLabel="Jednostka stawki przychodowej"
            />
            {grossConversion ? (
              <p role="status" className="mt-1 text-xs text-primary">
                Z dokumentu: {grossConversion.gross} PLN/h brutto →{" "}
                {grossConversion.net} PLN/h netto (brutto ÷ 1,23)
              </p>
            ) : null}
          </div>
        </div>

        {costBased || sharedMdBased ? (
          /* Wspólna pula mieszka na grupie, więc linia nie może dostać
             drugiego, niezależnego budżetu. */
          <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {costBased
              ? "To zamówienie jest rozliczane kwotą wspólną dla wszystkich konsultantów — budżet MD przy osobie nie występuje. Faktury schodzą z kwoty zamówienia przy imporcie z Finansów."
              : "To zamówienie ma wspólną pulę MD dla wszystkich konsultantów — osobny budżet MD przy osobie nie występuje."}
          </p>
        ) : (
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
            {inputMode === "amount" && revenueCurrency !== "PLN"
              ? `Budżet MD zostanie obliczony po zapisaniu według kursu ${revenueCurrency}/PLN.`
              : inputMode === "amount"
              ? `Budżet MD: ${previewMd === null ? "—" : formatMd(previewMd)} MD (kwota ÷ stawka przychodowa)`
              : `Budżet MD: ${previewMd === null ? "—" : formatMd(previewMd)} MD`}
          </p>
        </fieldset>
        )}

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

        {unitChangeNotice ? (
          <div
            role="status"
            className="rounded-md border border-primary/30 bg-primary/5 p-3 text-sm text-foreground"
          >
            {unitChangeNotice}
          </div>
        ) : null}

        {consultantRef !== null ? (
          <p
            role="status"
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground"
          >
            Numer ID konsultanta z dokumentu:{" "}
            <span className="font-semibold">{consultantRef}</span> — potwierdź,
            że dokument dotyczy tej osoby.
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
          <p className={labelClass}>PDF zamówienia od klienta</p>
          <FileDropZone
            inputId="line-po"
            file={file}
            onPick={(picked) => {
              // Nowy plik unieważnia request i tylko wartości, które nadal są
              // wynikiem poprzedniego PDF. Ręczne poprawki pozostają.
              extractionEpochRef.current += 1;
              setExtracting(false);
              clearAutoExtractedValues(true);
              setFile(picked);
              setFileError(null);
              setExtractError(null);
              setCheckData(false);
              setCheckReasons([]);
              setConsultantRef(null);
              setUnitChangeNotice(null);
              setGrossConversion(null);
              setConflicts([]);
              setPendingApply(null);
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
            disabled={
              !file ||
              extracting ||
              targetCandidateId == null ||
              profileNameMessage !== null
            }
            className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-orange-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <FileSearch className="h-4 w-4" aria-hidden />
            {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
          </button>
          {targetCandidateId == null ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Najpierw wybierz konsultanta, którego dane mają zostać odczytane.
            </p>
          ) : profileNameMessage ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {profileNameMessage}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-muted-foreground">
            Odczytuje datę zamówienia, liczbę MD i stawkę przychodową. Przy
            rozbieżności z danymi wpisanymi ręcznie zapyta o potwierdzenie.
          </p>
        </div>

        {editing && onAdjustRemaining && !costBased && !sharedMdBased ? (
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
