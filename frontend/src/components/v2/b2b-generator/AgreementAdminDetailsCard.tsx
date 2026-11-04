"use client";

/**
 * „Szczegóły administracyjne” w Generatorze (0524, decyzje Artura 26.10.2026)
 * — pod „Źródłem danych”, w umowie B2B i w umowie zlecenia.
 *
 * Rekruter i Delivery Lead są tylko do odczytu: to odbiorcy placementu
 * i premii po 168 h, liczeni tą samą regułą co automat premii (`/prefill` →
 * `admin`). Umowę może wygenerować każdy, ale gdy robi to ktoś inny niż
 * prowadzący, kafelek mówi wprost, że placement, premia i przypomnienia
 * zostają przy prowadzącym. Wpisuje się replacement i wymiar FTE.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronsUpDown,
  ClipboardList,
  Info,
  Lock,
  Search,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import {
  b2bGeneratorApi,
  type B2BAgreementAdminDefaults,
  type B2BPlacementPerson,
  type B2BReplaceableContract,
} from "@/lib/api";
import {
  adminDefaults,
  BONUS_HOURS,
  bonusBusinessDays,
  FTE_OPTIONS,
  fteLabel,
  isAdminComplete,
  monthsWorked,
  underWarranty,
  type AgreementAdminValue,
} from "@/lib/agreement-admin-details";
import { formatIsoDatePl } from "@/lib/date-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const STANDARD_BUSINESS_DAYS = bonusBusinessDays("1");

function contractorStatus(c: B2BReplaceableContract): string {
  if (c.status === "ended") return `zakończony ${formatIsoDatePl(c.end_date)}`;
  if (c.status === "ending") return `kończy się ${formatIsoDatePl(c.end_date)}`;
  return "aktywny";
}

function FieldLabel({
  children,
  hint,
  required = true,
  htmlFor,
}: {
  children: string;
  hint?: string;
  required?: boolean;
  htmlFor?: string;
}) {
  return (
    <Label
      className="mb-1.5 flex flex-wrap items-baseline gap-x-2"
      htmlFor={htmlFor}
    >
      <span>
        {children}
        {required ? <span className="text-destructive"> *</span> : null}
      </span>
      {hint ? (
        <span className="text-xs font-normal text-success-muted-foreground">
          {hint}
        </span>
      ) : null}
    </Label>
  );
}

/** Osoba z reguły premii — pokazana, nie wybierana. */
function PayeeField({
  label,
  person,
  emptyText,
  changeHint,
  changeHref,
}: {
  label: string;
  person: B2BPlacementPerson | null;
  emptyText: string;
  changeHint: string;
  changeHref?: string;
}) {
  return (
    <div>
      <FieldLabel hint={person?.source_label} required={false}>
        {label}
      </FieldLabel>
      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-md border border-border bg-muted/40 px-3 text-sm",
          !person && "text-muted-foreground",
        )}
        data-testid={`admin-payee-${label.startsWith("Rekruter") ? "recruiter" : "dl"}`}
      >
        <Lock
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          aria-hidden
        />
        <span className="truncate">{person?.name ?? emptyText}</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {changeHref ? (
          <Link href={changeHref} className="hover:underline">
            {changeHint}
          </Link>
        ) : (
          changeHint
        )}
      </p>
    </div>
  );
}

function OwnerNotice({
  owner,
  meId,
}: {
  owner: B2BPlacementPerson | null;
  meId: number | null;
}) {
  if (!owner) {
    return (
      <p className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        Nikt nie prowadzi tej osoby w rekrutacji (brak weryfikacji i przypisania
        „Prowadzi”). Bez tego nie będzie placementu ani premii rekrutera —
        poproś admina albo Head of Recruitment o przypisanie.
      </p>
    );
  }
  if (owner.user_id === meId) {
    return (
      <p className="flex items-start gap-2 rounded-md border border-success/20 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        Prowadzisz tę osobę: placement w Lidze i premia rekrutera po{" "}
        {BONUS_HOURS} h pracy są Twoje. Po wygenerowaniu wyślij umowę
        kandydatowi i dopilnuj podpisu.
      </p>
    );
  }
  return (
    <p className="flex items-start gap-2 rounded-md border border-info/20 bg-info-muted px-3 py-2 text-sm text-info-muted-foreground">
      <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      Tworzysz umowę za osobę prowadzącą: {owner.name}. Placement, premia
      rekrutera i przypomnienia o podpisie zostają przy niej. Dostanie dzwonek,
      że umowa jest gotowa.
    </p>
  );
}

