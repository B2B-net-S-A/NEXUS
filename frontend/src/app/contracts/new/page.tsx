"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronsUpDown,
  Save,
  Search,
  X,
} from "lucide-react";
import { AxiosError } from "axios";
import api, {
  contractsApi,
  extractErrorMsg,
  CONTRACT_FIELD_LABELS,
} from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { CandidateRateScheduleFields } from "@/components/contracts/CandidateRateScheduleFields";
import {
  buildCandidateRateSchedule,
  scheduleHasBackwardsRange,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";
import {
  canManageCandidateFinance,
  useAuthStore,
} from "@/store/auth";

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
};

type ClientOption = { id: number; name: string };

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function NewContractForm() {
  const router = useRouter();
  const { showSuccess, showError } = useToast();
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);

  // ── Strony umowy ──────────────────────────────────────────────────────────
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");

  const [clientId, setClientId] = useState("");
  const [clientOpen, setClientOpen] = useState(false);
  const [clientQuery, setClientQuery] = useState("");

  const [stageId, setStageId] = useState(""); // wybrana rekrutacja → job_id

  // ── Warunki ─────────────────────────────────────────────────────────────────
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState("");
  const [contractType, setContractType] = useState("b2b");
  const [statusVal, setStatusVal] = useState("draft");
  const [currency, setCurrency] = useState("PLN");
  const [rateUnit, setRateUnit] = useState("monthly");
  const [billingHours, setBillingHours] = useState("160");
  // Effective-dated candidate-rate schedule. First row = stawka od startu
  // (effective_from puste ⇒ data rozpoczęcia). Kolejne wiersze = zmiany w czasie.
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
  // Tryb pracy — bez niego status „Aktywny" NIGDY nie przechodził walidacji
  // aktywacji (ACTIVATION_REQUIRED_FIELDS zawiera work_mode, a formularz nie
  // miał tego pola wcale — użytkownik nie miał jak spełnić wymagania).
  const [workMode, setWorkMode] = useState("");
  // Zużycie zamówienia (ilość + jednostka RBH/MD) — klienci per-zamówienie.
  const [orderConsumption, setOrderConsumption] = useState("");
  const [orderConsumptionUnit, setOrderConsumptionUnit] = useState("rbh");

  const [error, setError] = useState("");
  // Błędy per pole: klucz = nazwa pola z API (candidate_id, end_date, …).
  // Pole z wpisem dostaje czerwone obramowanie + opis pod spodem; baner na
  // górze mówi zbiorczo „Uzupełnij brakujące pola".
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

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
    queryKey: ["clients-lookup-new-contract"],
    queryFn: async () =>
      (await api.get<ClientOption[]>("/api/clients-lookup")).data,
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

  const selectedJobId = useMemo(
    () =>
      recruitmentsQuery.data?.find((r) => String(r.stage_id) === stageId)
        ?.job_id ?? null,
    [recruitmentsQuery.data, stageId],
  );

  // Status „Aktywny"/„Kończący się" podnosi wymagalność pól aktywacyjnych —
  // etykiety dostają gwiazdkę dynamicznie, walidacja w handleSubmit.
  const wantsLive = statusVal === "active" || statusVal === "ending";

  // ── Submit ──────────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: () => {
      const orderConsumptionVal = parseDecimalInput(orderConsumption);
      const payload: Record<string, unknown> = {
        candidate_id: candidate!.id,
        client_id: Number(clientId),
        job_id: selectedJobId,
        start_date: startDate,
        end_date: endDate || null,
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
          currency,
          rate_unit: rateUnit,
          billing_hours_per_month: Number(billingHours) || 160,
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
      router.push(id ? `/contracts/${id}` : "/contracts");
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
      if (!workMode) {
        errors.work_mode = `Status „${statusLabel}” wymaga trybu pracy.`;
      }
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
      const steps = rateSchedule
        .filter((r) => r.rate.trim() !== "")
        .map((r) => r.effectiveFrom || startDate);
      if (new Set(steps).size !== steps.length) {
        setError(
          "Każda zmiana stawki musi mieć inną datę „Obowiązuje od”.",
        );
        return;
      }
      if (scheduleHasBackwardsRange(rateSchedule, startDate)) {
        setError('„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”.');
        return;
      }
      const frameworkSteps = frameworkRateSchedule
        .filter((r) => r.rate.trim() !== "")
        .map((r) => r.effectiveFrom || startDate);
      if (new Set(frameworkSteps).size !== frameworkSteps.length) {
        setError(
          "Każdy etap stawki z umowy ramowej musi mieć inną datę „Obowiązuje od”.",
        );
        return;
      }
      if (scheduleHasBackwardsRange(frameworkRateSchedule, startDate)) {
        setError('„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”.');
        return;
      }
    }
    createMutation.mutate();
  };

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {/* Header */}
      <div className="space-y-1">
        <Link
          href="/contracts"
          className="inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Kontrakty
        </Link>
        <h1 className="text-2xl font-bold tracking-heading-tight text-foreground">
          Nowy kontrakt
        </h1>
        <p className="text-sm text-muted-foreground">
          Powiąż kandydata z klientem. Resztę szczegółów (dokumenty, draft umowy,
          aneksy) uzupełnisz po utworzeniu.
        </p>
      </div>

      {/* noValidate: walidację prowadzi handleSubmit (polskie komunikaty per
          pole) — natywne dymki przeglądarki mówiłyby w jej języku i tylko
          o pierwszym polu. */}
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-destructive/10 px-4 py-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        {/* Strony umowy */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Strony umowy</CardTitle>
            <CardDescription>
              Kandydat i klient są wymagane. Rekrutację możesz dobrać z listy
              kandydata.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {/* Kandydat */}
              <div>
                <Label className="mb-1.5 block">
                  Kandydat <span className="text-destructive">*</span>
                </Label>
                <div className="flex gap-2">
                  <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className={cn(
                          "w-full justify-between font-normal",
                          fieldErrors.candidate_id &&
                            "border-destructive focus-visible:ring-destructive",
                        )}
                      >
                        <span className="flex items-center gap-2 truncate">
                          <Search className="h-4 w-4 shrink-0 opacity-60" />
                          {candidate ? candidate.full_name : "Wybierz kandydata…"}
                        </span>
                        <ChevronsUpDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      className="w-(--radix-popover-trigger-width) p-0"
                    >
                      <Command shouldFilter={false}>
                        <CommandInput
                          placeholder="Szukaj kandydata…"
                          value={candidateQuery}
                          onValueChange={setCandidateQuery}
                        />
                        <CommandList>
                          {candidatesQuery.isLoading ? (
                            <div className="p-3 text-sm text-muted-foreground">
                              Szukam…
                            </div>
                          ) : (
                            <CommandEmpty>Brak wyników.</CommandEmpty>
                          )}
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
                  {candidate ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      title="Wyczyść kandydata"
                      onClick={() => {
                        setCandidate(null);
                        setStageId("");
                      }}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  ) : null}
                </div>
                {fieldError("candidate_id")}
              </div>

              {/* Klient */}
              <div>
                <Label className="mb-1.5 block">
                  Klient <span className="text-destructive">*</span>
                </Label>
                <div className="flex gap-2">
                  <Popover open={clientOpen} onOpenChange={setClientOpen}>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        className={cn(
                          "w-full justify-between font-normal",
                          fieldErrors.client_id &&
                            "border-destructive focus-visible:ring-destructive",
                        )}
                      >
                        <span className="flex items-center gap-2 truncate">
                          <Search className="h-4 w-4 shrink-0 opacity-60" />
                          {selectedClientName ?? "Wybierz klienta…"}
                        </span>
                        <ChevronsUpDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      className="w-(--radix-popover-trigger-width) p-0"
                    >
                      <Command shouldFilter={false}>
                        <CommandInput
                          placeholder="Szukaj klienta…"
                          value={clientQuery}
                          onValueChange={setClientQuery}
                        />
                        <CommandList>
                          {clientsQuery.isLoading ? (
                            <div className="p-3 text-sm text-muted-foreground">
                              Ładowanie…
                            </div>
                          ) : (
                            <CommandEmpty>Brak wyników.</CommandEmpty>
                          )}
                          <CommandGroup>
                            {filteredClients.map((c) => (
                              <CommandItem
                                key={c.id}
                                value={String(c.id)}
                                onSelect={() => {
                                  setClientId(String(c.id));
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
                  {clientId ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      title="Wyczyść klienta"
                      onClick={() => setClientId("")}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  ) : null}
                </div>
                {fieldError("client_id")}
              </div>
            </div>

            {/* Rekrutacja (opcjonalna, daje job_id) */}
            <div>
              <Label className="mb-1.5 block">Rekrutacja (opcjonalnie)</Label>
              <Select value={stageId} onValueChange={setStageId} disabled={!candidate}>
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      candidate
                        ? "Wybierz rekrutację kandydata…"
                        : "Najpierw wybierz kandydata"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {(recruitmentsQuery.data ?? []).map((r) => (
                    <SelectItem key={r.stage_id} value={String(r.stage_id)}>
                      {r.job_title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Line Manager — osoba po stronie klienta, pod którą raportuje kontraktor */}
            <div>
              <Label className="mb-1.5 block">Line Manager</Label>
              <Input
                type="text"
                value={lineManager}
                onChange={(e) => setLineManager(e.target.value)}
                placeholder="Imię i nazwisko (po stronie klienta)"
              />
            </div>
          </CardContent>
        </Card>

        {/* Warunki */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Warunki</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="mb-1.5 block">
                  Data rozpoczęcia <span className="text-destructive">*</span>
                </Label>
                <Input
                  type="date"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    clearField("start_date");
                  }}
                  className={cn(fieldErrors.start_date && "border-destructive")}
                />
                {fieldError("start_date")}
              </div>
              <div>
                <Label className="mb-1.5 block">
                  Data zakończenia{" "}
                  {wantsLive ? (
                    <span className="text-destructive">*</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      (opcjonalna dla szkicu)
                    </span>
                  )}
                </Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value);
                    clearField("end_date");
                  }}
                  className={cn(fieldErrors.end_date && "border-destructive")}
                />
                {fieldError("end_date")}
              </div>
              <div>
                <Label className="mb-1.5 block">
                  Typ kontraktu{wantsLive && <span className="text-destructive"> *</span>}
                </Label>
                <Select
                  value={contractType}
                  onValueChange={(v) => {
                    setContractType(v);
                    clearField("contract_type");
                  }}
                >
                  <SelectTrigger
                    className={cn(fieldErrors.contract_type && "border-destructive")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="b2b">B2B</SelectItem>
                    <SelectItem value="uop">Umowa o pracę</SelectItem>
                    <SelectItem value="uzlecenie">Zlecenie</SelectItem>
                  </SelectContent>
                </Select>
                {fieldError("contract_type")}
              </div>
              <div>
                <Label className="mb-1.5 block">Status</Label>
                <Select
                  value={statusVal}
                  onValueChange={(v) => {
                    setStatusVal(v);
                    clearField("status");
                  }}
                >
                  <SelectTrigger
                    className={cn(fieldErrors.status && "border-destructive")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="draft">Szkic</SelectItem>
                    <SelectItem value="active">Aktywny</SelectItem>
                    <SelectItem value="ending">Kończący się</SelectItem>
                    <SelectItem value="ended">Zakończony</SelectItem>
                  </SelectContent>
                </Select>
                {fieldError("status")}
              </div>
              <div>
                <Label className="mb-1.5 block">
                  Tryb pracy{wantsLive && <span className="text-destructive"> *</span>}
                </Label>
                <Select
                  value={workMode}
                  onValueChange={(v) => {
                    setWorkMode(v);
                    clearField("work_mode");
                  }}
                >
                  <SelectTrigger
                    className={cn(fieldErrors.work_mode && "border-destructive")}
                  >
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="remote">Zdalnie</SelectItem>
                    <SelectItem value="hybrid">Hybrydowo</SelectItem>
                    <SelectItem value="onsite">Stacjonarnie</SelectItem>
                  </SelectContent>
                </Select>
                {fieldError("work_mode")}
              </div>
            </div>

            {canManageFinance && (
              <>
                <div className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <Label className="mb-1.5 block">Jednostka stawki</Label>
                    <Select value={rateUnit} onValueChange={setRateUnit}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="monthly">Miesięcznie</SelectItem>
                        <SelectItem value="daily">Dziennie</SelectItem>
                        <SelectItem value="hourly">Godzinowo</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="mb-1.5 block">Waluta</Label>
                    <Select value={currency} onValueChange={setCurrency}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="PLN">PLN</SelectItem>
                        <SelectItem value="EUR">EUR</SelectItem>
                        <SelectItem value="USD">USD</SelectItem>
                        <SelectItem value="GBP">GBP</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {rateUnit === "hourly" && (
                    <div>
                      <Label className="mb-1.5 block">Godziny / miesiąc</Label>
                      <Input
                        type="number"
                        min="1"
                        step="1"
                        value={billingHours}
                        onChange={(e) => setBillingHours(e.target.value)}
                      />
                    </div>
                  )}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label className="mb-1.5 block">
                      Stawka przychodowa (klienta)
                      {wantsLive && <span className="text-destructive"> *</span>}
                    </Label>
                    <Input
                      type="text"
                      inputMode="decimal"
                      value={rateClient}
                      onChange={(e) => {
                        setRateClient(sanitizeDecimalInput(e.target.value));
                        clearField("rate_client");
                      }}
                      placeholder="np. 215,60"
                      className={cn(fieldErrors.rate_client && "border-destructive")}
                    />
                    {fieldError("rate_client")}
                  </div>
                </div>

                {/* Stawka z umowy ramowej — OPCJONALNA: nie blokuje zapisu
                    w żadnym statusie (nie ma jej w ACTIVATION_REQUIRED_FIELDS). */}
                <CandidateRateScheduleFields
                  rows={frameworkRateSchedule}
                  onChange={setFrameworkRateSchedule}
                  startDate={startDate}
                  label="Stawka z umowy ramowej (opcjonalna)"
                  hint="Możesz zaplanować zmianę stawki ramowej — system zastosuje aktualną od wskazanej daty."
                  addLabel="+ Dodaj etap stawki ramowej"
                />

                {/* Stawka progresywna kandydata — kolejne etapy OPCJONALNE;
                    dla statusu „Aktywny" wymagany jest tylko pierwszy wpis
                    stawki (kosztowej). */}
                <CandidateRateScheduleFields
                  rows={rateSchedule}
                  onChange={(rows) => {
                    setRateSchedule(rows);
                    clearField("rate_candidate");
                  }}
                  startDate={startDate}
                />
                {fieldError("rate_candidate")}
              </>
            )}

            {/* Zużycie zamówienia — ilość + jednostka (RBH / MD) */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="mb-1.5 block">Zużycie zamówienia</Label>
                <Input
                  type="text"
                  inputMode="decimal"
                  value={orderConsumption}
                  onChange={(e) =>
                    setOrderConsumption(sanitizeDecimalInput(e.target.value))
                  }
                  placeholder="—"
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Jednostka zużycia</Label>
                <Select
                  value={orderConsumptionUnit}
                  onValueChange={setOrderConsumptionUnit}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rbh">RBH</SelectItem>
                    <SelectItem value="md">MD</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end gap-2">
          <Link href="/contracts">
            <Button type="button" variant="ghost">
              Anuluj
            </Button>
          </Link>
          <Button
            type="submit"
            variant="primary"
            loading={createMutation.isPending}
          >
            {createMutation.isPending ? null : <Save className="h-4 w-4" />}
            Utwórz kontrakt
          </Button>
        </div>
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
    <RequireRole
      roles={["admin", "delivery_lead", "tac"]}
      fallback={
        <div className="max-w-3xl mx-auto p-6">
          <Link
            href="/contracts"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Wróć do listy
          </Link>
          <p className="mt-4 text-sm text-muted-foreground">
            Tworzenie kontraktów jest dostępne dla ról: admin, delivery lead, TAC.
          </p>
        </div>
      }
    >
      <NewContractForm />
    </RequireRole>
  );
}
