"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileSearch } from "lucide-react";

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
import {
  contractRateUnitToInputUnit,
  convertRate,
  rateUnitLabel,
  toMdRate,
  toPlnMdRate,
  type RateUnit,
} from "@/lib/rate-unit";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { ConsultantPicker } from "./ConsultantPicker";
import { ExtractionConflictDialog } from "./ExtractionConflictDialog";
import { formatMd } from "./MdBudgetBar";

/** Ten sam limit i te same rozszerzenia co na endpointach zamówień. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.doc";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass =
  "mb-1 block text-xs font-semibold text-muted-foreground";
const COST_RATE_UNITS: readonly RateUnit[] = ["hour", "md", "month"];
const REVENUE_RATE_UNITS: readonly RateUnit[] = ["hour", "md"];

export interface LineFormValues {
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
  // Wartość ZAPISYWANA jest zawsze w PLN/MD — przełącznik i waluta dotyczą
  // wyłącznie tego, co operator widzi i wpisuje.
  const [costUnit, setCostUnit] = useState<RateUnit>("md");
  const [costCurrency, setCostCurrency] = useState("PLN");
  const [costRateToPln, setCostRateToPln] = useState(1);
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
  const sharedMdBased = Boolean(group?.is_md_budget_based);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  const [conflicts, setConflicts] = useState<ExtractionConflict[]>([]);
  const [pendingApply, setPendingApply] = useState<null | (() => void)>(null);

  const handlePersonChange = (next: ConsultantOption | null) => {
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
    if (!open) return;
    setPerson(null);
    setRateCost(line?.rate_cost != null ? String(line.rate_cost) : "");
    setRateRevenue(line?.rate_revenue != null ? String(line.rate_revenue) : "");
    // Wartości z API są w zł/MD, więc formularz otwiera się w tej jednostce —
    // inaczej pierwszy render pokazywałby liczbę ośmiokrotnie za dużą pod
    // etykietą „zł/h”.
    setCostUnit("md");
    setCostCurrency("PLN");
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
    setConflicts([]);
    setPendingApply(null);
  }, [open, line, group]);

  async function handleExtract() {
    if (!file || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(clientId, file);
      const apply = () => {
        if (data.start_date) setStartDate(data.start_date.slice(0, 10));
        if (data.end_date) setEndDate(data.end_date.slice(0, 10));
        if (data.rate_client != null) {
          // Odczyt z PDF wraca w zł/MD dla klientów MD (patrz polityki
          // klientowe w `order_pdf_parser`) — wstawiamy razem z jednostką.
          setRevenueUnit("md");
          setRateRevenue(String(data.rate_client));
        }
        if (!costBased && !sharedMdBased && data.md_total != null) {
          setInputMode("md");
          setInputValue(String(data.md_total));
        }
      };
      // Rozbieżność → PYTAMY (ticket §5). W widoku jednoosobowym odczyt
      // nadpisuje bez pytania — to dwa różne scenariusze, nie niespójność.
      const found = findConflicts([
        {
          key: "start_date",
          label: "Start",
          current: startDate,
          incoming: data.start_date ? data.start_date.slice(0, 10) : null,
        },
        {
          key: "end_date",
          label: "Koniec",
          current: endDate,
          incoming: data.end_date ? data.end_date.slice(0, 10) : null,
        },
        {
          key: "rate_client",
          label: "Stawka przychodowa",
          current: rateRevenue,
          incoming: numberToField(data.rate_client) || null,
        },
        ...(costBased || sharedMdBased
          ? []
          : [
              {
                key: "md_total" as const,
                label: "Liczba MD",
                current: inputMode === "md" ? inputValue : "",
                incoming: numberToField(data.md_total) || null,
              },
            ]),
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
    if (rate === null || rate <= 0) return null;
    return value / rate;
  }, [inputValue, rateRevenue, revenueUnit, inputMode]);

  // Kwota, która NAPRAWDĘ pójdzie do bazy — pokazywana przy każdej konwersji
  // jednostki lub waluty. Bez tego formularz prosiłby o zaufanie zamiast
  // pokazać wynik finansowy przed zapisem.
  const rateCostAsPlnMd = useMemo(() => {
    const parsed = parseDecimalInput(rateCost);
    return parsed === null
      ? null
      : toPlnMdRate(parsed, costUnit, costRateToPln);
  }, [rateCost, costUnit, costRateToPln]);
  const costNeedsConversion =
    costUnit !== "md" || costCurrency !== "PLN" || costRateToPln !== 1;
  const rateRevenueAsMd = useMemo(() => {
    const parsed = parseDecimalInput(rateRevenue);
    return parsed === null ? null : toMdRate(parsed, revenueUnit);
  }, [rateRevenue, revenueUnit]);

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
    const costMd = toPlnMdRate(
      parseDecimalInput(rateCost) ?? Number.NaN,
      costUnit,
      costRateToPln,
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
            {costNeedsConversion ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Zapis w PLN/MD:{" "}
                {rateCostAsPlnMd === null ? "—" : `${rateCostAsPlnMd} zł`}
                {costCurrency !== "PLN"
                  ? ` (kurs ${costCurrency}→PLN: ${costRateToPln})`
                  : null}
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
            <RateUnitToggle
              id="line-revenue-unit"
              unit={revenueUnit}
              onUnitChange={setRevenueUnit}
              value={rateRevenue}
              onValueChange={setRateRevenue}
              units={REVENUE_RATE_UNITS}
              currency="PLN"
              ariaLabel="Jednostka stawki przychodowej"
            />
            {revenueUnit === "hour" ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Zapis w zł/MD:{" "}
                {rateRevenueAsMd === null ? "—" : `${rateRevenueAsMd} zł`}
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
            {inputMode === "amount"
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
              // Dodanie pliku NIE zmienia żadnego pola — odczyt jest osobną,
              // świadomą akcją użytkownika.
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
          <p className="mt-1 text-xs text-muted-foreground">
            Odczytuje datę zamówienia, liczbę MD i stawkę przychodową. Przy
            rozbieżności z danymi wpisanymi ręcznie zapyta o potwierdzenie.
          </p>
        </div>

        {editing && onAdjustRemaining && !sharedMdBased ? (
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
