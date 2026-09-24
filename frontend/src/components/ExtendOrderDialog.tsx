"use client";

import { ExtractedConsultants, type ExtractedConsultantRows } from "@/components/orders/ExtractedConsultants";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Trash2 } from "lucide-react";
import { FileDropZone } from "@/components/ds/FileDropZone";
import {
  OrderCurrencySelect,
  OrderRateUnitToggle,
  convertRateInput,
  extractionRateUnit,
  normalizeOrderCurrency,
  rateUnitNoticeLabel,
} from "@/components/orders/OrderRateUnitToggle";
import { useToast } from "@/components/Toast";
import { extractErrorMsg } from "@/lib/api";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  ContractWithOrdersRead,
  OrderRateUnit,
  OrderExtractionResult,
} from "@/lib/api/dlPortal";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import {
  executiveContractOptionLabel,
  useExecutiveContractOptions,
} from "@/lib/api/executiveContracts";
import { isEzdrowieClient } from "@/lib/ezdrowie";
import { extractionErrorMessage, numberToField } from "@/lib/order-extraction";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { HOURS_PER_MONTH } from "@/lib/work-time";
import {
  canManageCandidateFinance,
  useAuthStore,
} from "@/store/auth";

interface ExtendOrderDialogProps {
  clientId: number;
  contract: ContractWithOrdersRead;
  canManageFinance?: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}

