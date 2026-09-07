"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileSearch, Search } from "lucide-react";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { OrderTypeSwitch } from "@/components/orders/OrderTypeSwitch";
import {
  OrderCurrencySelect,
  OrderRateUnitToggle,
  convertRateInput,
  extractionRateUnit,
} from "@/components/orders/OrderRateUnitToggle";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OrderRateUnit, OrderType } from "@/lib/api/dlPortal";
import api, { extractErrorMsg } from "@/lib/api";
import {
  DATE_PATTERN,
  DATE_PLACEHOLDER,
  normalizeDateInput,
} from "@/lib/dateInput";
import { PROJECT_PARTS, isEzdrowieClient } from "@/lib/ezdrowie";
import { extractionErrorMessage } from "@/lib/order-extraction";
import { parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import {
  canManageCandidateFinance,
  useAuthStore,
} from "@/store/auth";

interface NewContractorOrderDialogProps {
  clientId: number;
  orderType?: OrderType;
  onOrderTypeChange?: (orderType: OrderType) => void;
  allowedOrderTypes?: readonly OrderType[];
  canManageFinance?: boolean;
  /**
   * Jednostka stawki proponowana domyślnie (najczęstsza u tego klienta —
   * `useClientDefaultRateUnit`). Zastępuje twardy `monthly`. `undefined`, dopóki
   * zapytanie się nie rozwiąże — wtedy inicjujemy `monthly` i adoptujemy wartość
   * efektem, gdy dojedzie, o ile użytkownik nie tknął pola.
   */
  defaultRateUnit?: OrderRateUnit | null;
  onClose: () => void;
  onCreated: () => void;
}

interface CandidateSearchItem {
  id: number;
  name: string;
  lastname: string;
  email?: string | null;
  location?: string | null;
  competence_category?: string | null;
}

interface JobListItem {
  id: number;
  title: string;
  status?: string | null;
}

/** Backend trzyma location jako JSON string ({lat, lng, locality, iso, ...}) lub plain string. */
function formatCandidateLocation(loc?: string | null): string | null {
  if (!loc) return null;
  const trimmed = loc.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const locality = parsed.locality ?? parsed.city ?? parsed.region1;
      return typeof locality === "string" && locality ? locality : null;
    } catch {
      return null;
    }
  }
  return trimmed;
}

