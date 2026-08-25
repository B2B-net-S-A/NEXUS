"use client";

/**
 * „+ Dodaj kolejny projekt" — druga (trzecia…) umowa TEJ SAMEJ osoby u innego
 * klienta, z widoku istniejącego kontraktu. Po zapisie kontrakt staje się
 * wieloklientowy: lista grupuje wiersze po osobie, a szczegóły dostają
 * zakładki nazwane po kliencie.
 *
 * Reguły:
 * - Klient jest WYMAGANY (walidacja blokuje zapis, czerwone pole + opis).
 * - Rekrutacja opcjonalna — z listy rekrutacji WYBRANEGO KLIENTA (nowy projekt
 *   u nowego klienta zwykle nie ma jeszcze rekrutacji kandydata).
 * - Status „Aktywny" wymaga kompletu pól aktywacyjnych (daty, stawki, tryb
 *   pracy) — walidujemy lokalnie tym samym zestawem co backend
 *   (ACTIVATION_REQUIRED_FIELDS), a 409 z listą `missing` mapujemy na pola.
 * - Duplikat (ta sama osoba u tego samego klienta, po e-mailu) → komunikat
 *   z backendu pod polem klienta.
 * - Pola stawek renderują się tylko dla ról z dostępem finansowym (jak
 *   formularz „Nowy kontrakt") — bez nich aktywacja jest niemożliwa, więc
 *   status jest ograniczony do szkicu.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Check, ChevronsUpDown, Search, X } from "lucide-react";
import api, {
  contractsApi,
  extractErrorMsg,
  CONTRACT_FIELD_LABELS,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

type ClientOption = { id: number; name: string };
type JobOption = { id: number; title: string };

export interface AddProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string | null;
  /** Kontrakt, z którego otwarto dialog — źródło sensownych domyślnych. */
  baseContract: {
    id: number;
    client_id: number;
    contract_type: string;
    rate_unit: string;
    currency: string;
    billing_hours_per_month: number;
    work_mode: string | null;
  };
  /** Czy wołający może pisać pola finansowe (stawki) — jak „Nowy kontrakt". */
  canManageFinance: boolean;
}