/** Flow A — "Dodaj przedłużenie": tworzy Order pod istniejącym Contract. */
export function ExtendOrderDialog({
  clientId,
  contract,
  canManageFinance: serverCanManageFinance,
  onClose,
  onCreated,
}: ExtendOrderDialogProps) {
  const { showToast } = useToast();
  const user = useAuthStore((state) => state.user);
  const canManageFinance =
    serverCanManageFinance ?? canManageCandidateFinance(user);
  // Lista jest posortowana malejąco po starcie; anulowane zamówienie nie może
  // podpowiadać startu ani stawek przedłużenia (N3, audyt 24.09.2026).
  const latest =
    contract.orders.find((order) => order.status !== "cancelled") ??
    contract.orders[0];
  const rateBillingHours =
    latest?.billing_hours_per_month ??
    contract.billing_hours_per_month ??
    HOURS_PER_MONTH;

  // Bez autofillu: ta wartość ląduje na karcie jako „Numer zamówienia", więc
  // podpowiedź „Przedłużenie <imię>" wpisywała tam nazwisko zamiast numeru
  // z dokumentu klienta — i zostawała tam, bo nikt nie poprawia pola, które
  // wygląda na wypełnione.
  const [title, setTitle] = useState("");
  const [startDate, setStartDate] = useState(
    latest?.end_date
      ? // start dzień po końcu poprzedniego
        new Date(new Date(latest.end_date).getTime() + 86400000)
          .toISOString()
          .slice(0, 10)
      : "",
  );
  const [endDate, setEndDate] = useState("");
  const [rateClient, setRateClient] = useState(
    canManageFinance
      ? String(latest?.rate_client ?? contract.latest_order_rate_client ?? "")
      : "",
  );
  const [rateCandidate, setRateCandidate] = useState(
    canManageFinance
      ? String(latest?.rate_candidate ?? contract.rate_candidate ?? "")
      : "",
  );
  // Przedłużenie dziedziczy jednostkę z ostatniego zamówienia / kontraktu
  // (razem z przeliczonymi pod nią kwotami) — nie flipujemy jej na domyślną
  // jednostkę klienta, bo rozjechałaby się z dziedziczonymi kwotami.
  const [rateUnit, setRateUnit] = useState<OrderRateUnit>(
    latest?.rate_unit ?? contract.rate_unit ?? "monthly",
  );
  const [rateClientCurrency, setRateClientCurrency] = useState(
    normalizeOrderCurrency(
      latest?.rate_client_currency,
      latest?.currency,
      contract.rate_client_currency,
      contract.currency,
    ),
  );
  const [rateCandidateCurrency, setRateCandidateCurrency] = useState(
    normalizeOrderCurrency(
      latest?.rate_candidate_currency,
      contract.rate_candidate_currency,
      contract.rate_client_currency,
      contract.currency,
    ),
  );
  const [totalValue, setTotalValue] = useState("");
  const [jobId, setJobId] = useState(
    String(latest?.job_id ?? contract.initial_job_id ?? ""),
  );
  // „Umowa wykonawcza" — tylko Centrum e-Zdrowia. Przedłużenie DZIEDZICZY
  // umowę z najnowszego zamówienia (edytowalne — zmiana umowy wykonawczej
  // przy przedłużeniu to legalny scenariusz). Część jest wartością pochodną.
  const ezdrowie = isEzdrowieClient(clientId);
  const [executiveContractId, setExecutiveContractId] = useState<string>(
    latest?.executive_contract_id != null ? String(latest.executive_contract_id) : "",
  );
  // Dziedziczona umowa zostaje w opcjach także po zakończeniu — inaczej
  // select startowałby od „— wybierz —" mimo przypisania na ostatnim zamówieniu.
  const executiveContracts = useExecutiveContractOptions(
    clientId,
    latest?.executive_contract_id ?? null,
  );
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  // Odczyt PDF ("Zczytaj dane z dokumentu") — świadoma akcja, ODDZIELONA od
  // dodania pliku. Dodanie pliku samo w sobie NIC nie zmienia w formularzu.
  const [extracting, setExtracting] = useState(false);
  // Baner „Sprawdź dane!" — pokazywany gdy odczyt był niepewny (uncertain).
  const [extractedRows, setExtractedRows] = useState<ExtractedConsultantRows>([]);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  // Polityka klientowa (Bank Pocztowy) nie znalazła numeru w dokumencie —
  // komunikat „Sprawdź numer zamówienia" przy polu numeru, dopóki puste.
  const [titleCheck, setTitleCheck] = useState(false);
  // Oryginalna stawka za 1 MD z dokumentu (Bank Pocztowy) — pokazywana obok
  // pola stawki; samo pole niesie już wartość przeliczoną na zł/h (MD ÷ 8).
  const [rateMdOriginal, setRateMdOriginal] = useState<string | null>(null);
  // Numer ID konsultanta z dokumentu (polityka BNP) — PDF-y tego klienta nie
  // niosą imienia ani nazwiska, więc to jedyny ślad tożsamości w pliku.
  // Pokazywany do wzrokowego potwierdzenia, że dokument dotyczy tej osoby.
  const [consultantRef, setConsultantRef] = useState<string | null>(null);
  const [grossConversion, setGrossConversion] = useState<{
    gross: string;
    net: string;
  } | null>(null);
  const [unitChangeNotice, setUnitChangeNotice] = useState<string | null>(null);

  // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
  const rateClientNum = parseDecimalInput(rateClient);
  const rateCandidateNum = parseDecimalInput(rateCandidate);

  /** Wstawia odczytane pola. Wypełnia tylko te, które dokument dostarczył —
   *  nie kasuje ręcznych wpisów dla pól nieodczytanych. Wszystkie edytowalne. */
  const applyExtraction = (d: OrderExtractionResult) => {
    if (d.title) setTitle(d.title);
    setTitleCheck(Boolean(d.title_needs_review));
    if (d.start_date) setStartDate(normalizeDateInput(d.start_date));
    if (d.end_date) setEndDate(normalizeDateInput(d.end_date));
    if (canManageFinance) {
      const detectedUnit = extractionRateUnit(d.rate_unit);
      if (detectedUnit && detectedUnit !== rateUnit) {
        setRateCandidate(
          convertRateInput(
            rateCandidate,
            rateUnit,
            detectedUnit,
            rateBillingHours,
          ),
        );
        setRateClient(
          convertRateInput(
            rateClient,
            rateUnit,
            detectedUnit,
            rateBillingHours,
          ),
        );
        setRateUnit(detectedUnit);
        setUnitChangeNotice(
          `Jednostkę stawki zmieniono na ${rateUnitNoticeLabel(detectedUnit)} na podstawie odczytanej pozycji`,
        );
      } else {
        setUnitChangeNotice(null);
      }
      // Kwoty finansowe tylko dla ról z manage_finance (backend i tak je redaguje).
      if (d.rate_client != null) setRateClient(numberToField(d.rate_client));
      // Waluta z dokumentu dotyczy przychodu klienta, nie kosztu kontraktora.
      if (d.currency) {
        setRateClientCurrency(normalizeOrderCurrency(d.currency));
      }
      if (d.total_value != null) setTotalValue(numberToField(d.total_value));
      // Bank Pocztowy: pole wyżej dostało stawkę GODZINOWĄ; oryginał MD
      // pokazujemy obok, żeby obie wartości były widoczne przed zapisem.
      setRateMdOriginal(d.rate_client_md != null ? numberToField(d.rate_client_md) : null);
      setGrossConversion(
        d.rate_client_gross != null && d.rate_client != null
          ? {
              gross: numberToField(d.rate_client_gross),
              net: numberToField(d.rate_client),
            }
          : null,
      );
    }
    // `md_total` z odczytu jest tu świadomie POMIJANE: ten formularz obsługuje
    // wyłącznie klientów rozliczanych jednoosobowo, u których zamówienie nie ma
    // budżetu MD. Klienci MD (BIK/Polkomtel/BNP) mają własny widok i własne
    // „Dodaj przedłużenie" (`ExtendOrderGroupModal`), gdzie liczba MD trafia
    // na linię konsultanta. Pole tutaj nie miałoby gdzie się zapisać.
    // Poza blokiem `canManageFinance` — numer ID nie jest kwotą.
    setConsultantRef(d.consultant_ref ?? null);
    setExtractedRows(d.client_policy === "Nordea" ? (d.consultant_rows ?? []) : []);
    setCheckData(Boolean(d.uncertain));
    setCheckReasons(d.uncertain_reasons ?? []);
  };

  const handleExtract = async () => {
    if (!file || extracting) return;
    setExtracting(true);
    try {
      const res = await dlPortalApi.extractOrderPdf(
        clientId,
        file,
        contract.candidate_id,
      );
      applyExtraction(res.data);
      showToast("Odczytano dane z dokumentu", "success");
    } catch (err: unknown) {
      showToast(extractionErrorMessage(err, extractErrorMsg(err)), "error");
    } finally {
      setExtracting(false);
    }
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("contract_id", String(contract.contract_id));
      fd.append("title", title);
      fd.append("order_status", "active");
      // Normalizacja EU→ISO także tutaj — submit przez Enter nie odpala onBlur,
      // więc surowe „1.6.2026" trafiłoby do backendu jako 422.
      if (startDate) fd.append("start_date", normalizeDateInput(startDate));
      if (endDate) fd.append("end_date", normalizeDateInput(endDate));
      if (canManageFinance) {
        // Candidate-bearing order finance is Admin-only. Operational callers
        // omit amounts entirely instead of sending redacted/default values.
        if (rateClientNum !== null) fd.append("rate_client", String(rateClientNum));
        if (rateCandidateNum !== null) {
          fd.append("rate_candidate", String(rateCandidateNum));
        }
        fd.append("rate_unit", rateUnit);
        fd.append("billing_hours_per_month", String(rateBillingHours));
        fd.append("rate_client_currency", rateClientCurrency);
        fd.append("rate_candidate_currency", rateCandidateCurrency);
        const totalValueNum = parseDecimalInput(totalValue);
        if (totalValueNum !== null) fd.append("total_value", String(totalValueNum));
      }
      if (jobId) fd.append("job_id", jobId);
      if (ezdrowie && executiveContractId) {
        fd.append("executive_contract_id", executiveContractId);
      }
      if (file) fd.append("file", file);
      return dlPortalApi.createOrderExtension(clientId, fd);
    },
    onSuccess: async () => {
      await onCreated();
      showToast("Przedłużenie dodane", "success");
    },
    onError: (err: unknown) => {
      showToast(err instanceof Error ? err.message : "Błąd zapisu", "error");
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (ezdrowie && !executiveContractId) {
            showToast("Wybierz umowę wykonawczą", "error");
            return;
          }
          mutation.mutate();
        }}
        className="bg-card rounded-lg shadow-xl max-w-md w-full p-6 flex max-h-[90dvh] flex-col gap-3"
      >
        {/* Treść przewija się w środku, przyciski zostają widoczne (dvh:
            na iOS `vh` liczy duży wiewport i stopka chowała się pod paskiem). */}
        <div className="-mx-1 min-h-0 flex-1 space-y-3 overflow-y-auto px-1">
          <div>
            <h3 className="text-lg font-semibold">Nowe zamówienie / przedłużenie</h3>
            <p className="text-xs text-muted-foreground mt-1">
              Dla: <strong>{contract.candidate_name}</strong> · Contract #{contract.contract_id}
            </p>
          </div>

          {/* Baner „Sprawdź dane!" — nad tytułem zamówienia, gdy odczyt niepewny. */}
          <ExtractedConsultants rows={extractedRows} />
            {checkData && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 px-3 py-2 text-orange-800 dark:border-orange-800 dark:bg-orange-950/40 dark:text-orange-200"
            >
              <AlertTriangle
                className="w-5 h-5 shrink-0 mt-0.5 text-orange-500"
                aria-hidden
              />
              <div className="text-sm">
                <span className="font-bold">Sprawdź dane!</span>
                {checkReasons.length > 0 && (
                  <ul className="mt-1 list-disc list-inside text-xs text-orange-700 dark:text-orange-300 space-y-0.5">
                    {checkReasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {consultantRef !== null && (
            <p
              role="status"
              className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground"
            >
              Numer ID konsultanta z dokumentu:{" "}
              <span className="font-semibold">{consultantRef}</span> — potwierdź,
              że dokument dotyczy tej osoby.
            </p>
          )}

          <label className="block">
            <span className="text-sm">Numer zamówienia</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="np. 45767"
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
            {/* Polityka klientowa nie znalazła numeru — komunikat znika, gdy
                użytkownik wpisze numer ręcznie (przestaje być aktualny). */}
            {titleCheck && !title.trim() && (
              <span className="text-xs text-destructive mt-0.5 block">
                Sprawdź numer zamówienia
              </span>
            )}
          </label>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label>
              <span className="text-sm">
                Start <span className="text-destructive">*</span>
              </span>
              <input
                type="text"
                inputMode="numeric"
                pattern={DATE_PATTERN}
                placeholder={DATE_PLACEHOLDER}
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                onBlur={(e) => setStartDate(normalizeDateInput(e.target.value))}
                // WYMAGANE, bo bez daty startu przedłużenie jest klasyfikowane
                // jako ROZPOCZĘTE (`splitOrders` traktuje NULL jak przeszłość,
                // a backend sortuje NULL na koniec) i wpada do zwiniętej
                // „Historii zamówień" zamiast do „Przyszłego zamówienia".
                // Użytkownik zgłasza to jako „zamówienie zniknęło".
                required
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              />
            </label>
            <label>
              <span className="text-sm">Koniec</span>
              <input
                type="text"
                inputMode="numeric"
                pattern={DATE_PATTERN}
                placeholder={DATE_PLACEHOLDER}
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                onBlur={(e) => setEndDate(normalizeDateInput(e.target.value))}
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              />
            </label>
          </div>

          {canManageFinance && (
            <div className="space-y-3 rounded-md border border-border bg-muted/20 p-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label>
                  <span className="text-sm">Stawka przychodowa (klient)</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={rateClient}
                    onChange={(e) =>
                      setRateClient(sanitizeDecimalInput(e.target.value))
                    }
                    className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                    placeholder="np. 17000"
                  />
                  {/* Bank Pocztowy: dokument podaje stawkę za 1 MD (8 h) — pole
                      wyżej ma już przeliczoną stawkę godzinową (edytowalną),
                      a oryginał z dokumentu zostaje widoczny obok. */}
                  {rateMdOriginal !== null && (
                    <span className="text-xs text-muted-foreground mt-0.5 block">
                      Z dokumentu: {rateMdOriginal} {rateClientCurrency}/MD →
                      przeliczono na stawkę godzinową (÷ 8, w górę do 2 miejsc)
                    </span>
                  )}
                  {grossConversion !== null && (
                    <span className="text-xs text-muted-foreground mt-0.5 block">
                      Z dokumentu: {grossConversion.gross} {rateClientCurrency}/h
                      brutto → {grossConversion.net} {rateClientCurrency}/h netto
                      (÷ 1,23)
                    </span>
                  )}
                </label>
                <label>
                  <span className="text-sm">Stawka kosztowa (kontraktor)</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={rateCandidate}
                    onChange={(e) =>
                      setRateCandidate(sanitizeDecimalInput(e.target.value))
                    }
                    className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                    placeholder="np. 12000"
                  />
                  {rateCandidateNum !== null &&
                    rateClientNum !== null &&
                    rateCandidateCurrency === rateClientCurrency && (
                    <span className="text-xs text-green-700 mt-0.5 block">
                      marża: {rateClientNum - rateCandidateNum} {rateClientCurrency}
                    </span>
                  )}
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 sm:items-end">
                <div className="sm:col-span-2">
                  <OrderRateUnitToggle
                    value={rateUnit}
                    rateCandidate={rateCandidate}
                    rateClient={rateClient}
                    onValueChange={setRateUnit}
                  onRateCandidateChange={setRateCandidate}
                  onRateClientChange={setRateClient}
                  billingHoursPerMonth={rateBillingHours}
                />
                </div>
                <OrderCurrencySelect
                  value={rateClientCurrency}
                  onChange={setRateClientCurrency}
                />
                <OrderCurrencySelect
                  value={rateCandidateCurrency}
                  onChange={setRateCandidateCurrency}
                  label="Waluta stawki kosztowej"
                  ariaLabel="Waluta stawki kosztowej"
                />
              </div>
              {rateClientNum !== null &&
                rateCandidateNum !== null &&
                rateClientCurrency !== rateCandidateCurrency && (
                  <p className="text-xs text-muted-foreground">
                    Marża zostanie pokazana po niezależnym przeliczeniu obu stawek
                    do PLN.
                  </p>
                )}
              {unitChangeNotice ? (
                <p role="status" className="text-xs text-primary">
                  {unitChangeNotice}
                </p>
              ) : null}
              <label className="block">
                <span className="text-sm">Total value (opcjonalnie)</span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={totalValue}
                  onChange={(e) =>
                    setTotalValue(sanitizeDecimalInput(e.target.value))
                  }
                  className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                />
              </label>
            </div>
          )}

          <label className="block">
            <span className="text-sm">Job ID (rekrutacja, z której przedłużenie)</span>
            <input
              type="number"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              placeholder={contract.initial_job_id?.toString() ?? "—"}
            />
          </label>

          {/* „Umowa wykonawcza" — tylko Centrum e-Zdrowia. */}
          {ezdrowie && (
            <label className="block">
              <span className="text-sm">Umowa wykonawcza *</span>
              <select
                value={executiveContractId}
                onChange={(e) => setExecutiveContractId(e.target.value)}
                aria-label="Umowa wykonawcza"
                className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
              >
                <option value="">— wybierz —</option>
                {executiveContracts.groups.map((group) => (
                  <optgroup key={group.framework_contract_id} label={group.label}>
                    {group.options.map((ec) => (
                      <option key={ec.id} value={String(ec.id)}>
                        {executiveContractOptionLabel(ec)}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {executiveContracts.isSuccess && executiveContracts.groups.length === 0 ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Dodaj umowę wykonawczą w sekcji Struktura umów na profilu klienta.
                </p>
              ) : null}
            </label>
          )}

          {/* Kafelek załącznika + przycisk odczytu — na dole formularza. Dodanie
              pliku NIE uruchamia odczytu; to robi dopiero pomarańczowy przycisk. */}
          <div className="pt-1">
            <FileDropZone
              inputId="order-pdf-input"
              file={file}
              onPick={(picked) => {
                // Sam wybór pliku NIC nie zmienia w polach — kasuje tylko baner
                // z poprzedniego odczytu (dotyczył innego pliku).
                setFile(picked);
                setFileError(null);
                setExtractedRows([]);
                setCheckData(false);
                setCheckReasons([]);
                setTitleCheck(false);
                setConsultantRef(null);
                setRateMdOriginal(null);
                setGrossConversion(null);
                setUnitChangeNotice(null);
              }}
              onError={setFileError}
              error={fileError}
              accept=".pdf,.docx,.doc"
              maxBytes={25 * 1024 * 1024}
              label="PDF zamówienia od klienta"
              hint=".pdf / .docx · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={handleExtract}
                disabled={!file || extracting}
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-md bg-orange-500 px-3 py-2 text-sm font-semibold text-white hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
              </button>
              {file ? (
                <button
                  type="button"
                  aria-label="Usuń plik PDF zamówienia"
                  title="Usuń plik"
                  onClick={() => {
                    if (
                      window.confirm(
                        "Czy na pewno chcesz usunąć plik PDF zamówienia?",
                      )
                    ) {
                      setFile(null);
                      setFileError(null);
                      setExtractedRows([]);
                      setCheckData(false);
                      setCheckReasons([]);
                      setTitleCheck(false);
                      setConsultantRef(null);
                      setRateMdOriginal(null);
                      setGrossConversion(null);
                      setUnitChangeNotice(null);
                    }
                  }}
                  className="rounded-md border border-destructive/40 p-2 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </button>
              ) : null}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-sm border border-border rounded"
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {mutation.isPending ? "Zapisywanie…" : "Zapisz przedłużenie"}
          </button>
        </div>
      </form>
    </div>
  );
}