/** Flow B — "Nowy kontraktor": atomic Contract + Order create. */
export function NewContractorOrderDialog({
  clientId,
  orderType = "periodic",
  onOrderTypeChange,
  allowedOrderTypes,
  canManageFinance: serverCanManageFinance,
  defaultRateUnit,
  onClose,
  onCreated,
}: NewContractorOrderDialogProps) {
  const { showToast, showError } = useToast();
  const user = useAuthStore((state) => state.user);
  const canManageFinance =
    serverCanManageFinance ?? canManageCandidateFinance(user);

  // Candidate typeahead state
  const [candidateQuery, setCandidateQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedCandidate, setSelectedCandidate] =
    useState<CandidateSearchItem | null>(null);

  const [jobId, setJobId] = useState<string>(""); // "" = brak
  const [title, setTitle] = useState("");
  const [contractStart, setContractStart] = useState("");
  const [contractEnd, setContractEnd] = useState("");
  const [orderStart, setOrderStart] = useState("");
  const [orderEnd, setOrderEnd] = useState("");
  const [rateClient, setRateClient] = useState("");
  const [rateCandidate, setRateCandidate] = useState("");
  // Domyślnie jednostka najczęstsza u klienta (nigdy `monthly`), a nie twardy
  // `monthly`. Gdy `defaultRateUnit` jeszcze nie dojechał, startujemy `monthly`
  // i adoptujemy właściwą wartość efektem niżej — o ile pola nie tknięto.
  const [rateUnit, setRateUnit] = useState<OrderRateUnit>(
    defaultRateUnit ?? "monthly",
  );
  // Blokuje adopcję domyślnej jednostki, gdy użytkownik ją wybrał ręcznie lub
  // gdy nadpisał ją odczyt z dokumentu — inaczej późno dojeżdżający default
  // przełączyłby świadomie ustawioną jednostkę (i przeliczone pod nią kwoty).
  const rateUnitTouchedRef = useRef(false);
  const [billingHours, setBillingHours] = useState("160");
  const [rateClientCurrency, setRateClientCurrency] = useState("PLN");
  const [rateCandidateCurrency, setRateCandidateCurrency] = useState("PLN");
  const [notes, setNotes] = useState("");
  // „Część umowy" — pole widoczne i wymagane wyłącznie dla Centrum e-Zdrowia
  // (ticket #3; bramka po client_id, walidacja też serwerowo).
  const ezdrowie = isEzdrowieClient(clientId);
  const [projectPart, setProjectPart] = useState<string>("");

  // ── PDF od klienta + odczyt ────────────────────────────────────────────
  //
  // Odczyt jest tą SAMĄ funkcją i tym samym endpointem co w „Uzupełnij
  // zamówienie" (`dlPortalApi.extractOrderPdf`), więc reguły klientowe
  // (Nordea, Bank Pocztowy, BNP…) obowiązują tu bez żadnej dodatkowej
  // konfiguracji. Klienta NIE czytamy z dokumentu — wynika z profilu, z
  // którego formularz został otwarty.
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [checkData, setCheckData] = useState(false);
  const [checkReasons, setCheckReasons] = useState<string[]>([]);
  // `null` = odczytu jeszcze nie było. Pusty string = odczyt był, ale ten
  // klient nie ma własnych reguł — komunikat mówi to wprost, zamiast zostawiać
  // operatora z przekonaniem, że numer przyszedł z właściwego pola dokumentu.
  const [clientPolicy, setClientPolicy] = useState<string | null>(null);

  // Odczyt jest asynchroniczny, a `applyExtraction` czyta wartości pól, żeby
  // wiedzieć, które są puste. Gdyby brał je z domknięcia handlera, patrzyłby na
  // stan Z CHWILI WGRANIA PLIKU — a użytkownik może pisać w trakcie odczytu
  // i jego tekst zostałby nadpisany „bo pole było puste". Ref niesie stan
  // BIEŻĄCY. Ten sam wzorzec co `extractionFormRef` w `ConsultantLineModal`.
  const formRef = useRef({
    title: "",
    contractStart: "",
    orderStart: "",
    orderEnd: "",
    rateClient: "",
    rateCandidate: "",
    rateUnit: "monthly" as "monthly" | "daily" | "hourly",
    billingHours: "160",
  });
  formRef.current = {
    title,
    contractStart,
    orderStart,
    orderEnd,
    rateClient,
    rateCandidate,
    rateUnit,
    billingHours,
  };

  // Adopcja domyślnej jednostki klienta, gdy dojedzie po zamontowaniu dialogu
  // (zimny cache). Zwykle `defaultRateUnit` jest już w cache (zakładka pobiera
  // go przy montażu), więc `useState` startuje właściwą wartością i ten efekt
  // tylko potwierdza. Nie nadpisuje wyboru użytkownika ani jednostki z odczytu.
  useEffect(() => {
    if (defaultRateUnit && !rateUnitTouchedRef.current) {
      setRateUnit(defaultRateUnit);
    }
  }, [defaultRateUnit]);

  // Dwa szybkie wgrania pliku = dwa równoległe odczyty. Bez licznika epok
  // wolniejsza odpowiedź STARSZEGO pliku wygrywałaby z nowszą — do formularza
  // trafiłyby dane z dokumentu, którego już nie ma w polu wyboru.
  const extractionEpochRef = useRef(0);

  function resetExtraction() {
    setCheckData(false);
    setCheckReasons([]);
    setClientPolicy(null);
  }

  /** Wypełnia pola z odczytu.
   *
   *  `overwrite=false` (odczyt automatyczny po wgraniu pliku) uzupełnia
   *  WYŁĄCZNIE puste pola — nie kasuje niczego, co operator zdążył wpisać.
   *  `overwrite=true` (przycisk „Zczytaj dane z dokumentu") nadpisuje, bo to
   *  świadoma prośba o ponowny odczyt. Reguła repo „dodanie pliku samo z siebie
   *  nie zmienia pól" broni ręcznej pracy; tutaj formularz startuje pusty, więc
   *  jej sens spełnia wariant „tylko puste pola".
   */
  function applyExtraction(
    data: Awaited<ReturnType<typeof dlPortalApi.extractOrderPdf>>["data"],
    { overwrite }: { overwrite: boolean },
  ) {
    const form = formRef.current;
    const fill = (
      current: string,
      incoming: string | null | undefined,
      setter: (value: string) => void,
    ) => {
      if (incoming == null || incoming === "") return;
      if (!overwrite && current.trim() !== "") return;
      setter(incoming);
    };

    fill(form.title, data.title, setTitle);
    fill(
      form.orderStart,
      data.start_date ? normalizeDateInput(data.start_date) : null,
      setOrderStart,
    );
    fill(
      form.orderEnd,
      data.end_date ? normalizeDateInput(data.end_date) : null,
      setOrderEnd,
    );
    // Kontrakt zaczyna się razem z zamówieniem, dopóki operator nie powie
    // inaczej — to pole jest wymagane, a jego brak blokuje zapis.
    fill(
      form.contractStart,
      data.start_date ? normalizeDateInput(data.start_date) : null,
      setContractStart,
    );
    if (canManageFinance) {
      const detectedUnit = extractionRateUnit(data.rate_unit);
      if (detectedUnit && detectedUnit !== form.rateUnit) {
        // Jednostka z dokumentu przelicza to, co JUŻ jest w polach — inaczej
        // kwota zostałaby przeetykietowana bez konwersji (błąd ×8 / ×22).
        setRateClient(
          convertRateInput(
            form.rateClient,
            form.rateUnit,
            detectedUnit,
            Number(form.billingHours) || 160,
          ),
        );
        setRateCandidate(
          convertRateInput(
            form.rateCandidate,
            form.rateUnit,
            detectedUnit,
            Number(form.billingHours) || 160,
          ),
        );
        // Jednostka z dokumentu to świadomy wybór — nie pozwól, by późno
        // dojeżdżający default klienta ją nadpisał.
        rateUnitTouchedRef.current = true;
        setRateUnit(detectedUnit);
      }
      // Dokument opisuje pozycję PRZYCHODOWĄ klienta. Stawka kosztowa
      // kontraktora nie wynika z niego i zostaje do wpisania ręcznie.
      fill(
        form.rateClient,
        data.rate_client == null ? null : String(data.rate_client),
        setRateClient,
      );
      if (data.currency) setRateClientCurrency(data.currency.toUpperCase());
    }
    setClientPolicy(data.client_policy ?? "");
    setCheckData(Boolean(data.uncertain));
    setCheckReasons(data.uncertain_reasons ?? []);
  }

  async function runExtraction(picked: File, options: { overwrite: boolean }) {
    const epoch = extractionEpochRef.current + 1;
    extractionEpochRef.current = epoch;
    setExtracting(true);
    setFileError(null);
    try {
      const { data } = await dlPortalApi.extractOrderPdf(
        clientId,
        picked,
        selectedCandidate?.id ?? null,
      );
      // Wynik starszego pliku nie może nadpisać nowszego.
      if (extractionEpochRef.current !== epoch) return;
      applyExtraction(data, options);
    } catch (err: unknown) {
      if (extractionEpochRef.current !== epoch) return;
      setFileError(
        extractionErrorMessage(err, "Nie udało się odczytać danych z dokumentu."),
      );
    } finally {
      if (extractionEpochRef.current === epoch) setExtracting(false);
    }
  }

  // Debounce candidate search (300ms — same as AddCandidateToJobModal)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(candidateQuery.trim()), 300);
    return () => clearTimeout(t);
  }, [candidateQuery]);

  const {
    data: candidates = [],
    isFetching: candLoading,
    isError: candError,
    refetch: refetchCandidates,
  } = useQuery<CandidateSearchItem[]>({
    queryKey: ["new-contractor-candidate-search", debouncedQuery],
    queryFn: async () => {
      if (debouncedQuery.length < 2) return [];
      const r = await api.get("/api/candidates", {
        params: { q: debouncedQuery, page_size: 15 },
      });
      const payload = r.data;
      return Array.isArray(payload) ? payload : payload?.items ?? [];
    },
    enabled: !selectedCandidate && debouncedQuery.length >= 2,
  });

  // Jobs of this client (for optional Job picker)
  const { data: clientJobs = [] } = useQuery<JobListItem[]>({
    queryKey: ["new-contractor-client-jobs", clientId],
    queryFn: async () => {
      const r = await api.get("/api/jobs", {
        params: { client_id: clientId, page_size: 100 },
      });
      const payload = r.data;
      return Array.isArray(payload) ? payload : payload?.items ?? [];
    },
  });

  // Autofill USUNIĘTY: ta wartość jest pokazywana na karcie klienta jako
  // „Numer zamówienia", a podpowiedź „Imię Nazwisko — Stanowisko" wpisywała tam
  // nazwisko z tytułem rekrutacji zamiast numeru z dokumentu klienta. Pole
  // wyglądające na wypełnione nie jest poprawiane, więc numer nigdy nie
  // trafiał do systemu.

  // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
  const rateClientNum = parseDecimalInput(rateClient);
  const rateCandidateNum = parseDecimalInput(rateCandidate);
  const rateUnitSuffix =
    rateUnit === "hourly" ? "h" : rateUnit === "daily" ? "MD" : "mc";
  const margin =
    rateClientCurrency === rateCandidateCurrency &&
    rateClientNum !== null &&
    rateCandidateNum !== null
      ? rateClientNum - rateCandidateNum
      : null;

  const mutation = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) {
        throw new Error("Wybierz kandydata");
      }
      const payload: Parameters<
        typeof dlPortalApi.createContractWithOrder
      >[1] = {
        candidate_id: selectedCandidate.id,
        job_id: jobId ? Number(jobId) : null,
        title,
        contract_start_date: contractStart,
        contract_end_date: contractEnd || null,
        order_start_date: orderStart || contractStart,
        order_end_date: orderEnd || null,
        order_type: orderType,
        notes: notes || null,
      };
      if (ezdrowie) {
        payload.project_part = projectPart || null;
      }
      if (canManageFinance) {
        payload.rate_client = rateClientNum ?? undefined;
        payload.rate_candidate = rateCandidateNum ?? undefined;
        payload.rate_unit = rateUnit;
        payload.billing_hours_per_month = Number(billingHours);
        payload.rate_client_currency = rateClientCurrency;
        payload.rate_candidate_currency = rateCandidateCurrency;
      }
      return dlPortalApi.createContractWithOrder(clientId, payload);
    },
    onSuccess: async (res) => {
      const marginSuffix =
        res.data.monthly_margin == null
          ? ""
          : ` (marża ${res.data.monthly_margin}/mc)`;
      // PDF idzie DRUGIM żądaniem, bo `contract-with-order` jest atomowym
      // zapisem JSON. Nieudany upload nie może cofnąć utworzonego kontraktu:
      // mówimy o tym wprost i zostawiamy plik do wgrania w „Uzupełnij
      // zamówienie", zamiast udawać, że nic się nie stało.
      let fileNote = "";
      if (file) {
        try {
          await dlPortalApi.replaceOrderPo(clientId, res.data.order_id, file);
        } catch {
          fileNote = " — PDF NIE został zapisany, wgraj go ponownie";
        }
      }
      showToast(
        `Kontrakt #${res.data.contract_id} + Order #${res.data.order_id} utworzone${marginSuffix}${fileNote}`,
        fileNote ? "error" : "success",
      );
      onCreated();
    },
    onError: (err: unknown) => {
      showError(extractErrorMsg(err));
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (
            !selectedCandidate ||
            !title ||
            !contractStart ||
            (canManageFinance &&
              (rateClientNum === null || rateCandidateNum === null))
          ) {
            showError(
              canManageFinance
                ? "Wypełnij wymagane pola (kandydat, tytuł, daty, stawki)"
                : "Wypełnij wymagane pola (kandydat, tytuł, data rozpoczęcia)",
            );
            return;
          }
          if (ezdrowie && !projectPart) {
            showError("Wybierz część umowy");
            return;
          }
          mutation.mutate();
        }}
        className="bg-card rounded-lg shadow-xl max-w-xl w-full p-6 space-y-3 max-h-[90vh] overflow-auto"
      >
        <div>
          <h3 className="text-lg font-semibold">Nowy kontraktor / zamówienie</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Atomic: tworzy nowy Contract z kandydatem + pierwszy Order pod nim.
          </p>
        </div>

        {onOrderTypeChange ? (
          <OrderTypeSwitch
            value={orderType}
            onChange={onOrderTypeChange}
            allowedTypes={allowedOrderTypes}
          />
        ) : null}

        {/* Candidate picker (typeahead search) */}
        <div>
          <span className="text-sm">Kandydat *</span>
          {selectedCandidate ? (
            <div className="mt-1 flex items-center justify-between gap-3 px-3 py-2 border border-border rounded bg-background">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">
                  {selectedCandidate.name} {selectedCandidate.lastname}{" "}
                  <span className="text-xs text-muted-foreground">
                    #{selectedCandidate.id}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {[
                    selectedCandidate.competence_category,
                    formatCandidateLocation(selectedCandidate.location),
                    selectedCandidate.email,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedCandidate(null);
                  setCandidateQuery("");
                  setDebouncedQuery("");
                }}
                className="text-xs text-muted-foreground hover:text-foreground shrink-0"
              >
                Zmień
              </button>
            </div>
          ) : (
            <>
              <div className="relative mt-1">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
                <input
                  type="text"
                  autoFocus
                  value={candidateQuery}
                  onChange={(e) => setCandidateQuery(e.target.value)}
                  placeholder="Szukaj po imieniu, emailu, skillu..."
                  className="w-full pl-9 pr-3 py-2 border border-border rounded bg-background"
                />
              </div>
              {debouncedQuery.length >= 2 && (
                <div className="mt-1 max-h-48 overflow-y-auto border border-border rounded bg-background">
                  {candLoading ? (
                    <p className="text-xs text-muted-foreground text-center py-3">
                      Szukam…
                    </p>
                  ) : candError ? (
                    /* Awaria zapytania NIE może wyglądać jak „nie ma takiej
                       osoby" — na tej ścieżce zakłada się kontrakt, więc pustka
                       podpowiada, żeby założyć drugi rekord komuś, kto w bazie
                       JEST. Realny przypadek: chwilowy rate limit przy imporcie
                       Nordei ukrył kandydata, którego `/api/candidates` zwraca
                       bez problemu. */
                    <div
                      role="alert"
                      className="px-3 py-3 text-center text-xs text-destructive"
                    >
                      <p>Nie udało się wyszukać kandydatów.</p>
                      <button
                        type="button"
                        onClick={() => refetchCandidates()}
                        className="mt-1 underline hover:no-underline"
                      >
                        Ponów
                      </button>
                    </div>
                  ) : candidates.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-3">
                      Brak wyników dla „{debouncedQuery}".
                    </p>
                  ) : (
                    candidates.map((c) => (
                      <button
                        type="button"
                        key={c.id}
                        onClick={() => {
                          setSelectedCandidate(c);
                          setCandidateQuery("");
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-muted transition-colors border-b border-border last:border-b-0"
                      >
                        <p className="text-sm font-medium truncate">
                          {c.name} {c.lastname}{" "}
                          <span className="text-xs text-muted-foreground">
                            #{c.id}
                          </span>
                        </p>
                        <p className="text-xs text-muted-foreground truncate">
                          {[c.competence_category, formatCandidateLocation(c.location), c.email]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </p>
                      </button>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Job dropdown (jobs of this client) */}
        <label className="block">
          <span className="text-sm">Rekrutacja (opcjonalnie)</span>
          <select
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          >
            <option value="">— brak —</option>
            {clientJobs.map((j) => (
              <option key={j.id} value={String(j.id)}>
                #{j.id} · {j.title}
                {j.status ? ` (${j.status})` : ""}
              </option>
            ))}
          </select>
        </label>

        {/* „Wybór części umowy" — tylko Centrum e-Zdrowia (ticket #3). */}
        {ezdrowie && (
          <label className="block">
            <span className="text-sm">Wybór części umowy *</span>
            <select
              value={projectPart}
              onChange={(e) => setProjectPart(e.target.value)}
              aria-label="Wybór części umowy"
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="">— wybierz —</option>
              {PROJECT_PARTS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            {!projectPart && (
              <p className="mt-1 text-xs text-muted-foreground">
                Pole wymagane dla Centrum e-Zdrowia.
              </p>
            )}
          </label>
        )}

        {/* PDF od klienta — widoczny OD RAZU i dla KAŻDEGO klienta.
            Formularz działa dalej bez pliku: wgranie jest skrótem, nie
            warunkiem. */}
        <div className="space-y-2">
          <FileDropZone
            inputId="new-order-po"
            file={file}
            onPick={(picked) => {
              // Unieważnia odczyt w locie: odpowiedź poprzedniego pliku nie
              // może wpaść do formularza po zmianie wyboru.
              extractionEpochRef.current += 1;
              setExtracting(false);
              setFile(picked);
              setFileError(null);
              resetExtraction();
              // Formularz startuje pusty, więc odczyt po wgraniu wypełnia go
              // od razu — ale WYŁĄCZNIE puste pola (patrz `applyExtraction`).
              if (picked) void runExtraction(picked, { overwrite: false });
            }}
            onError={setFileError}
            error={fileError}
            accept=".pdf,.docx,.doc"
            maxBytes={25 * 1024 * 1024}
            label="PDF zamówienia od klienta"
            hint=".pdf / .docx · przeciągnij plik tutaj lub wybierz z dysku · maks. 25 MB"
          />
          <button
            type="button"
            onClick={() => file && void runExtraction(file, { overwrite: true })}
            disabled={!file || extracting}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-orange-500 px-3 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
          >
            <FileSearch className="h-4 w-4" aria-hidden />
            {extracting ? "Odczytywanie…" : "Zczytaj dane z dokumentu"}
          </button>

          {clientPolicy !== null && (
            <p
              role="status"
              className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-foreground"
            >
              {clientPolicy
                ? `Zastosowano reguły odczytu: ${clientPolicy}.`
                : "Dla tego klienta nie ma jeszcze własnych reguł odczytu PDF — pola wypełnił odczyt ogólny. Sprawdź je przed zapisem."}
            </p>
          )}

          {checkData && (
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
                {checkReasons.length > 0 && (
                  <ul className="mt-1 list-disc pl-4">
                    {checkReasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>

        <label className="block">
          {/* Ta wartość jest wyświetlana na karcie klienta jako „Numer
              zamówienia", więc etykieta musi mówić to samo — rozjazd „Tytuł"
              tutaj vs „Numer" tam kazał zgadywać, że to jedno i to samo pole. */}
          <span className="text-sm">Numer zamówienia *</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. 45767"
          />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Contract start *</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={contractStart}
              onChange={(e) => setContractStart(e.target.value)}
              onBlur={(e) => setContractStart(normalizeDateInput(e.target.value))}
              required
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Contract end</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={contractEnd}
              onChange={(e) => setContractEnd(e.target.value)}
              onBlur={(e) => setContractEnd(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Order start (PDF od klienta)</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={orderStart}
              onChange={(e) => setOrderStart(e.target.value)}
              onBlur={(e) => setOrderStart(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Order end</span>
            <input
              type="text"
              inputMode="numeric"
              pattern={DATE_PATTERN}
              placeholder={DATE_PLACEHOLDER}
              value={orderEnd}
              onChange={(e) => setOrderEnd(e.target.value)}
              onBlur={(e) => setOrderEnd(normalizeDateInput(e.target.value))}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>

        {canManageFinance && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-sm">
                  Klient płaci ({rateClientCurrency}/{rateUnitSuffix}) *
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={rateClient}
                  onChange={(e) =>
                    setRateClient(sanitizeDecimalInput(e.target.value))
                  }
                  required
                  className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                  placeholder="np. 215,60"
                />
              </label>
              <label>
                <span className="text-sm">
                  My płacimy kontraktorowi ({rateCandidateCurrency}/
                  {rateUnitSuffix}) *
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={rateCandidate}
                  onChange={(e) =>
                    setRateCandidate(sanitizeDecimalInput(e.target.value))
                  }
                  required
                  className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
                  placeholder="np. 150,40"
                />
              </label>
            </div>

            {margin !== null && (
              <div className="text-sm text-green-700 bg-green-50 px-3 py-2 rounded">
                Marża /{rateUnitSuffix} (przybl.):{" "}
                <strong>{margin.toLocaleString("pl-PL")}</strong>{" "}
                {rateClientCurrency}
                {rateClientNum !== null && rateClientNum > 0 && (
                  <> ({((margin / rateClientNum) * 100).toFixed(1)}%)</>
                )}
              </div>
            )}

            <div className="space-y-3">
              <OrderRateUnitToggle
                value={rateUnit}
                rateCandidate={rateCandidate}
                rateClient={rateClient}
                onValueChange={(u) => {
                  rateUnitTouchedRef.current = true;
                  setRateUnit(u);
                }}
                onRateCandidateChange={setRateCandidate}
                onRateClientChange={setRateClient}
                billingHoursPerMonth={Number(billingHours) || 160}
              />
              <div className="grid gap-3 sm:grid-cols-[8rem_1fr_1fr] sm:items-end">
                <label>
                  <span className="text-sm">Godziny / mc</span>
                  <input
                    type="number"
                    min="1"
                    value={billingHours}
                    onChange={(e) => setBillingHours(e.target.value)}
                    disabled={rateUnit !== "hourly"}
                    className="mt-1 w-full px-3 py-2 border border-border rounded bg-background disabled:opacity-50"
                  />
                </label>
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
            </div>

            {rateClientCurrency !== rateCandidateCurrency &&
              rateClientNum !== null &&
              rateCandidateNum !== null && (
                <p className="text-xs text-muted-foreground">
                  Marża zostanie pokazana po niezależnym przeliczeniu obu stawek
                  do PLN.
                </p>
              )}
          </>
        )}

        <label className="block">
          <span className="text-sm">Notatki</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
          />
        </label>

        <div className="flex justify-end gap-2 pt-2">
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
            {mutation.isPending ? "Zapisywanie…" : "Stwórz Contract + Order"}
          </button>
        </div>
      </form>
    </div>
  );
}