type FieldErrors = Record<string, string>;

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AddProjectDialog({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  baseContract,
  canManageFinance,
}: AddProjectDialogProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();

  const [clientId, setClientId] = useState("");
  const [clientOpen, setClientOpen] = useState(false);
  const [clientQuery, setClientQuery] = useState("");
  const [jobId, setJobId] = useState("");
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState("");
  const [contractType, setContractType] = useState(baseContract.contract_type);
  const [workMode, setWorkMode] = useState(baseContract.work_mode ?? "");
  const [rateUnit, setRateUnit] = useState(baseContract.rate_unit || "monthly");
  const [rateCost, setRateCost] = useState("");
  const [rateRevenue, setRateRevenue] = useState("");
  // Bez dostępu finansowego nie da się podać stawek, a bez stawek nie ma
  // aktywacji — status startuje (i zostaje) jako szkic.
  const [statusVal, setStatusVal] = useState(
    canManageFinance ? "active" : "draft",
  );
  const [banner, setBanner] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  // Świeże otwarcie = czysty stan błędów; zeszłotygodniowy 409 nie ma prawa
  // witać użytkownika przy ponownym otwarciu dialogu.
  useEffect(() => {
    if (open) {
      setBanner("");
      setFieldErrors({});
    }
  }, [open]);

  const clearField = (field: string) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup-add-project"],
    queryFn: async () =>
      (await api.get<ClientOption[]>("/api/clients-lookup")).data,
    enabled: open,
  });

  // Rekrutacje powiązane z WYBRANYM klientem (ticket: pole opcjonalne).
  const jobsQuery = useQuery({
    queryKey: ["add-project-jobs", clientId],
    queryFn: async () => {
      const r = await api.get<{ items: JobOption[] }>("/api/jobs", {
        params: { client_id: clientId, page_size: 100 },
        paramsSerializer: { indexes: null },
      });
      return r.data.items ?? [];
    },
    enabled: open && !!clientId,
  });

  const filteredClients = useMemo(() => {
    const all = clientsQuery.data ?? [];
    const q = clientQuery.trim().toLowerCase();
    const matched = q ? all.filter((c) => c.name.toLowerCase().includes(q)) : all;
    return matched.slice(0, 50);
  }, [clientsQuery.data, clientQuery]);

  const selectedClientName = useMemo(
    () => clientsQuery.data?.find((c) => String(c.id) === clientId)?.name ?? null,
    [clientsQuery.data, clientId],
  );

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        candidate_id: candidateId,
        client_id: Number(clientId),
        job_id: jobId ? Number(jobId) : null,
        start_date: startDate,
        end_date: endDate || null,
        contract_type: contractType,
        work_mode: workMode || null,
        status: statusVal,
      };
      if (canManageFinance) {
        Object.assign(payload, {
          currency: baseContract.currency || "PLN",
          rate_unit: rateUnit,
          billing_hours_per_month: baseContract.billing_hours_per_month || 160,
          rate_candidate: parseDecimalInput(rateCost),
          rate_client: parseDecimalInput(rateRevenue),
        });
      }
      return contractsApi.create(payload);
    },
    onSuccess: (res) => {
      showSuccess("Dodano kolejny projekt — kontrakt jest teraz wieloklientowy");
      // Odśwież wszystkie powierzchnie, które właśnie stały się wieloklientowe.
      queryClient.invalidateQueries({ queryKey: ["contract", baseContract.id] });
      queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      const newId = (res?.data as { id?: number } | undefined)?.id;
      onOpenChange(false);
      if (newId) router.push(`/contracts/${newId}`);
    },
    onError: (err: unknown) => {
      // 409 lifecycle {missing: [...]} → podświetl konkretne pola;
      // 409 duplicate_contractor → komunikat pod polem klienta.
      if (err instanceof AxiosError && err.response) {
        const detail = (err.response.data as { detail?: unknown })?.detail;
        if (detail && typeof detail === "object" && !Array.isArray(detail)) {
          const d = detail as {
            code?: string;
            message?: string;
            missing?: string[];
          };
          if (d.code === "duplicate_contractor" && d.message) {
            setFieldErrors((prev) => ({ ...prev, client_id: d.message! }));
            setBanner(d.message);
            return;
          }
          if (Array.isArray(d.missing) && d.missing.length > 0) {
            const next: FieldErrors = {};
            for (const field of d.missing) {
              next[field] =
                `Uzupełnij pole: ${CONTRACT_FIELD_LABELS[field] ?? field}`;
            }
            setFieldErrors((prev) => ({ ...prev, ...next }));
            setBanner("Uzupełnij brakujące pola");
            return;
          }
        }
      }
      setBanner(extractErrorMsg(err));
    },
  });

  const handleSubmit = () => {
    setBanner("");
    const errors: FieldErrors = {};
    if (!clientId) {
      errors.client_id = "Wybierz klienta — pole jest wymagane.";
    }
    if (!startDate) {
      errors.start_date = "Podaj datę rozpoczęcia nowego projektu.";
    }
    if (statusVal === "active") {
      // Lustro ACTIVATION_REQUIRED_FIELDS — lepiej odmówić tu, po polsku,
      // niż odsyłać użytkownika po 409 z serwera.
      if (!endDate) {
        errors.end_date = "Status „Aktywny” wymaga daty zakończenia.";
      }
      if (!workMode) {
        errors.work_mode = "Status „Aktywny” wymaga trybu pracy.";
      }
      if (canManageFinance && parseDecimalInput(rateCost) == null) {
        errors.rate_candidate = "Status „Aktywny” wymaga stawki kosztowej.";
      }
      if (canManageFinance && parseDecimalInput(rateRevenue) == null) {
        errors.rate_client = "Status „Aktywny” wymaga stawki przychodowej.";
      }
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setBanner("Uzupełnij brakujące pola");
      return;
    }
    createMutation.mutate();
  };

  const fieldError = (field: string) =>
    fieldErrors[field] ? (
      <p className="mt-1 text-xs text-destructive">{fieldErrors[field]}</p>
    ) : null;

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        // Nie zamykaj w trakcie zapisu — zamknięcie w połowie mutacji
        // zostawiłoby użytkownika bez informacji o wyniku (lustro modala
        // usuwania kontraktu).
        if (!createMutation.isPending) onOpenChange(next);
      }}
      title="Dodaj kolejny projekt"
      description={
        candidateName
          ? `Nowa umowa dla: ${candidateName}. Po zapisie pojawi się osobna zakładka nazwana po kliencie.`
          : "Nowa umowa tej samej osoby u kolejnego klienta."
      }
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={createMutation.isPending}
            onClick={handleSubmit}
          >
            Dodaj projekt
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {banner && (
          <div className="rounded-lg bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {banner}
          </div>
        )}

        {/* Klient (wymagany) */}
        <div>
          <Label className="mb-1.5 block">
            Klient <span className="text-destructive">*</span>
          </Label>
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
                          setJobId("");
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
                        {c.id === baseContract.client_id && (
                          <span className="ml-auto text-xs text-muted-foreground">
                            obecny klient
                          </span>
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
          {fieldError("client_id")}
        </div>

        {/* Rekrutacja (opcjonalna, z listy rekrutacji klienta) */}
        <div>
          <Label className="mb-1.5 block">Rekrutacja (opcjonalnie)</Label>
          <div className="flex gap-2">
            <Select value={jobId} onValueChange={setJobId} disabled={!clientId}>
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    clientId
                      ? "— (możesz zostawić puste)"
                      : "Najpierw wybierz klienta"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {(jobsQuery.data ?? []).map((j) => (
                  <SelectItem key={j.id} value={String(j.id)}>
                    {j.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {jobId ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title="Wyczyść rekrutację"
                onClick={() => setJobId("")}
              >
                <X className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        </div>

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
              <span className="text-xs text-muted-foreground">
                (puste = bezterminowo)
              </span>
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
            <Label className="mb-1.5 block">Tryb pracy</Label>
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
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <Label className="mb-1.5 block">Stawka kosztowa</Label>
              <Input
                type="text"
                inputMode="decimal"
                value={rateCost}
                onChange={(e) => {
                  setRateCost(sanitizeDecimalInput(e.target.value));
                  clearField("rate_candidate");
                }}
                placeholder="np. 125,00"
                className={cn(fieldErrors.rate_candidate && "border-destructive")}
              />
              {fieldError("rate_candidate")}
            </div>
            <div>
              <Label className="mb-1.5 block">Stawka przychodowa</Label>
              <Input
                type="text"
                inputMode="decimal"
                value={rateRevenue}
                onChange={(e) => {
                  setRateRevenue(sanitizeDecimalInput(e.target.value));
                  clearField("rate_client");
                }}
                placeholder="np. 175,00"
                className={cn(fieldErrors.rate_client && "border-destructive")}
              />
              {fieldError("rate_client")}
            </div>
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
          </div>
        )}

        <div>
          <Label className="mb-1.5 block">Status</Label>
          <Select
            value={statusVal}
            onValueChange={setStatusVal}
            disabled={!canManageFinance}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="draft">Szkic</SelectItem>
              {canManageFinance && (
                <SelectItem value="active">Aktywny</SelectItem>
              )}
            </SelectContent>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">
            {canManageFinance
              ? "Szkic możesz aktywować później z widoku kontraktu."
              : "Stawki wymagane do aktywacji uzupełnia administrator — projekt zapisze się jako szkic."}
          </p>
        </div>
      </div>
    </AppModal>
  );
}
