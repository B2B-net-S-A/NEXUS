"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Loader2, Save, Search } from "lucide-react";
import api, { contractsApi, extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";
import { CandidateRateScheduleFields } from "@/components/contracts/CandidateRateScheduleFields";
import {
  buildCandidateRateSchedule,
  scheduleHasBackwardsRange,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  ENGAGEMENT_MODEL_OPTIONS,
  PROLONGATION_OPTIONS,
  type EngagementModel,
  type ProlongationStatus,
  type RegisterContractRow,
} from "@/lib/contract-register";

type CandidateOption = {
  id: number;
  name: string;
  lastname: string;
  full_name: string;
  email?: string | null;
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clientId: number;
  clientName?: string;
  /** Gdy podany → tryb edycji; inaczej tworzenie nowego kontraktu. */
  contract?: RegisterContractRow | null;
  onSaved: () => void;
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const STATUS_OPTIONS = [
  { value: "draft", label: "Szkic" },
  { value: "active", label: "Aktywny" },
  { value: "ending", label: "Kończący się" },
  { value: "ended", label: "Zakończony" },
];

export function ContractRegisterDialog({
  open,
  onOpenChange,
  clientId,
  clientName,
  contract,
  onSaved,
}: Props) {
  const isEdit = !!contract;
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();

  // Etykieta pola „Numer projektu" zależy od nomenklatury klienta:
  // BNP i Bank Pocztowy → „Numer zamówienia", PFRON → „Numer zlecenia".
  // Dopasowanie po nazwie, spójne z detekcją w B2BContractGeneratorV2 (hasSpecialClauses).
  const clientNameLower = (clientName ?? "").toLowerCase();
  const projectCodeLabel =
    clientNameLower.includes("bnp") || clientNameLower.includes("pocztowy")
      ? "Numer zamówienia"
      : clientNameLower.includes("pfron") ||
          clientNameLower.includes("rehabilitacji osób niepełnosprawnych")
        ? "Numer zlecenia"
        : "Numer projektu";

  // ── Form state ──────────────────────────────────────────────────────────
  const [candidate, setCandidate] = useState<CandidateOption | null>(null);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateQuery, setCandidateQuery] = useState("");

  const [projectCode, setProjectCode] = useState("");
  const [projectName, setProjectName] = useState("");
  const [engagementModel, setEngagementModel] =
    useState<EngagementModel>("time_based");
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState("");
  const [hoursTotal, setHoursTotal] = useState("");
  const [hoursConsumed, setHoursConsumed] = useState("");
  const [prolongation, setProlongation] =
    useState<ProlongationStatus>("unknown");
  const [statusVal, setStatusVal] = useState("active");
  // Progresywna stawka kandydata — etapy „od–do" seedowane przy tworzeniu.
  // Tylko dla nowego kontraktu; edycja stawek istniejącego idzie przez aneksy.
  const [rateSchedule, setRateSchedule] = useState<RateScheduleRow[]>([
    { rate: "", effectiveFrom: "" },
  ]);
  const [error, setError] = useState("");

  // Reset / hydrate na otwarcie.
  useEffect(() => {
    if (!open) return;
    setError("");
    if (contract) {
      setCandidate(null);
      setProjectCode(contract.project_code ?? "");
      setProjectName(contract.project_name ?? "");
      setEngagementModel(contract.engagement_model ?? "time_based");
      setStartDate(contract.start_date?.slice(0, 10) ?? todayISO());
      setEndDate(contract.end_date?.slice(0, 10) ?? "");
      setHoursTotal(
        contract.hours_pool_total != null ? String(contract.hours_pool_total) : "",
      );
      setHoursConsumed(
        contract.hours_pool_consumed != null
          ? String(contract.hours_pool_consumed)
          : "",
      );
      setProlongation(contract.prolongation_status ?? "unknown");
      setStatusVal(contract.status ?? "active");
      setRateSchedule([{ rate: "", effectiveFrom: "" }]);
    } else {
      setCandidate(null);
      setCandidateQuery("");
      setProjectCode("");
      setProjectName("");
      setEngagementModel("time_based");
      setStartDate(todayISO());
      setEndDate("");
      setHoursTotal("");
      setHoursConsumed("");
      setProlongation("unknown");
      setStatusVal("active");
      setRateSchedule([{ rate: "", effectiveFrom: "" }]);
    }
  }, [open, contract]);

  const candidatesQuery = useQuery({
    queryKey: ["register-candidates", candidateQuery],
    queryFn: async () =>
      (
        await api.get<CandidateOption[]>("/api/cv-generator/candidates", {
          params: { q: candidateQuery, limit: 20 },
        })
      ).data,
    enabled: candidateOpen && !isEdit,
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      const isPool = engagementModel === "hours_pool";
      const payload: Record<string, unknown> = {
        project_code: projectCode.trim() || null,
        project_name: projectName.trim() || null,
        engagement_model: engagementModel,
        start_date: startDate,
        end_date: endDate || null,
        hours_pool_total: isPool && hoursTotal ? Number(hoursTotal) : null,
        hours_pool_consumed: isPool && hoursConsumed ? Number(hoursConsumed) : null,
        prolongation_status: prolongation,
        status: statusVal,
      };
      if (isEdit && contract) {
        return contractsApi.update(contract.id, payload);
      }
      // Etapy z wpisaną stawką → harmonogram; pusty „od" = data rozpoczęcia,
      // `effective_to` = wpisana data lub wyliczona (od–do) gdy pusta. Backend
      // wylicza bieżące `rate_candidate`.
      const schedule = buildCandidateRateSchedule(rateSchedule, startDate);
      return contractsApi.create({
        ...payload,
        client_id: clientId,
        candidate_id: candidate!.id,
        job_id: null,
        contract_type: "b2b",
        candidate_rate_schedule: schedule.length > 0 ? schedule : undefined,
      });
    },
    onSuccess: () => {
      showSuccess(isEdit ? "Kontrakt zaktualizowany" : "Kontrakt dodany");
      queryClient.invalidateQueries({ queryKey: ["client-register", clientId] });
      onSaved();
      onOpenChange(false);
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
    if (!isEdit && !candidate) {
      setError("Wybierz konsultanta.");
      return;
    }
    if (!startDate) {
      setError("Podaj datę rozpoczęcia.");
      return;
    }
    if (engagementModel === "hours_pool" && !hoursTotal) {
      setError("Dla puli godzin podaj budżet godzin.");
      return;
    }
    if (!isEdit) {
      const steps = rateSchedule
        .filter((r) => r.rate.trim() !== "")
        .map((r) => r.effectiveFrom || startDate);
      if (new Set(steps).size !== steps.length) {
        setError("Każdy etap stawki musi mieć inną datę „Obowiązuje od”.");
        return;
      }
      if (scheduleHasBackwardsRange(rateSchedule, startDate)) {
        setError('„Obowiązuje do” nie może być wcześniejsze niż „Obowiązuje od”.');
        return;
      }
    }
    saveMutation.mutate();
  };

  const candidateLabel = useMemo(() => {
    if (isEdit) return contract?.candidate_name ?? "—";
    return candidate ? candidate.full_name : "Wybierz konsultanta…";
  }, [isEdit, contract, candidate]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edytuj kontrakt" : "Nowy kontrakt"}
            {clientName ? (
              <span className="text-muted-foreground font-normal"> · {clientName}</span>
            ) : null}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Zmień dane projektu, okres / pulę godzin lub status przedłużenia."
              : "Powiąż konsultanta z projektem klienta i ustaw warunki."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="contents">
          <DialogBody className="space-y-4">
            {error && (
              <div className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Konsultant */}
            <div>
              <Label className="mb-1.5 block">
                Konsultant {!isEdit && <span className="text-destructive">*</span>}
              </Label>
              {isEdit ? (
                <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">
                  {candidateLabel}
                </div>
              ) : (
                <Popover open={candidateOpen} onOpenChange={setCandidateOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full justify-between font-normal"
                    >
                      <span className="flex items-center gap-2 truncate">
                        <Search className="h-4 w-4 shrink-0 opacity-60" />
                        {candidateLabel}
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
                        placeholder="Szukaj konsultanta…"
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
              )}
            </div>

            {/* Projekt */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="mb-1.5 block">{projectCodeLabel}</Label>
                <Input
                  value={projectCode}
                  onChange={(e) => setProjectCode(e.target.value)}
                  placeholder="np. NDA-2026-014"
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Nazwa projektu</Label>
                <Input
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="np. Core Banking Migration"
                />
              </div>
            </div>

            {/* Model rozliczeń */}
            <div>
              <Label className="mb-1.5 block">Model rozliczeń</Label>
              <Select
                value={engagementModel}
                onValueChange={(v) => setEngagementModel(v as EngagementModel)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ENGAGEMENT_MODEL_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label} — {o.hint}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Okres */}
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
            </div>

            {/* Pula godzin */}
            {engagementModel === "hours_pool" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label className="mb-1.5 block">
                    Pula godzin (budżet){" "}
                    <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    type="number"
                    min="0"
                    step="1"
                    value={hoursTotal}
                    onChange={(e) => setHoursTotal(e.target.value)}
                    placeholder="np. 200"
                  />
                </div>
                <div>
                  <Label className="mb-1.5 block">Wykorzystane godziny</Label>
                  <Input
                    type="number"
                    min="0"
                    step="1"
                    value={hoursConsumed}
                    onChange={(e) => setHoursConsumed(e.target.value)}
                    placeholder="0"
                  />
                </div>
              </div>
            )}

            {/* Stawka kandydata — progresja stawki w czasie (tylko nowy kontrakt).
                Edycja stawek istniejącego kontraktu idzie przez aneksy. */}
            {!isEdit && (
              <CandidateRateScheduleFields
                rows={rateSchedule}
                onChange={setRateSchedule}
                startDate={startDate}
              />
            )}

            {/* Statusy */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="mb-1.5 block">Status przedłużenia</Label>
                <Select
                  value={prolongation}
                  onValueChange={(v) => setProlongation(v as ProlongationStatus)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROLONGATION_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="mb-1.5 block">Status kontraktu</Label>
                <Select value={statusVal} onValueChange={setStatusVal}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STATUS_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Anuluj
            </Button>
            <Button type="submit" variant="primary" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isEdit ? "Zapisz zmiany" : "Dodaj kontrakt"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