function WarrantyNotice({ replaced }: { replaced: B2BReplaceableContract }) {
  if (!underWarranty(replaced)) return null;
  return (
    <p className="mt-2 flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      Gwarancja: kontrakt {replaced.name} trwał {monthsWorked(replaced)} mies. (
      {formatIsoDatePl(replaced.start_date)}–
      {formatIsoDatePl(replaced.end_date)}), krócej niż rok. Za ten placement
      premia DL się nie należy.
    </p>
  );
}

function ReplacedPicker({
  candidateId,
  clientId,
  clientName,
  value,
  onChange,
  invalid,
}: {
  candidateId: number | null;
  clientId: number | null;
  clientName: string | null;
  value: B2BReplaceableContract | null;
  onChange: (v: B2BReplaceableContract | null) => void;
  invalid: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [everywhere, setEverywhere] = useState(clientId === null);
  const debounced = useDebouncedValue(query.trim(), 300);

  const clientQuery = useQuery({
    queryKey: ["b2b-replacement-options", "client", clientId, candidateId],
    queryFn: () =>
      b2bGeneratorApi.replacementOptions({
        clientId,
        excludeCandidateId: candidateId,
      }),
    enabled: open && !everywhere && clientId !== null,
    staleTime: 60_000,
  });
  const globalQuery = useQuery({
    queryKey: ["b2b-replacement-options", "all", debounced, candidateId],
    queryFn: () =>
      b2bGeneratorApi.replacementOptions({
        q: debounced,
        excludeCandidateId: candidateId,
      }),
    enabled: open && everywhere && debounced.length >= 2,
  });

  const items = useMemo(() => {
    if (everywhere) return globalQuery.data ?? [];
    const needle = query.trim().toLocaleLowerCase("pl");
    return (clientQuery.data ?? []).filter(
      (c) => !needle || c.name.toLocaleLowerCase("pl").includes(needle),
    );
  }, [everywhere, globalQuery.data, clientQuery.data, query]);
  const active = everywhere ? globalQuery : clientQuery;

  if (value) {
    return (
      <div>
        <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-muted/40 py-1 pl-3 pr-1 text-sm">
          <span className="truncate font-medium">{value.name}</span>
          <span className="truncate text-xs text-muted-foreground">
            kontrakt #{value.contract_id}
            {value.client_name && value.client_id !== clientId
              ? ` · ${value.client_name}`
              : ""}
            {value.status !== "active" ? ` · ${contractorStatus(value)}` : ""}
          </span>
          <button
            type="button"
            aria-label={`Usuń ${value.name}`}
            className="rounded-full p-1 hover:bg-muted"
            onClick={() => onChange(null)}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </span>
        <WarrantyNotice replaced={value} />
      </div>
    );
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setQuery("");
          setEverywhere(clientId === null);
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-invalid={invalid || undefined}
          className={cn(
            "w-full justify-between font-normal",
            invalid && "border-destructive",
          )}
        >
          <span className="flex items-center gap-2 truncate text-muted-foreground">
            <Search className="h-4 w-4 shrink-0 opacity-60" />
            Wpisz nazwisko osoby, którą zastępuje…
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
            placeholder={
              everywhere ? "Nazwisko (min. 2 litery)…" : "Szukaj po nazwisku…"
            }
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <PickerQueryState
              isPending={active.isLoading}
              isError={active.isError}
              onRetry={() => void active.refetch()}
              loadingLabel="Szukam…"
              errorLabel="Nie udało się pobrać kontraktorów."
            />
            {active.isSuccess && <CommandEmpty>Nikogo takiego.</CommandEmpty>}
            <CommandGroup
              heading={
                everywhere
                  ? "Wszyscy kontraktorzy NEXUSA"
                  : `Kontraktorzy u klienta ${clientName ?? ""}`.trim()
              }
            >
              {items.map((c) => (
                <CommandItem
                  key={c.contract_id}
                  value={String(c.contract_id)}
                  onSelect={() => {
                    onChange(c);
                    setOpen(false);
                  }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{c.name}</span>
                      <span
                        className={cn(
                          "shrink-0 text-xs",
                          c.status === "active"
                            ? "text-muted-foreground"
                            : "text-warning-muted-foreground",
                        )}
                      >
                        {contractorStatus(c)}
                      </span>
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {everywhere && c.client_name ? `${c.client_name} · ` : ""}
                      {c.job_title ? `${c.job_title} · ` : ""}kontrakt #
                      {c.contract_id}
                    </div>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
            {!everywhere && (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    value="__everywhere"
                    onSelect={() => {
                      setEverywhere(true);
                    }}
                  >
                    <Search className="mr-2 h-4 w-4" />
                    Szukaj we wszystkich kontraktorach NEXUSA
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export interface AgreementAdminDetailsCardProps {
  candidateId: number | null;
  jobId: number | null;
  value: AgreementAdminValue;
  onChange: (value: AgreementAdminValue) => void;
  /** Pokaż brakujące pola na czerwono (po kliknięciu „Pobierz”). */
  showErrors?: boolean;
  /**
   * Para „kandydat:rekrutacja”, której wartości wczytano z zapisanej umowy
   * („Popraw umowę”) — dla niej kafelek nie nadpisuje ich podpowiedziami.
   */
  restoredPair?: string | null;
}

export function AgreementAdminDetailsCard({
  candidateId,
  jobId,
  value,
  onChange,
  showErrors = false,
  restoredPair = null,
}: AgreementAdminDetailsCardProps) {
  const meId = useAuthStore((s) =>
    s.user?.id != null ? Number(s.user.id) : null,
  );
  const hasRecruitment = candidateId !== null && jobId !== null;
  // Ten sam klucz i zapytanie co podpowiedzi formularza B2B — jedna odpowiedź.
  const prefillQuery = useQuery({
    queryKey: ["b2b-prefill", candidateId, jobId],
    queryFn: () => b2bGeneratorApi.prefill(candidateId!, jobId!),
    enabled: hasRecruitment,
  });
  const admin: B2BAgreementAdminDefaults | null =
    prefillQuery.data?.admin ?? null;

  // Po wybraniu (albo zmianie) rekrutacji od razu „Nie” i pełny etat (pola
  // nie czekają na serwer); zastępstwo z tytułu dochodzi z odpowiedzią
  // `/prefill`, o ile nikt jeszcze niczego w kafelku nie zmienił.
  const pairKey = hasRecruitment ? `${candidateId}:${jobId}` : null;
  const seededFor = useRef<string | null>(null);
  const titleCheckedFor = useRef<string | null>(null);
  const touched = useRef(false);
  const latestOnChange = useRef(onChange);
  latestOnChange.current = onChange;
  useEffect(() => {
    if (!pairKey || seededFor.current === pairKey) return;
    seededFor.current = pairKey;
    // Wybór wczytany z zapisanej umowy wygrywa z podpowiedziami.
    if (pairKey === restoredPair) {
      titleCheckedFor.current = pairKey;
      return;
    }
    touched.current = false;
    latestOnChange.current(adminDefaults(null));
  }, [pairKey, restoredPair]);
  useEffect(() => {
    if (!pairKey || titleCheckedFor.current === pairKey) return;
    if (!prefillQuery.isSuccess) return;
    titleCheckedFor.current = pairKey;
    const suggested = prefillQuery.data?.admin;
    if (suggested?.replacement_from_title && !touched.current) {
      latestOnChange.current(adminDefaults(suggested));
    }
  }, [pairKey, prefillQuery.isSuccess, prefillQuery.data]);

  const defaults = adminDefaults(admin);
  const fromTitle = Boolean(admin?.replacement_from_title);
  const set = (patch: Partial<AgreementAdminValue>) => {
    touched.current = true;
    onChange({ ...value, ...patch });
  };
  const missing = showErrors && hasRecruitment && !isAdminComplete(value);
  const changeOwnerHref = hasRecruitment
    ? `/jobs/${jobId}?candidate=${candidateId}`
    : undefined;

  return (
    <div
      className={cn(
        "rounded-xl border bg-card text-card-foreground shadow-sm",
        missing && "border-destructive",
      )}
      data-testid="agreement-admin-details"
    >
      <div className="flex flex-col gap-1.5 p-6 pb-4">
        <h3 className="flex items-center gap-2 text-base font-semibold leading-none">
          <ClipboardList className="h-4 w-4" aria-hidden /> Szczegóły
          administracyjne
        </h3>
        <p className="text-sm text-muted-foreground">
          Rekruter i Delivery Lead dostaną placement i premię po {BONUS_HOURS} h
          pracy kontraktora — wynikają z rekrutacji. Tu uzupełniasz replacement
          i wymiar etatu.
        </p>
      </div>
      <div className="space-y-4 px-6 pb-6">
        {hasRecruitment && prefillQuery.isError ? (
          <p className="text-sm text-destructive">
            Nie udało się pobrać osób z rekrutacji.{" "}
            <button
              type="button"
              className="underline"
              onClick={() => void prefillQuery.refetch()}
            >
              Spróbuj ponownie
            </button>
          </p>
        ) : null}
        {hasRecruitment && prefillQuery.isSuccess ? (
          <OwnerNotice owner={admin?.recruiter ?? null} meId={meId} />
        ) : null}
        <div className="grid gap-x-6 gap-y-4 @xl:grid-cols-2">
          <PayeeField
            label="Rekruter (prowadzi kandydata)"
            person={hasRecruitment ? (admin?.recruiter ?? null) : null}
            emptyText={
              !hasRecruitment
                ? "Uzupełni się po wybraniu rekrutacji"
                : prefillQuery.isSuccess
                  ? "Brak osoby prowadzącej"
                  : "Wczytywanie…"
            }
            changeHint="Zmiana: „Prowadzi” w panelu osoby (admin, Head of Recruitment)"
            changeHref={changeOwnerHref}
          />
          <PayeeField
            label="Delivery Lead (premia DL)"
            person={hasRecruitment ? (admin?.delivery_lead ?? null) : null}
            emptyText={
              !hasRecruitment
                ? "Uzupełni się po wybraniu rekrutacji"
                : prefillQuery.isSuccess
                  ? "Brak Delivery Leada u klienta"
                  : "Wczytywanie…"
            }
            changeHint="Zmiana: Delivery Lead w rekrutacji"
            changeHref={hasRecruitment ? `/jobs/${jobId}` : undefined}
          />

          <div>
            <FieldLabel
              hint={
                fromTitle && value.isReplacement === defaults.isReplacement
                  ? "z tytułu rekrutacji"
                  : undefined
              }
            >
              Replacement
            </FieldLabel>
            <div className="flex gap-2" role="group" aria-label="Replacement">
              {[true, false].map((option) => (
                <Button
                  key={String(option)}
                  type="button"
                  size="sm"
                  disabled={!hasRecruitment}
                  variant={
                    value.isReplacement === option ? "primary" : "outline"
                  }
                  aria-pressed={value.isReplacement === option}
                  onClick={() =>
                    set(
                      option
                        ? { isReplacement: true }
                        : { isReplacement: false, replaced: null },
                    )
                  }
                >
                  {option ? "Tak" : "Nie"}
                </Button>
              ))}
            </div>
          </div>

          <div>
            <FieldLabel
              hint={
                hasRecruitment && value.fte === "1"
                  ? "domyślnie pełny etat — rekrutacja nie ma pola FTE"
                  : undefined
              }
            >
              Wymiar FTE
            </FieldLabel>
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label="Wymiar FTE"
            >
              {FTE_OPTIONS.map((fte) => (
                <Button
                  key={fte}
                  type="button"
                  size="sm"
                  className="min-w-12"
                  disabled={!hasRecruitment}
                  variant={value.fte === fte ? "primary" : "outline"}
                  aria-pressed={value.fte === fte}
                  onClick={() => set({ fte })}
                >
                  {fteLabel(fte)}
                </Button>
              ))}
            </div>
            {value.fte && value.fte !== "1" ? (
              <p className="mt-1.5 text-xs text-muted-foreground">
                {BONUS_HOURS} h pracy przy {fteLabel(value.fte)} FTE to ok.{" "}
                {bonusBusinessDays(value.fte)} dni roboczych od startu, a nie{" "}
                {STANDARD_BUSINESS_DAYS} — premie przyjdą później.
              </p>
            ) : null}
          </div>

          {value.isReplacement ? (
            <div className="@xl:col-span-2">
              <FieldLabel
                hint={
                  value.replaced &&
                  defaults.replaced?.contract_id === value.replaced.contract_id
                    ? "dopasowane po nazwisku z tytułu — sprawdź"
                    : undefined
                }
              >
                Replacement za kogo
              </FieldLabel>
              <ReplacedPicker
                candidateId={candidateId}
                clientId={admin?.client_id ?? null}
                clientName={admin?.client_name ?? null}
                value={value.replaced}
                onChange={(replaced) => set({ replaced })}
                invalid={showErrors && !value.replaced}
              />
            </div>
          ) : null}
        </div>
        {missing ? (
          <p className="text-xs text-destructive" role="alert">
            Uzupełnij{" "}
            {value.isReplacement && !value.replaced
              ? "„Replacement za kogo”"
              : "replacement i wymiar FTE"}{" "}
            — bez tego nie wygenerujesz umowy.
          </p>
        ) : null}
      </div>
    </div>
  );
}
