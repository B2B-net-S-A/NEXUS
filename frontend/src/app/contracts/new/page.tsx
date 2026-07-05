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
  Loader2,
  Save,
  Search,
  X,
} from "lucide-react";
import api, { contractsApi, extractErrorMsg } from "@/lib/api";
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
import type { RateScheduleRow } from "@/lib/contract-rate-schedule";

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
  const [frameworkRate, setFrameworkRate] = useState("");
  const [lineManager, setLineManager] = useState("");
  // Zużycie zamówienia (ilość + jednostka RBH/MD) — klienci per-zamówienie.
  const [orderConsumption, setOrderConsumption] = useState("");
  const [orderConsumptionUnit, setOrderConsumptionUnit] = useState("rbh");

  const [error, setError] = useState("");

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

  // ── Submit ──────────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: () => {
      // Rows with a numeric rate become schedule steps; an empty effective_from
      // defaults to the contract start date. Backend derives the current rate.
      // Stawki przyjmują grosze wpisane po polsku (przecinek) — parseDecimalInput.
      const schedule = rateSchedule
        .map((r) => ({
          rate: parseDecimalInput(r.rate),
          effective_from: r.effectiveFrom || startDate,
        }))
        .filter(
          (r): r is { rate: number; effective_from: string } => r.rate !== null,
        );
      const orderConsumptionVal = parseDecimalInput(orderConsumption);
      const payload: Record<string, unknown> = {
        candidate_id: candidate!.id,
        client_id: Number(clientId),
        job_id: selectedJobId,
        start_date: startDate,
        end_date: endDate || null,
        contract_type: contractType,
        status: statusVal,
        currency,
        rate_unit: rateUnit,
        billing_hours_per_month: Number(billingHours) || 160,
        rate_candidate: schedule.length === 0 ? null : undefined,
        candidate_rate_schedule: schedule.length > 0 ? schedule : undefined,
        rate_client: parseDecimalInput(rateClient),
        framework_rate: parseDecimalInput(frameworkRate),
        line_manager: lineManager.trim() || null,
        order_consumption: orderConsumptionVal,
        order_consumption_unit: orderConsumptionVal !== null ? orderConsumptionUnit : null,
      };
      return contractsApi.create(payload);
    },
    onSuccess: (res) => {
      showSuccess("Kontrakt utworzony");
      const id = (res?.data as { id?: number } | undefined)?.id;
      router.push(id ? `/contracts/${id}` : "/contracts");
    },
    onError: (err: unknown) => {
      const msg = extractErrorMsg(err);
      setError(msg);
      showError(msg);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!candidate) {
      setError("Wybierz kandydata.");
      return;
    }
    if (!clientId) {
      setError("Wybierz klienta.");
      return;
    }
    if (!startDate) {
      setError("Podaj datę rozpoczęcia.");
      return;
    }
    const steps = rateSchedule
      .filter((r) => r.rate.trim() !== "")
      .map((r) => r.effectiveFrom || startDate);
    if (new Set(steps).size !== steps.length) {
      setError(
        "Każda zmiana stawki musi mieć inną datę „Obowiązuje od”.",
      );
      return;
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
        <h1 className="text-2xl font-bold tracking-[-0.02em] text-foreground">
          Nowy kontrakt
        </h1>
        <p className="text-sm text-muted-foreground">
          Powiąż kandydata z klientem. Resztę szczegółów (dokumenty, draft umowy,
          aneksy) uzupełnisz po utworzeniu.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
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
              Kandydat i klient są wymagane. Ofertę możesz dobrać z rekrutacji
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
                        className="w-full justify-between font-normal"
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
                      className="w-[--radix-popover-trigger-width] p-0"
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
                        className="w-full justify-between font-normal"
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
                      className="w-[--radix-popover-trigger-width] p-0"
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
              </div>
            </div>

            {/* Rekrutacja (opcjonalna, daje job_id) */}
            <div>
              <Label className="mb-1.5 block">Oferta / rekrutacja (opcjonalnie)</Label>
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
                  onChange={(e) => setStartDate(e.target.value)}
                  required
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Data zakończenia</Label>
                <Input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Typ kontraktu</Label>
                <Select value={contractType} onValueChange={setContractType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="b2b">B2B</SelectItem>
                    <SelectItem value="uop">Umowa o pracę</SelectItem>
                    <SelectItem value="uzlecenie">Zlecenie</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="mb-1.5 block">Status</Label>
                <Select value={statusVal} onValueChange={setStatusVal}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="active">Aktywny</SelectItem>
                    <SelectItem value="ending">Kończący się</SelectItem>
                    <SelectItem value="ended">Zakończony</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

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
                <Label className="mb-1.5 block">Stawka z umowy ramowej</Label>
                <Input
                  type="text"
                  inputMode="decimal"
                  value={frameworkRate}
                  onChange={(e) =>
                    setFrameworkRate(sanitizeDecimalInput(e.target.value))
                  }
                  placeholder="np. 215,60"
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Stawka klienta</Label>
                <Input
                  type="text"
                  inputMode="decimal"
                  value={rateClient}
                  onChange={(e) =>
                    setRateClient(sanitizeDecimalInput(e.target.value))
                  }
                  placeholder="np. 215,60"
                />
              </div>
            </div>

            {/* Stawka kandydata — progresja stawki w czasie (etapy od–do) */}
            <CandidateRateScheduleFields
              rows={rateSchedule}
              onChange={setRateSchedule}
              startDate={startDate}
            />

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
