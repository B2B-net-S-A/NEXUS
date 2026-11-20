"use client";

// „Nowy kontrakt” w wariancie B (decyzja Artura z 19.11.2026, makiety modułu
// Kontrakty): po lewej zwarty formularz w trzech sekcjach (Strony umowy, Okres,
// Stawki) i zwinięte „Zaawansowane”, po prawej przyklejona karta
// „Podsumowanie”, która na bieżąco mówi, co powstanie, i trzyma jedyny
// przycisk główny. Pola, walidacja, zapis i bramki — bez zmian.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronRight, ChevronsUpDown, Search, X } from "lucide-react";
import { AxiosError } from "axios";
import api, { contractsApi, extractErrorMsg, CONTRACT_FIELD_LABELS } from "@/lib/api";
import { fetchRecruitmentRates } from "@/lib/api/recruitmentRates";
import { RequirePermission } from "@/components/RequirePermission";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { B2B_END_DATE_HOW, b2bEndDateLocked } from "@/lib/contract-end-date";
import { HOURS_PER_MONTH } from "@/lib/work-time";
import { CandidateRateScheduleFields } from "@/components/contracts/CandidateRateScheduleFields";
import { NewContractSummaryCard } from "@/components/contracts/new/NewContractSummaryCard";
import {
  buildCandidateRateSchedule,
  scheduleHasBackwardsRange,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";
import { relativeDays } from "@/lib/contract-happening";
import { formatIsoDatePl } from "@/lib/date-pl";
import { currencySymbol, rateUnitSuffix } from "@/lib/money";
import {
  advancedSummary,
  candidateRateOnStart,
  contractMoney,
  CREATE_STATUS_LABEL,
  laterFields,
  recruitmentRateHint,
  type CreateStatus,
  type RecruitmentRateHint,
} from "@/lib/new-contract-summary";
import { CONTRACT_TYPE_OPTIONS } from "@/lib/filter-options";
import { canManageCandidateFinance, useAuthStore } from "@/store/auth";
import { warsawToday } from "@/lib/warsaw-date";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { permissionLabel } from "@/lib/permissions";

type CandidateOption = {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  email?: string | null;
};

type RecruitmentOption = {
  stage_id: number;
  job_id: number;
  job_title: string;
  stage?: string;
  client_id?: number | null;
};

type ClientOption = { id: number; name: string };

const CURRENCIES = ["PLN", "EUR", "USD", "GBP"] as const;

const WORK_MODE_OPTIONS = [
  { value: "remote", label: "Zdalnie" },
  { value: "hybrid", label: "Hybrydowo" },
  { value: "onsite", label: "Stacjonarnie" },
] as const;

/**
 * Pola, które mieszkają w „Zaawansowanych”. Błąd któregoś z nich (z walidacji
 * albo z 409 serwera) rozwija sekcję, żeby komunikat nie stał pod zwiniętym
 * nagłówkiem.
 */
const ADVANCED_FIELDS = new Set([
  "status",
  "currency",
  "rate_client_currency",
  "rate_candidate_currency",
  "rate_unit",
  "billing_hours_per_month",
  "framework_rate",
  "framework_rate_schedule",
  "candidate_rate_schedule",
  "order_consumption",
  "order_consumption_unit",
]);

function todayISO(): string {
  return warsawToday();
}

function daysFromToday(iso: string): number | null {
  const a = Date.parse(`${todayISO()}T00:00:00Z`);
  const b = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

function FieldLabel({
  htmlFor,
  children,
  required,
  optional,
  className,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  required?: boolean;
  optional?: boolean;
  className?: string;
}) {
  return (
    <Label htmlFor={htmlFor} className={cn("mb-1 block text-[12.5px] font-medium text-foreground", className)}>
      {children}
      {required ? <span className="text-destructive"> *</span> : null}
      {optional ? <span className="ml-1 font-normal text-muted-foreground">(opcjonalnie)</span> : null}
    </Label>
  );
}

/**
 * Etykieta z „Wyczyść” po prawej. Przycisk stoi w wierszu etykiety, a nie obok
 * pola — w dwóch kolumnach przy 1280 px zabierał miejsce i ucinał nazwisko.
 */
function FieldHead({
  label,
  required,
  optional,
  clearLabel,
  onClear,
}: {
  label: string;
  required?: boolean;
  optional?: boolean;
  clearLabel: string;
  onClear: (() => void) | null;
}) {
  return (
    <div className="mb-1 flex items-center justify-between gap-2">
      <FieldLabel required={required} optional={optional} className="mb-0">
        {label}
      </FieldLabel>
      {onClear ? (
        <button
          type="button"
          title={clearLabel}
          aria-label={clearLabel}
          onClick={onClear}
          className="hit-area inline-flex items-center gap-1 text-[11.5px] text-muted-foreground hover:text-foreground"
        >
          <X className="size-3" aria-hidden />
          Wyczyść
        </button>
      ) : null}
    </div>
  );
}

/** Sekcja formularza: numer, tytuł i jedno zdanie po lewej, pola po prawej. */
function Section({
  n,
  title,
  note,
  children,
}: {
  n: number;
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 gap-3 px-5 py-4 md:grid-cols-[132px_minmax(0,1fr)] md:gap-5">
      <div>
        <h2 className="flex items-baseline gap-1.5 text-[13.5px] font-semibold text-foreground">
          <span className="tabular-nums text-muted-foreground">{n}</span>
          {title}
        </h2>
        <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">{note}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-[11.5px] leading-4 text-muted-foreground">{children}</p>;
}

/** Podpis pod polem stawki: stawka z rekrutacji i — przy stawce konsultanta — „Użyj”. */
function RecruitmentHintLine({
  hint,
  onUse,
}: {
  hint: RecruitmentRateHint | null;
  onUse?: (value: string) => void;
}) {
  if (!hint) return null;
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-[11.5px] leading-4 text-muted-foreground">
      <span>{hint.text}</span>
      {hint.useValue && onUse ? (
        <button
          type="button"
          onClick={() => onUse(hint.useValue as string)}
          className="font-medium text-primary hover:underline"
        >
          Użyj
        </button>
      ) : null}
    </p>
  );
}

function NewContractForm() {
  const router = useRouter();
  const { showSuccess, showError } = useToast();
  const user = useAuthStore((state) => state.user);

  // ── Strony umowy ──────────────────────────────────────────────────────────
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");

  const [clientId, setClientId] = useState("");
  // Kwoty zmienia „Stawki i kwoty: zmiana”; konto z rolą Delivery Leada —
  // u klientów z przypisania, więc po wyborze klienta pytamy o niego.
  const canManageFinance = canManageCandidateFinance(
    user,
    clientId ? Number(clientId) : null,
  );
  const [clientOpen, setClientOpen] = useState(false);
  const [clientQuery, setClientQuery] = useState("");

  const [stageId, setStageId] = useState(""); // wybrana rekrutacja → job_id

  // ── Warunki ─────────────────────────────────────────────────────────────────
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState("");
  const [contractType, setContractType] = useState("b2b");
  const [statusVal, setStatusVal] = useState("draft");
  const [rateClientCurrency, setRateClientCurrency] = useState("PLN");
  const [rateCandidateCurrency, setRateCandidateCurrency] = useState("PLN");
  // Stawki w Kontraktach są godzinowe (umowa B2B podaje stawkę za godzinę).
  const [rateUnit, setRateUnit] = useState("hourly");
  const [billingHours, setBillingHours] = useState(String(HOURS_PER_MONTH));
  // Effective-dated candidate-rate schedule. First row = stawka od startu
  // (effective_from puste ⇒ data rozpoczęcia). Kolejne wiersze = zmiany w czasie.
  // Pierwszy wiersz edytuje pole „Konsultant dostaje”, kolejne — „Zaawansowane”.
  const [rateSchedule, setRateSchedule] = useState<RateScheduleRow[]>([
    { rate: "", effectiveFrom: "" },
  ]);
  const [rateClient, setRateClient] = useState("");
  // Effective-dated framework-rate schedule ("stawka z umowy ramowej"). First
  // row = stawka od startu (effective_from puste ⇒ data rozpoczęcia). Kolejne
  // wiersze = zaplanowane zmiany stawki ramowej w czasie.
  const [frameworkRateSchedule, setFrameworkRateSchedule] = useState<
    RateScheduleRow[]
  >([{ rate: "", effectiveFrom: "" }]);
  const [lineManager, setLineManager] = useState("");
  // Tryb pracy jest informacją opcjonalną i można go uzupełnić później.
  const [workMode, setWorkMode] = useState("");
  // Zużycie zamówienia (ilość + jednostka RBH/MD) — klienci per-zamówienie.
  const [orderConsumption, setOrderConsumption] = useState("");
  const [orderConsumptionUnit, setOrderConsumptionUnit] = useState("rbh");

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [error, setError] = useState("");
  // Błędy per pole: klucz = nazwa pola z API (candidate_id, end_date, …).
  // Pole z wpisem dostaje czerwone obramowanie + opis pod spodem; karta
  // „Podsumowanie” mówi zbiorczo „Uzupełnij brakujące pola” przy przycisku.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const advancedHasError = Object.keys(fieldErrors).some((field) => ADVANCED_FIELDS.has(field));
  const showAdvanced = advancedOpen || advancedHasError;

  const clearField = (field: string) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });

  const fieldError = (field: string) =>
    fieldErrors[field] ? (
      <p className="mt-1 text-xs text-destructive">{fieldErrors[field]}</p>
    ) : null;

  // ── Data ──────────────────────────────────────────────────────────────────
  const candidatesQuery = useQuery({
    queryKey: ["new-contract-candidates", candidateQuery],
    queryFn: async () =>
      (
        await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
          params: { q: candidateQuery, limit: 20 },
        })
      ).data,
    enabled: candidateOpen,
  });

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup-new-contract", "contract-eligible"],
    queryFn: async () =>
      (
        await api.get<ClientOption[]>("/api/clients-lookup", {
          // `delivery_scope`: Delivery Lead widzi tylko swój portfel — zapis
          // kontraktu u klienta spoza niego i tak odmawia 403 (runda 6 audytu).
          params: { contract_eligible: true, delivery_scope: true },
        })
      ).data,
  });

  const recruitmentsQuery = useQuery({
    queryKey: ["new-contract-recruitments", candidate?.id],
    queryFn: async () => {
      if (!candidate) return [] as RecruitmentOption[];
      return (
        await api.get<RecruitmentOption[]>(
          `/api/cv-generator/candidates/${candidate.id}/recruitments`,
        )
      ).data;
    },
    enabled: !!candidate,
  });
  // Lista rekrutacji tylko wybranego klienta (albo bez klienta) — inaczej po
  // zmianie klienta dało się dalej wskazać rekrutację poprzedniego (UAT B24).
  const visibleRecruitments = useMemo(
    () =>
      (recruitmentsQuery.data ?? []).filter(
        (r) => !clientId || r.client_id == null || String(r.client_id) === clientId,
      ),
    [recruitmentsQuery.data, clientId],
  );
  useEffect(() => {
    if (!stageId || !recruitmentsQuery.data) return;
    if (!visibleRecruitments.some((r) => String(r.stage_id) === stageId)) setStageId("");
  }, [stageId, visibleRecruitments, recruitmentsQuery.data]);

  const filteredClients = useMemo(() => {
    const all = clientsQuery.data ?? [];
    const q = clientQuery.trim().toLowerCase();
    const matched = q
      ? all.filter((c) => c.name.toLowerCase().includes(q))
      : all;
    return matched.slice(0, 50);
  }, [clientsQuery.data, clientQuery]);

  const selectedClientName = useMemo(
    () => clientsQuery.data?.find((c) => String(c.id) === clientId)?.name ?? null,
    [clientsQuery.data, clientId],
  );

  const selectedRecruitment = useMemo(
    () => recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId) ?? null,
    [recruitmentsQuery.data, stageId],
  );
  const selectedJobId = selectedRecruitment?.job_id ?? null;

  // Stawki z rekrutacji (D7): podpowiedź pod polami stawek. Tylko odczyt —
  // nic się nie wpisuje samo, różnica nie blokuje zapisu, a awaria zapytania
  // chowa podpis (jak w „Nowym kontraktorze”).
  const recruitmentRatesQuery = useQuery({
    queryKey: ["recruitment-rates", Number(clientId), candidate?.id ?? null, selectedJobId],
    queryFn: () =>
      fetchRecruitmentRates(Number(clientId), candidate?.id as number, selectedJobId),
    enabled: canManageFinance && !!candidate && !!clientId,
    staleTime: 60_000,
    retry: false,
  });
  const recruitmentRate = recruitmentRatesQuery.data?.rate ?? null;

  // Status „Aktywny"/„Kończący się" podnosi wymagalność pól aktywacyjnych —
  // etykiety dostają gwiazdkę dynamicznie, walidacja w handleSubmit.
  const wantsLive = statusVal === "active" || statusVal === "ending";
  // Nowa umowa B2B jest bezterminowa — datę niesie tylko wpis umowy już
  // zakończonej (reguła `lib/contract-end-date.ts`, lustro backendu).
  const endDateLocked = b2bEndDateLocked({
    contract_type: contractType,
    status: statusVal,
  });

  // ── Submit ──────────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: () => {
      const orderConsumptionVal = parseDecimalInput(orderConsumption);
      const payload: Record<string, unknown> = {
        candidate_id: candidate!.id,
        client_id: Number(clientId),
        job_id: selectedJobId,
        start_date: startDate,
        end_date: endDateLocked ? null : endDate || null,
        contract_type: contractType,
        status: statusVal,
        work_mode: workMode || null,
        line_manager: lineManager.trim() || null,
        order_consumption: orderConsumptionVal,
        order_consumption_unit: orderConsumptionVal !== null ? orderConsumptionUnit : null,
      };
      if (canManageFinance) {
        // Candidate-bearing finance fields are Admin-only. Operational callers
        // create a draft without emitting defaults, schedules or currency.
        const schedule = buildCandidateRateSchedule(rateSchedule, startDate);
        const frameworkSchedule = buildCandidateRateSchedule(
          frameworkRateSchedule,
          startDate,
        );
        Object.assign(payload, {
          rate_client_currency: rateClientCurrency,
          rate_candidate_currency: rateCandidateCurrency,
          rate_unit: rateUnit,
          billing_hours_per_month: Number(billingHours) || HOURS_PER_MONTH,
          rate_candidate: schedule.length === 0 ? null : undefined,
          candidate_rate_schedule: schedule.length > 0 ? schedule : undefined,
          rate_client: parseDecimalInput(rateClient),
          framework_rate: frameworkSchedule.length === 0 ? null : undefined,
          framework_rate_schedule:
            frameworkSchedule.length > 0 ? frameworkSchedule : undefined,
        });
      }
      return contractsApi.create(payload);
    },
    onSuccess: (res) => {
      showSuccess("Kontrakt utworzony");
      const id = (res?.data as { id?: number } | undefined)?.id;
      // Zastępujemy wpis formularza w historii: po zapisie „Wstecz” ma wrócić
      // do listy kontraktów, z której użytkownik otworzył /contracts/new.
      router.replace(id ? `/contracts/${id}` : "/contracts");
    },
    onError: (err: unknown) => {
      // Ustrukturyzowane 409 z backendu mapujemy na KONKRETNE pola:
      // - duplicate_contractor → komunikat pod polem kandydata (duplikat
      //   rozpoznawany po e-mailu, nie po nazwisku),
      // - {missing: [...]} z lifecycle'u → podświetlenie każdego brakującego
      //   pola. To siatka bezpieczeństwa — walidacja lokalna w handleSubmit
      //   powinna złapać braki wcześniej, po polsku i bez rundy do serwera.
      if (err instanceof AxiosError && err.response) {
        const detail = (err.response.data as { detail?: unknown })?.detail;
        if (detail && typeof detail === "object" && !Array.isArray(detail)) {
          const d = detail as {
            code?: string;
            message?: string;
            missing?: string[];
          };
          if (d.code === "duplicate_contractor" && d.message) {
            setFieldErrors((prev) => ({ ...prev, candidate_id: d.message! }));
            setError(d.message);
            showError(d.message);
            return;
          }
          if (Array.isArray(d.missing) && d.missing.length > 0) {
            const next: Record<string, string> = {};
            for (const field of d.missing) {
              next[field] =
                `Uzupełnij pole: ${CONTRACT_FIELD_LABELS[field] ?? field}`;
            }
            setFieldErrors((prev) => ({ ...prev, ...next }));
            setError("Uzupełnij brakujące pola");
            showError("Uzupełnij brakujące pola");
            return;
          }
        }
      }
      const msg = extractErrorMsg(err);
      setError(msg);
      showError(msg);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    // Walidacja per pole — każde brakujące pole dostaje własny komunikat i
    // czerwone obramowanie zamiast jednego generycznego banera.
    const errors: Record<string, string> = {};
    if (!candidate) {
      errors.candidate_id = "Wybierz kandydata — pole jest wymagane.";
    }
    if (!clientId) {
      errors.client_id = "Wybierz klienta — pole jest wymagane.";
    }
    if (!startDate) {
      errors.start_date = "Podaj datę rozpoczęcia.";
    }
    // Status „Aktywny"/„Kończący się" wymaga kompletu pól aktywacyjnych
    // (lustro ACTIVATION_REQUIRED_FIELDS z backendu) — odmawiamy od razu,
    // po polsku, zamiast odsyłać użytkownika po 409 z serwera.
    if (wantsLive) {
      const statusLabel = statusVal === "ending" ? "Kończący się" : "Aktywny";
      // Data zakończenia NIE jest wymagana — umowa bezterminowa jest w
      // body-leasingu normalnym stanem docelowym (rejestr renderuje ją jako
      // „bezterminowo"). Lustro `ACTIVATION_REQUIRED_FIELDS`, z którego
      // `end_date` zostało zdjęte razem z tą poprawką.
      if (canManageFinance) {
        if (!rateSchedule.some((r) => r.rate.trim() !== "")) {
          errors.rate_candidate = `Status „${statusLabel}” wymaga stawki kosztowej (kandydata).`;
        }
        if (parseDecimalInput(rateClient) == null) {
          errors.rate_client = `Status „${statusLabel}” wymaga stawki przychodowej (klienta).`;
        }
      } else {
        errors.status =
          "Aktywacja wymaga stawek, które może uzupełnić tylko administrator — zapisz kontrakt jako szkic.";
      }
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setError("Uzupełnij brakujące pola");
      return;
    }
    if (canManageFinance) {
      // Błędy harmonogramów dotyczą pól z „Zaawansowanych” — rozwijamy je,
      // żeby było widać, który etap poprawić.
      const steps = rateSchedule
        .filter((r) => r.rate.trim() !== "")
        .map((r) => r.effectiveFrom || startDate);
      if (new Set(steps).size !== steps.length) {
        setAdvancedOpen(true);
        setError(
          "Każda zmiana stawki musi mieć inną datę „Obowiązuje od”.",
        );
        return;
      }
      if (scheduleHasBackwardsRange(rateSchedule, startDate)) {
        setAdvancedOpen(true);
        setError('„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”.');
        return;
      }
      const frameworkSteps = frameworkRateSchedule
        .filter((r) => r.rate.trim() !== "")
        .map((r) => r.effectiveFrom || startDate);
      if (new Set(frameworkSteps).size !== frameworkSteps.length) {
        setAdvancedOpen(true);
        setError(
          "Każdy etap stawki z umowy ramowej musi mieć inną datę „Obowiązuje od”.",
        );
        return;
      }
      if (scheduleHasBackwardsRange(frameworkRateSchedule, startDate)) {
        setAdvancedOpen(true);
        setError('„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”.');
        return;
      }
    }
    createMutation.mutate();
  };

  // ── Podsumowanie ──────────────────────────────────────────────────────────
  const rateClientNum = parseDecimalInput(rateClient);
  const rateCandidateNum = candidateRateOnStart(rateSchedule, startDate);
  const money = contractMoney({
    clientRate: rateClientNum,
    candidateRate: rateCandidateNum,
    clientCurrency: rateClientCurrency,
    candidateCurrency: rateCandidateCurrency,
    rateUnit,
    billingHours: Number(billingHours) || null,
  });
  const contractTypeLabel =
    CONTRACT_TYPE_OPTIONS.find((o) => o.value === contractType)?.label ?? contractType;
  const startDays = startDate ? daysFromToday(startDate) : null;
  const endLabel = endDateLocked
    ? "bezterminowo"
    : endDate
      ? `do ${formatIsoDatePl(endDate)}`
      : "bez daty końca";
  const statusOptions = (["draft", "active", "ending", "ended"] as const)
    // „Kończący się” wymaga daty końca, a nowa umowa B2B jej nie ma (N3).
    .filter((value) => value !== "ending" || contractType !== "b2b")
    .map((value) => ({ value, label: CREATE_STATUS_LABEL[value] }));
  const rateSuffix = (currency: string) => `${currencySymbol(currency)}${rateUnitSuffix(rateUnit)}`;
  const clientHint = recruitmentRateHint(recruitmentRate, "client", {
    value: rateClient,
    unit: rateUnit,
    currency: rateClientCurrency,
  });
  const candidateHint = recruitmentRateHint(recruitmentRate, "candidate", {
    value: rateSchedule[0]?.rate ?? "",
    unit: rateUnit,
    currency: rateCandidateCurrency,
  });
  const setFirstCandidateRate = (value: string) => {
    setRateSchedule((rows) =>
      rows.map((row, i) => (i === 0 ? { ...row, rate: sanitizeDecimalInput(value) } : row)),
    );
    clearField("rate_candidate");
  };
  const laterCandidateSteps = rateSchedule.slice(1).filter((r) => r.rate.trim() !== "").length;

  return (
    <div className="mx-auto max-w-6xl space-y-3.5">
      <header className="space-y-1">
        <Link
          href="/contracts"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Kontrakty
        </Link>
        <h1 className="text-[22px] font-semibold leading-7 tracking-heading-tight text-foreground">
          Nowy kontrakt
        </h1>
        <p className="text-[13px] text-muted-foreground">
          Powiąż kandydata z klientem. Podsumowanie po prawej mówi, co powstanie;
          umowę, dokumenty i aneksy dodasz po utworzeniu.
        </p>
      </header>

      {/* noValidate: walidację prowadzi handleSubmit (polskie komunikaty per
          pole) — natywne dymki przeglądarki mówiłyby w jej języku i tylko
          o pierwszym polu. */}
      <form
        onSubmit={handleSubmit}
        noValidate
        className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px]"
      >
        <div className="divide-y divide-border/70 rounded-xl border border-border bg-card shadow-xs">
          <Section n={1} title="Strony umowy" note="Kandydat i klient są wymagane, reszta pomaga później.">
            <div className="grid grid-cols-1 gap-x-3.5 gap-y-3 sm:grid-cols-2">
              {/* Kandydat */}
              <div className="min-w-0">
                <FieldHead
                  label="Kandydat"
                  required
                  clearLabel="Wyczyść kandydata"
                  onClear={
                    candidate
                      ? () => {
                          setCandidate(null);
                          setStageId("");
                        }
                      : null
                  }
                />
                <div>
                  <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        title={candidate?.full_name}
                        className={cn(
                          "w-full justify-between px-3 font-normal",
                          fieldErrors.candidate_id &&
                            "border-destructive focus-visible:ring-destructive",
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                          <span className={cn("truncate", !candidate && "text-muted-foreground")}>
                            {candidate ? candidate.full_name : "Wybierz kandydata…"}
                          </span>
                        </span>
                        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      className="w-(--radix-popover-trigger-width) min-w-72 p-0"
                    >
                      <Command shouldFilter={false}>
                        <CommandInput
                          placeholder="Szukaj kandydata…"
                          value={candidateQuery}
                          onValueChange={setCandidateQuery}
                        />
                        <CommandList>
                          {/* Awaria wyszukiwania ≠ „nikogo nie ma”: pusty stan tylko przy sukcesie. */}
                          <PickerQueryState
                            isPending={candidatesQuery.isLoading}
                            isError={candidatesQuery.isError}
                            onRetry={() => void candidatesQuery.refetch()}
                            loadingLabel="Szukam…"
                            errorLabel="Nie udało się wyszukać kandydatów."
                          />
                          {candidatesQuery.isSuccess && <CommandEmpty>Brak wyników.</CommandEmpty>}
                          <CommandGroup>
                            {(candidatesQuery.data ?? []).map((c) => (
                              <CommandItem
                                key={c.id}
                                value={String(c.id)}
                                onSelect={() => {
                                  setCandidate(c);
                                  setStageId("");
                                  clearField("candidate_id");
                                  setCandidateOpen(false);
                                }}
                              >
                                <Check
                                  className={cn(
                                    "mr-2 h-4 w-4",
                                    candidate?.id === c.id
                                      ? "opacity-100"
                                      : "opacity-0",
                                  )}
                                />
                                <span className="truncate">
                                  {c.full_name}
                                  {c.email ? (
                                    <span className="ml-1 text-xs text-muted-foreground">
                                      {c.email}
                                    </span>
                                  ) : null}
                                </span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                </div>
                {fieldError("candidate_id")}
              </div>

              {/* Klient */}
              <div className="min-w-0">
                <FieldHead
                  label="Klient"
                  required
                  clearLabel="Wyczyść klienta"
                  onClear={clientId ? () => setClientId("") : null}
                />
                <div>
                  <Popover open={clientOpen} onOpenChange={setClientOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        title={selectedClientName ?? undefined}
                        className={cn(
                          "w-full justify-between px-3 font-normal",
                          fieldErrors.client_id &&
                            "border-destructive focus-visible:ring-destructive",
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                          <span className={cn("truncate", !selectedClientName && "text-muted-foreground")}>
                            {selectedClientName ?? "Wybierz klienta…"}
                          </span>
                        </span>
                        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      className="w-(--radix-popover-trigger-width) min-w-72 p-0"
                    >
                      <Command shouldFilter={false}>
                        <CommandInput
                          placeholder="Szukaj klienta…"
                          value={clientQuery}
                          onValueChange={setClientQuery}
                        />
                        <CommandList>
                          {/* Awaria listy klientów ≠ „brak klientów”: pusty stan tylko przy sukcesie. */}
                          <PickerQueryState
                            isPending={clientsQuery.isPending}
                            isError={clientsQuery.isError}
                            onRetry={() => void clientsQuery.refetch()}
                            loadingLabel="Ładowanie klientów…"
                            errorLabel="Nie udało się pobrać listy klientów."
                          />
                          {clientsQuery.isSuccess && <CommandEmpty>Brak wyników.</CommandEmpty>}
                          <CommandGroup>
                            {filteredClients.map((c) => (
                              <CommandItem
                                key={c.id}
                                value={String(c.id)}
                                onSelect={() => {
                                  setClientId(String(c.id));
                                  // Rekrutacja innego klienta nie może zostać
                                  // w formularzu po zmianie klienta — backend
                                  // i tak odrzuci `job_client_mismatch`, ale
                                  // dopiero przy zapisie (UAT B24). Rekrutacja
                                  // bez klienta zostaje.
                                  const chosen = recruitmentsQuery.data?.find(
                                    (r) => String(r.stage_id) === stageId,
                                  );
                                  if (chosen?.client_id != null && chosen.client_id !== c.id) {
                                    setStageId("");
                                  }
                                  clearField("client_id");
                                  setClientOpen(false);
                                }}
                              >
                                <Check
                                  className={cn(
                                    "mr-2 h-4 w-4",
                                    clientId === String(c.id)
                                      ? "opacity-100"
                                      : "opacity-0",
                                  )}
                                />
                                <span className="truncate">{c.name}</span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                    </PopoverContent>
                  </Popover>
                </div>
                {fieldError("client_id")}
              </div>

              {/* Rekrutacja (opcjonalna, daje job_id) */}
              <div className="min-w-0 sm:col-span-2">
                <FieldHead
                  label="Rekrutacja"
                  optional
                  clearLabel="Wyczyść rekrutację"
                  onClear={stageId ? () => setStageId("") : null}
                />
                <div>
                  <Select value={stageId} onValueChange={setStageId} disabled={!candidate}>
                    <SelectTrigger
                      aria-label="Rekrutacja"
                      className="h-9 [&>span]:truncate [&>span]:text-left"
                      title={selectedRecruitment?.job_title}
                    >
                      <SelectValue
                        placeholder={
                          candidate
                            ? "Wybierz rekrutację kandydata…"
                            : "Najpierw wybierz kandydata"
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {visibleRecruitments.map((r) => (
                        <SelectItem key={r.stage_id} value={String(r.stage_id)}>
                          {r.job_title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Line Manager — osoba po stronie klienta, pod którą raportuje kontraktor */}
              <div className="min-w-0">
                <FieldLabel htmlFor="new-contract-line-manager" optional>
                  Line manager
                </FieldLabel>
                <Input
                  id="new-contract-line-manager"
                  type="text"
                  value={lineManager}
                  onChange={(e) => setLineManager(e.target.value)}
                  placeholder="Osoba po stronie klienta"
                  className="h-9"
                />
              </div>

              <div className="min-w-0">
                <FieldLabel optional>Tryb pracy</FieldLabel>
                <Select
                  value={workMode}
                  onValueChange={(v) => {
                    setWorkMode(v === "none" ? "" : v);
                    clearField("work_mode");
                  }}
                >
                  <SelectTrigger
                    aria-label="Tryb pracy"
                    className={cn("h-9", fieldErrors.work_mode && "border-destructive")}
                  >
                    <SelectValue placeholder="Nie określono" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Nie określono</SelectItem>
                    {WORK_MODE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {fieldError("work_mode")}
              </div>
            </div>
          </Section>

          <Section n={2} title="Okres" note="Od kiedy osoba pracuje u klienta.">
            <div className="grid grid-cols-1 gap-x-3.5 gap-y-3 sm:grid-cols-2">
              <div className="min-w-0">
                <FieldLabel required={wantsLive}>Typ umowy</FieldLabel>
                <Select
                  value={contractType}
                  onValueChange={(v) => {
                    setContractType(v);
                    clearField("contract_type");
                    // Nowa umowa B2B jest bezterminowa, a „Kończący się”
                    // wymaga daty końca — serwer odmówiłby 409 (audyt 24.09,
                    // N3). Przy zmianie typu na B2B status wraca na „Szkic”.
                    if (v === "b2b" && statusVal === "ending") setStatusVal("draft");
                  }}
                >
                  <SelectTrigger
                    aria-label="Typ umowy"
                    className={cn("h-9", fieldErrors.contract_type && "border-destructive")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CONTRACT_TYPE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {fieldError("contract_type")}
              </div>
              <div className="min-w-0">
                <FieldLabel htmlFor="new-contract-start" required>
                  Data startu
                </FieldLabel>
                <Input
                  id="new-contract-start"
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    clearField("start_date");
                  }}
                  className={cn("h-9 tabular-nums", fieldErrors.start_date && "border-destructive")}
                />
                {fieldError("start_date")}
              </div>
              {endDateLocked ? (
                <p
                  className="text-[12px] leading-4 text-muted-foreground sm:col-span-2"
                  data-testid="end-date-b2b-indefinite"
                >
                  Bezterminowo. {B2B_END_DATE_HOW}
                </p>
              ) : (
                <div className="min-w-0 sm:col-start-2">
                  <FieldLabel htmlFor="new-contract-end" optional>
                    Data końca
                  </FieldLabel>
                  <Input
                    id="new-contract-end"
                    type="date"
                    value={endDate}
                    onChange={(e) => {
                      setEndDate(e.target.value);
                      clearField("end_date");
                    }}
                    className={cn("h-9 tabular-nums", fieldErrors.end_date && "border-destructive")}
                  />
                </div>
              )}
              {fieldError("end_date")}
            </div>
          </Section>

          <Section
            n={3}
            title="Stawki"
            note={canManageFinance ? "Netto, z umowy. Pod polem: stawka z rekrutacji." : "Kwoty kontraktu."}
          >
            {canManageFinance ? (
              <>
                <div className="grid grid-cols-1 gap-x-3.5 gap-y-3 sm:grid-cols-2">
                  <div className="min-w-0">
                    <FieldLabel htmlFor="new-contract-rate-client" required={wantsLive}>
                      Klient płaci
                    </FieldLabel>
                    <Input
                      id="new-contract-rate-client"
                      type="text"
                      inputMode="decimal"
                      value={rateClient}
                      onChange={(e) => {
                        setRateClient(sanitizeDecimalInput(e.target.value));
                        clearField("rate_client");
                      }}
                      placeholder="np. 215,60"
                      trailingIcon={<span className="text-xs">{rateSuffix(rateClientCurrency)}</span>}
                      className={cn("h-9 pr-14 tabular-nums", fieldErrors.rate_client && "border-destructive")}
                    />
                    {fieldError("rate_client")}
                    <RecruitmentHintLine hint={clientHint} />
                  </div>
                  <div className="min-w-0">
                    <FieldLabel htmlFor="new-contract-rate-candidate" required={wantsLive}>
                      Konsultant dostaje
                    </FieldLabel>
                    <Input
                      id="new-contract-rate-candidate"
                      type="text"
                      inputMode="decimal"
                      value={rateSchedule[0]?.rate ?? ""}
                      onChange={(e) => setFirstCandidateRate(e.target.value)}
                      placeholder="np. 160,00"
                      trailingIcon={<span className="text-xs">{rateSuffix(rateCandidateCurrency)}</span>}
                      className={cn("h-9 pr-14 tabular-nums", fieldErrors.rate_candidate && "border-destructive")}
                    />
                    {fieldError("rate_candidate")}
                    <RecruitmentHintLine hint={candidateHint} onUse={setFirstCandidateRate} />
                    {laterCandidateSteps > 0 ? (
                      <Hint>
                        Od startu; zaplanowane zmiany ({laterCandidateSteps}) są w „Zaawansowanych”.
                      </Hint>
                    ) : null}
                  </div>
                </div>
                {money.marginPerUnit != null && money.marginPerUnit < 0 ? (
                  <p
                    role="status"
                    className="mt-2.5 rounded-lg border border-current/25 bg-destructive/10 px-3 py-2 text-[12.5px] text-destructive"
                  >
                    Konsultant kosztuje więcej, niż płaci klient — sprawdź stawki.
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-[12.5px] leading-[18px] text-muted-foreground">
                Stawki u tego klienta wpisuje osoba z uprawnieniem „{permissionLabel("amounts_edit")}”
                — tu kontrakt powstaje bez kwot.
              </p>
            )}
          </Section>

          <div>
            <button
              type="button"
              aria-expanded={showAdvanced}
              aria-controls="new-contract-advanced"
              onClick={() => setAdvancedOpen(!showAdvanced)}
              title="W środku: waluty i jednostka stawek, godziny w miesiącu, stawka z umowy ramowej, zmiany stawki w czasie, zużycie zamówienia i status przy utworzeniu."
              data-tour="contracts.new.advanced"
              className="flex w-full items-center gap-2 px-5 py-2.5 text-left hover:bg-muted/40"
            >
              <ChevronRight
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-transform",
                  showAdvanced && "rotate-90",
                )}
                aria-hidden
              />
              <span className="shrink-0 text-[13px] font-medium text-foreground">Zaawansowane</span>
              <span className="min-w-0 truncate text-[12px] text-muted-foreground">
                {advancedSummary({
                  canManageFinance,
                  clientCurrency: rateClientCurrency,
                  candidateCurrency: rateCandidateCurrency,
                  rateUnit,
                  billingHours,
                  frameworkRows: frameworkRateSchedule,
                  candidateRows: rateSchedule,
                  consumption: orderConsumption,
                  consumptionUnit: orderConsumptionUnit,
                  status: statusVal,
                })}
              </span>
            </button>
            {showAdvanced ? (
              <div id="new-contract-advanced" className="space-y-4 border-t border-border/70 px-5 py-4">
                {canManageFinance ? (
                  <div className="grid grid-cols-1 gap-x-4 gap-y-3.5 sm:grid-cols-2">
                    <div className="min-w-0">
                      <FieldLabel>Waluta stawki klienta</FieldLabel>
                      <Select value={rateClientCurrency} onValueChange={setRateClientCurrency}>
                        <SelectTrigger aria-label="Waluta stawki przychodowej (klienta)" className="h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CURRENCIES.map((cur) => (
                            <SelectItem key={cur} value={cur}>
                              {cur}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="min-w-0">
                      <FieldLabel>Waluta stawki konsultanta</FieldLabel>
                      <Select value={rateCandidateCurrency} onValueChange={setRateCandidateCurrency}>
                        <SelectTrigger
                          aria-label="Waluta stawki kosztowej (kandydata / umowy ramowej)"
                          className="h-9"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CURRENCIES.map((cur) => (
                            <SelectItem key={cur} value={cur}>
                              {cur}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Hint>Ta sama waluta obowiązuje stawkę z umowy ramowej.</Hint>
                    </div>
                    <div className="min-w-0">
                      <FieldLabel>Jednostka stawki</FieldLabel>
                      {/* Stawki w Kontraktach są godzinowe (zł/h) albo
                          ryczałtowe — bez MD. Zamówienie w MD prowadzi się
                          w module Klienci; kontrakt przelicza je ÷ 8. */}
                      <SegmentedRadio<"hourly" | "monthly">
                        label="Jednostka stawki"
                        size="sm"
                        value={rateUnit === "monthly" ? "monthly" : "hourly"}
                        onChange={setRateUnit}
                        options={[
                          { value: "hourly", label: "Za godzinę" },
                          { value: "monthly", label: "Ryczałt miesięczny" },
                        ]}
                      />
                    </div>
                    {rateUnit === "hourly" ? (
                      <div className="min-w-0">
                        <FieldLabel htmlFor="new-contract-hours">Godziny w miesiącu</FieldLabel>
                        <Input
                          id="new-contract-hours"
                          type="number"
                          min="1"
                          step="1"
                          value={billingHours}
                          onChange={(e) => setBillingHours(e.target.value)}
                          className="h-9 tabular-nums"
                        />
                        <Hint>Do przeliczeń miesięcznych, też marży w podsumowaniu.</Hint>
                      </div>
                    ) : null}
                    <div className="min-w-0 sm:col-span-2">
                      {/* Stawka z umowy ramowej — OPCJONALNA: nie blokuje zapisu
                          w żadnym statusie (nie ma jej w ACTIVATION_REQUIRED_FIELDS). */}
                      <CandidateRateScheduleFields
                        rows={frameworkRateSchedule}
                        onChange={setFrameworkRateSchedule}
                        startDate={startDate}
                        label="Stawka z umowy ramowej (opcjonalna)"
                        hint="Pułap z cennika klienta; nie wchodzi do marży. Zmianę możesz zaplanować od daty."
                        addLabel="+ Dodaj etap stawki ramowej"
                      />
                    </div>
                    <div className="min-w-0 sm:col-span-2">
                      {/* Stawka progresywna kandydata — kolejne etapy OPCJONALNE;
                          dla statusu „Aktywny" wymagany jest tylko pierwszy wpis
                          stawki (kosztowej). Pierwszy etap to „Konsultant dostaje”. */}
                      <CandidateRateScheduleFields
                        rows={rateSchedule}
                        onChange={(rows) => {
                          setRateSchedule(rows);
                          clearField("rate_candidate");
                        }}
                        startDate={startDate}
                        label="Stawka konsultanta w czasie"
                        hint="Pierwszy etap to „Konsultant dostaje”; kolejny przełączy stawkę sam od wskazanej daty."
                        addLabel="+ Zaplanuj zmianę stawki"
                      />
                    </div>
                  </div>
                ) : null}

                {/* Zużycie zamówienia — ilość + jednostka (RBH / MD) */}
                <div className={cn(canManageFinance && "border-t border-border/60 pt-3")}>
                  <FieldLabel htmlFor="new-contract-consumption" optional>
                    Zużycie zamówienia
                  </FieldLabel>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      id="new-contract-consumption"
                      type="text"
                      inputMode="decimal"
                      value={orderConsumption}
                      onChange={(e) => setOrderConsumption(sanitizeDecimalInput(e.target.value))}
                      placeholder="—"
                      className="h-9 w-40 tabular-nums"
                    />
                    <SegmentedRadio<"rbh" | "md">
                      label="Jednostka zużycia"
                      size="sm"
                      value={orderConsumptionUnit === "md" ? "md" : "rbh"}
                      onChange={setOrderConsumptionUnit}
                      options={[
                        { value: "rbh", label: "RBH (roboczogodziny)" },
                        { value: "md", label: "MD (osobodni)" },
                      ]}
                    />
                  </div>
                  <Hint>
                    Ile z zamówienia klienta zużywa ten kontrakt — tylko u klientów rozliczanych per
                    zamówienie. U pozostałych zostaw puste.
                  </Hint>
                </div>

                <div className="border-t border-border/60 pt-3">
                  <FieldLabel>Status przy utworzeniu</FieldLabel>
                  <SegmentedRadio<CreateStatus>
                    label="Status przy utworzeniu"
                    size="sm"
                    value={statusVal as CreateStatus}
                    onChange={(v) => {
                      setStatusVal(v);
                      clearField("status");
                    }}
                    options={statusOptions}
                  />
                  {fieldError("status")}
                  <Hint>Zwykle szkic. „Aktywny” i „Zakończony” tylko przy wpisie umowy już podpisanej.</Hint>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <aside className="lg:sticky lg:top-4">
          <NewContractSummaryCard
            candidateName={candidate?.full_name ?? null}
            clientName={selectedClientName}
            recruitmentTitle={selectedRecruitment?.job_title ?? null}
            contractTypeLabel={contractTypeLabel}
            startDate={startDate}
            startRelative={startDays != null ? relativeDays(startDays) : null}
            endLabel={endLabel}
            status={statusVal}
            money={
              canManageFinance
                ? {
                    facts: money,
                    clientRate: rateClientNum,
                    candidateRate: rateCandidateNum,
                    clientCurrency: rateClientCurrency,
                    candidateCurrency: rateCandidateCurrency,
                    rateUnit,
                  }
                : null
            }
            later={laterFields({ lineManager, workMode })}
            error={error}
            submitting={createMutation.isPending}
          />
        </aside>
      </form>
    </div>
  );
}

/**
 * Client-only gate (wzorzec jak /contracts i /contracts/b2b-generator) —
 * Next.js 15 + React 19 streaming SSR wieszał hydrację komponentów z useQuery.
 */
export default function NewContractPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>
    );
  }
  return (
    <RequirePermission
      permissions={["contracts_orders_edit"]}
      fallback={
        <div className="max-w-3xl mx-auto p-6">
          <Link
            href="/contracts"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Wróć do listy
          </Link>
          <p className="mt-4 text-sm text-muted-foreground">
            Brakuje Ci uprawnienia „{permissionLabel("contracts_orders_edit")}”.
            Poproś administratora o dostęp (Ustawienia → Zespół i dostęp →
            Osoby i role).
          </p>
        </div>
      }
    >
      <NewContractForm />
    </RequirePermission>
  );
}
