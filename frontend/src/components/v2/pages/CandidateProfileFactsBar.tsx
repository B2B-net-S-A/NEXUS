"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Briefcase,
  Globe2,
  CalendarClock,
  Check,
  ChevronsUpDown,
  Languages,
  Loader2,
  LockKeyhole,
  MapPin,
  PencilLine,
  Plus,
  RefreshCw,
  Trash2,
  WalletCards,
} from "lucide-react";
import { activeProcessesQueryKey, rateChangesApi } from "@/lib/rate-change";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  candidateFactsApi,
  candidateProfileApi,
  extractErrorMsg,
  type CandidateLanguageCefrLevel,
  type CandidateLanguageInput,
  type CandidateLanguagesResponse,
  type CandidateProfileRate,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import {
  B2B_OPTIONS,
  WORK_TIME_OPTIONS,
  callFactItems,
  callFactsDraft,
  callFactsPatch,
  callFactsVerifiedLabel,
  rateFactLabel,
  type CallFactsDraft,
  type CandidateCallFacts,
} from "@/lib/candidate-call-facts";
import {
  WORK_MODES,
  WORK_MODE_LABELS,
  formatWorkMode,
  profileWorkMode,
  workModeValidationError,
  type WorkMode,
} from "@/lib/work-mode";
import { useCapability } from "@/hooks/useCapability";
import {
  foldLanguageName,
  isListedLanguageCode,
  languageLabel as listedLanguageLabel,
  otherLanguageCode,
  searchLanguageOptions,
} from "@/lib/candidate-languages";
import { formatCandidateLocation } from "./candidate-list-helpers";
import { invalidateCandidateMutation } from "./candidate-cache";
import { candidateQueryKeys, candidateViewerScopeKey } from "./candidate-query-keys";
import {
  useCandidateCardOverview,
  type CandidateCardFact,
} from "@/lib/api/candidateCards";
import {
  cardFactLine,
  cardFactOrigin,
  cardFactTitle,
  cardFactsByKey,
} from "@/lib/candidate-card-facts";
import { useAuthStore } from "@/store/auth";
import {
  rateFromText,
  rateSecondLine,
  toAmount,
  type RateFromFields,
} from "@/lib/candidate-rate";
import { RateHistoryDialog } from "@/components/v2/candidate-profile/RateHistoryDialog";
import api from "@/lib/api";
import {
  AVAILABILITY_STATUS_OPTIONS,
  NOTICE_PERIOD_UNITS,
  availabilityDraft,
  availabilityDraftError,
  availabilityPatch,
  type AvailabilityDraft,
} from "@/lib/candidate-availability-edit";

const CEFR_LEVELS: CandidateLanguageCefrLevel[] = [
  "A1",
  "A2",
  "B1",
  "B2",
  "C1",
  "C2",
];

const AVAILABILITY_LABELS: Record<string, string> = {
  actively_looking: "Aktywnie szuka",
  open_to_offers: "Otwarty/a na oferty",
  not_looking: "Nie szuka",
  unknown: "Nie ustalono",
};

const LANGUAGE_CODE_RE = /^[a-z][a-z0-9-]{1,15}$/;

/** Podpowiedzi pola „Hub” (dawniej panel „Lokalizacja” w szczegółach profilu). */
const HUB_SUGGESTIONS = [
  "Warszawa",
  "Kraków",
  "Wrocław",
  "Trójmiasto",
  "Poznań",
  "Śląsk",
  "Łódź",
  "Lublin",
  "Rzeszów",
  "Remote",
];

/** Wiersz okna „Języki kandydata” — `other` = język spoza listy („Inny…”). */
type LanguageRow = CandidateLanguageInput & { other: boolean };

/**
 * Wybór języka z JEDNEJ listy (`LANGUAGE_OPTIONS`) z wyszukiwaniem. Kod
 * wynika z wyboru — pola „Kod” już nie ma. „Inny…” odsłania pole nazwy
 * (kod wyprowadzony z nazwy, serwer przyjmuje go tylko z `other: true`).
 */
function LanguagePicker({
  id,
  row,
  onPick,
}: {
  id: string;
  row: LanguageRow;
  onPick: (option: { code: string; label: string } | "other") => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const options = React.useMemo(() => searchLanguageOptions(query), [query]);
  const selectedLabel = row.other
    ? "Inny…"
    : row.language_code
      ? isListedLanguageCode(row.language_code)
        ? listedLanguageLabel(row.language_code)
        : row.language_name || row.language_code
      : null;
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="mt-1 min-h-11 w-full justify-between font-normal"
        >
          <span className={cn("truncate", !selectedLabel && "text-muted-foreground")}>
            {selectedLabel ?? "Wybierz język…"}
          </span>
          <ChevronsUpDown className="size-4 opacity-50" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[260px] p-0">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Szukaj języka…"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>Brak na liście — wybierz „Inny…”.</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.code}
                  value={option.code}
                  onSelect={() => {
                    onPick(option);
                    setOpen(false);
                  }}
                >
                  <Check
                    aria-hidden="true"
                    className={cn(
                      "mr-2 size-4",
                      !row.other && row.language_code === option.code
                        ? "opacity-100"
                        : "opacity-0",
                    )}
                  />
                  {option.label}
                </CommandItem>
              ))}
              <CommandItem
                value="__other__"
                onSelect={() => {
                  onPick("other");
                  setOpen(false);
                }}
              >
                <Check
                  aria-hidden="true"
                  className={cn("mr-2 size-4", row.other ? "opacity-100" : "opacity-0")}
                />
                Inny…
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

type LanguagesQueryData = {
  data: CandidateLanguagesResponse;
  etag: string | null;
};

type RateQueryData = {
  data: CandidateProfileRate;
  etag: string | null;
};

interface CandidateProfileFactsBarProps {
  /**
   * `column` (od 04.10.2026) = karta „Podsumowanie” w lewej kolumnie profilu:
   * fakty jeden pod drugim, ołówki dopiero po „Edytuj”, a pod faktami treść
   * z `children` („W skrócie”, „Ustalenia z notatek”). `grid` = dawny pasek
   * kafelków (zostaje dla wąskich wariantów i testów).
   */
  layout?: "grid" | "column";
  children?: React.ReactNode;
  candidate: {
    id: number;
    city?: string | null;
    country?: string | null;
    region?: string | null;
    hub_city?: string | null;
    location?: string | null;
    availability_status?: string | null;
    availability_date?: string | null;
    notice_period?: number | null;
    notice_period_unit?: string | null;
    preferences?: unknown;
    max_onsite_days_per_week?: number | null;
  } & CandidateCallFacts &
    RateFromFields;
}

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (
    error as {
      response?: { status?: number };
    }
  ).response?.status ?? null;
}

function availabilityValue(
  candidate: CandidateProfileFactsBarProps["candidate"],
): string {
  const status =
    AVAILABILITY_LABELS[candidate.availability_status ?? "unknown"] ??
    "Nie ustalono";
  if (candidate.availability_date) {
    // Nieznany status + data: sama data mówi wszystko („Nie ustalono · od …”
    // czytało się jak sprzeczność).
    if ((candidate.availability_status ?? "unknown") === "unknown") {
      return `Od ${formatDate(candidate.availability_date)}`;
    }
    return `${status} · od ${formatDate(candidate.availability_date)}`;
  }
  if (candidate.notice_period != null) {
    const unit =
      candidate.notice_period_unit === "months"
        ? "mies."
        : candidate.notice_period_unit === "weeks"
          ? "tyg."
          : "dni";
    return `${status} · ${candidate.notice_period} ${unit}`;
  }
  return status;
}

function formatRate(amount: string | null): string {
  if (amount == null) return "Nie uzupełniono";
  const parsed = Number(amount);
  if (!Number.isFinite(parsed)) return "Nie uzupełniono";
  return `${new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: parsed % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(parsed)} PLN netto/h`;
}

function languageLabel(language: CandidateLanguagesResponse["languages"][number]) {
  if (language.is_native) return `${language.language_name} · ojczysty`;
  if (language.cefr_level) {
    return `${language.language_name} · ${language.cefr_level}`;
  }
  return `${language.language_name} · poziom nieznany`;
}

/**
 * Linia pod wartością z profilu: co i kiedy ustalono w rozmowie (karta
 * rekomendacji). Wartość z profilu zostaje główną — po niej filtruje lista.
 */
function cardOrigin(
  fact: CandidateCardFact | undefined,
  profileAmount?: number | null,
): { text: string; title: string } | undefined {
  const text = cardFactLine(fact, profileAmount);
  return fact && text ? { text, title: cardFactTitle(fact) } : undefined;
}

/**
 * Układ faktów: `column` = wiersze karty „Podsumowanie” (ołówki tylko w trybie
 * edycji), inaczej kafelki paska.
 */
const FactsLayoutContext = React.createContext<{ column: boolean; editing: boolean }>({
  column: false,
  editing: true,
});

function FactShell({
  icon,
  label,
  children,
  action,
  actionAlways,
  muted,
  origin,
  footer,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  /** Akcja widoczna także poza trybem edycji (np. „Ponów” po awarii). */
  actionAlways?: boolean;
  muted?: boolean;
  /** Źródło i data ustalenia z rozmowy (karta rekomendacji). */
  origin?: { text: string; title: string };
  /** Akcja pod opisem źródła (np. „Historia stawek”). */
  footer?: React.ReactNode;
}) {
  const layout = React.useContext(FactsLayoutContext);
  if (layout.column) {
    const showAction = actionAlways || layout.editing;
    return (
      <div className="flex min-w-0 items-start gap-2 py-2.5 md:max-2xl:py-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">{label}</p>
          <div
            className={cn(
              "min-w-0 break-words text-sm font-semibold leading-5 text-foreground",
              muted && "font-normal text-muted-foreground",
            )}
          >
            {children}
          </div>
          {origin ? (
            <p
              className="mt-0.5 break-words text-[11px] leading-4 text-muted-foreground"
              title={origin.title}
              data-fact-origin
            >
              {origin.text}
            </p>
          ) : null}
          {footer}
        </div>
        {showAction ? action : null}
      </div>
    );
  }
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card p-3 md:max-2xl:p-2">
      <div className="flex min-h-11 items-start gap-2.5">
        <span
          aria-hidden="true"
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary"
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <div
            className={cn(
              // `break-words`, nie `[overflow-wrap:anywhere]`: „anywhere” zeruje
              // minimalną szerokość słowa, więc w wąskim kafelku tekst łamał się
              // litera po literze („Nie / uz / up / eł…”, test 23.09.2026).
              "mt-0.5 min-w-0 break-words text-sm font-medium leading-5 text-foreground",
              muted && "font-normal text-muted-foreground",
            )}
          >
            {children}
          </div>
          {origin ? (
            <p
              className="mt-0.5 break-words text-[11px] leading-4 text-muted-foreground"
              title={origin.title}
              data-fact-origin
            >
              {origin.text}
            </p>
          ) : null}
          {footer}
        </div>
        {action}
      </div>
    </div>
  );
}

function FactLoading({ label }: { label: string }) {
  return (
    <FactShell
      label={label}
      icon={<Loader2 aria-hidden="true" className="size-4 animate-spin" />}
      muted
    >
      <span role="status">Ładowanie…</span>
    </FactShell>
  );
}

function LanguagesEditor({
  open,
  onOpenChange,
  candidateId,
  queryData,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  queryData: LanguagesQueryData;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = React.useState<LanguageRow[]>([]);
  const [validationError, setValidationError] = React.useState<string | null>(
    null,
  );
  const [conflictMessage, setConflictMessage] = React.useState<string | null>(
    null,
  );
  const [mutationError, setMutationError] = React.useState<string | null>(null);
  const wasOpenRef = React.useRef(false);

  React.useEffect(() => {
    if (open && !wasOpenRef.current) {
      setRows(
        queryData.data.languages.map((language) => ({
          language_code: language.language_code,
          language_name: language.language_name,
          cefr_level: language.cefr_level,
          is_native: language.is_native,
          is_level_unknown: language.is_level_unknown,
          // Zapisany kod spoza listy (np. z CV) zostaje „Innym…” z tym samym
          // kodem, dopóki ktoś nie zmieni nazwy.
          other: !isListedLanguageCode(language.language_code),
        })),
      );
      setValidationError(null);
      setConflictMessage(null);
      setMutationError(null);
    }
    wasOpenRef.current = open;
  }, [open, queryData.data.languages]);

  const mutation = useMutation({
    mutationFn: (languages: CandidateLanguageInput[]) => {
      if (!queryData.etag) {
        throw new Error("Brak wersji danych. Odśwież języki i spróbuj ponownie.");
      }
      return candidateFactsApi.updateLanguages(
        candidateId,
        languages,
        queryData.etag,
      );
    },
    onSuccess: (result) => {
      setMutationError(null);
      queryClient.setQueryData(
        candidateQueryKeys.languages(candidateId),
        result,
      );
      onOpenChange(false);
      showSuccess("Języki zapisane");
    },
    onError: (error) => {
      const status = requestStatus(error);
      if (status === 409 || status === 412 || status === 428) {
        queryClient.invalidateQueries({
          queryKey: candidateQueryKeys.languages(candidateId),
        });
        const message =
          "Dane zmieniły się w innym oknie. Zachowaliśmy Twój draft i pobieramy aktualną wersję — sprawdź go przed ponownym zapisem.";
        setMutationError(null);
        setConflictMessage(message);
        showError(message);
        return;
      }
      const message =
        extractErrorMsg(error) || "Nie udało się zapisać języków";
      setMutationError(message);
      showError(message);
    },
  });

  const updateRow = (index: number, update: Partial<LanguageRow>) => {
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...update } : row,
      ),
    );
  };

  const save = () => {
    setMutationError(null);
    const normalized = rows
      .map((row) => ({
        ...row,
        language_name: row.language_name.trim(),
        language_code: row.language_code.trim().toLocaleLowerCase(),
      }))
      .filter((row) => row.language_name || row.language_code);
    const missingName = normalized.find((row) => !row.language_name);
    if (missingName) {
      setValidationError(
        missingName.other
          ? "Wpisz nazwę języka spoza listy albo usuń pusty wiersz."
          : "Wybierz język z listy albo usuń pusty wiersz.",
      );
      return;
    }
    const invalidCode = normalized.find(
      (row) => !LANGUAGE_CODE_RE.test(row.language_code),
    );
    if (invalidCode) {
      setValidationError(
        `Nazwa „${invalidCode.language_name}” jest za krótka albo nie zawiera liter — wpisz pełną nazwę języka.`,
      );
      return;
    }
    const nameKeys = normalized.map((row) => foldLanguageName(row.language_name));
    const codeKeys = normalized.map((row) => row.language_code);
    if (
      new Set(nameKeys).size !== nameKeys.length ||
      new Set(codeKeys).size !== codeKeys.length
    ) {
      setValidationError("Każdy język może wystąpić tylko raz.");
      return;
    }
    setValidationError(null);
    setConflictMessage(null);
    mutation.mutate(normalized);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="lg"
        aria-describedby="candidate-languages-dialog-description"
      >
        <DialogHeader>
          <DialogTitle>Języki kandydata</DialogTitle>
          <DialogDescription id="candidate-languages-dialog-description">
            Poziom CEFR podawaj tylko wtedy, gdy jest potwierdzony. Język
            ojczysty jest osobnym faktem.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          {rows.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
              Brak języków. Dodaj pierwszy wpis.
            </div>
          ) : null}
          {rows.map((row, index) => (
            <fieldset
              key={index}
              className="rounded-lg border border-border p-3"
            >
              <legend className="sr-only">Język {index + 1}</legend>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem_auto]">
                <div>
                  <Label htmlFor={`candidate-language-${index}`}>Język</Label>
                  <LanguagePicker
                    id={`candidate-language-${index}`}
                    row={row}
                    onPick={(picked) => {
                      if (picked === "other") {
                        updateRow(index, {
                          other: true,
                          language_name: row.other ? row.language_name : "",
                          language_code: row.other ? row.language_code : "",
                        });
                        return;
                      }
                      updateRow(index, {
                        other: false,
                        language_code: picked.code,
                        language_name: picked.label,
                      });
                    }}
                  />
                  {row.other ? (
                    <div className="mt-2">
                      <Label htmlFor={`candidate-language-other-${index}`}>
                        Nazwa języka
                      </Label>
                      <Input
                        id={`candidate-language-other-${index}`}
                        className="mt-1 min-h-11"
                        value={row.language_name}
                        onChange={(event) =>
                          updateRow(index, {
                            language_name: event.target.value,
                            language_code: otherLanguageCode(event.target.value),
                          })
                        }
                        placeholder="np. kataloński"
                        autoComplete="off"
                      />
                    </div>
                  ) : null}
                </div>
                <div>
                  <Label htmlFor={`candidate-language-level-${index}`}>
                    Poziom
                  </Label>
                  <select
                    id={`candidate-language-level-${index}`}
                    className="mt-1 h-11 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring"
                    value={
                      row.is_native
                        ? "native"
                        : row.cefr_level ?? "unknown"
                    }
                    onChange={(event) => {
                      const value = event.target.value;
                      if (value === "native") {
                        updateRow(index, {
                          is_native: true,
                          is_level_unknown: false,
                          cefr_level: null,
                        });
                      } else if (value === "unknown") {
                        updateRow(index, {
                          is_native: false,
                          is_level_unknown: true,
                          cefr_level: null,
                        });
                      } else {
                        updateRow(index, {
                          is_native: false,
                          is_level_unknown: false,
                          cefr_level: value as CandidateLanguageCefrLevel,
                        });
                      }
                    }}
                  >
                    <option value="unknown">Nieznany</option>
                    {CEFR_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                    <option value="native">Ojczysty</option>
                  </select>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="min-h-11 min-w-11 self-end text-muted-foreground hover:text-destructive"
                  aria-label={`Usuń język ${row.language_name || index + 1}`}
                  onClick={() =>
                    setRows((current) =>
                      current.filter((_, rowIndex) => rowIndex !== index),
                    )
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </fieldset>
          ))}
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() =>
              setRows((current) => [
                ...current,
                {
                  language_code: "",
                  language_name: "",
                  cefr_level: null,
                  is_native: false,
                  is_level_unknown: true,
                  other: false,
                },
              ])
            }
          >
            <Plus className="size-4" />
            Dodaj język
          </Button>
          {validationError ? (
            <p role="alert" className="text-sm text-destructive">
              {validationError}
            </p>
          ) : null}
          {conflictMessage ? (
            <p
              role="alert"
              className="rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              {conflictMessage}
            </p>
          ) : null}
          {mutationError ? (
            <p
              id="candidate-languages-mutation-error"
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
            >
              {mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            onClick={save}
          >
            Zapisz języki
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LocationEditor({
  open,
  onOpenChange,
  candidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidate: CandidateProfileFactsBarProps["candidate"];
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [city, setCity] = React.useState("");
  const [country, setCountry] = React.useState("");
  const [region, setRegion] = React.useState("");
  const [hub, setHub] = React.useState("");
  const [mutationError, setMutationError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setCity(candidate.city ?? "");
    setCountry(candidate.country ?? "");
    setRegion(candidate.region ?? "");
    setHub(candidate.hub_city ?? "");
    setMutationError(null);
  }, [candidate.city, candidate.country, candidate.region, candidate.hub_city, open]);

  // Tylko zmienione pola — każde zapisane pole dostaje ręczną blokadę przed
  // kolejnym odczytem CV, więc nietknięty region nie może jej dostać „przy okazji”.
  const locationPatch = () => {
    const next = {
      city: city.trim() || null,
      country: country.trim().toUpperCase() || null,
      region: region.trim() || null,
      hub_city: hub.trim() || null,
    };
    const before = {
      city: candidate.city?.trim() || null,
      country: candidate.country?.trim().toUpperCase() || null,
      region: candidate.region?.trim() || null,
      hub_city: candidate.hub_city?.trim() || null,
    };
    return Object.fromEntries(
      (Object.keys(next) as Array<keyof typeof next>)
        .filter((key) => next[key] !== before[key])
        .map((key) => [key, next[key]]),
    );
  };

  const mutation = useMutation({
    // Bez zmian nic nie wysyłamy — serwer odpowiedziałby 422 „No location fields”.
    mutationFn: async () => {
      const patch = locationPatch();
      if (Object.keys(patch).length === 0) return "unchanged" as const;
      await candidateProfileApi.updateLocation(candidate.id, patch);
      return "saved" as const;
    },
    onSuccess: (result) => {
      setMutationError(null);
      if (result === "unchanged") {
        onOpenChange(false);
        return;
      }
      // Runda 10 (R10-N15-10): lista (miasto pod nazwiskiem) i podgląd też.
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      onOpenChange(false);
      showSuccess("Lokalizacja zapisana");
    },
    onError: (error) => {
      const message =
        extractErrorMsg(error) || "Nie udało się zapisać lokalizacji";
      setMutationError(message);
      showError(message);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="candidate-location-dialog-description">
        <DialogHeader>
          <DialogTitle>Lokalizacja kandydata</DialogTitle>
          <DialogDescription id="candidate-location-dialog-description">
            Zapisz wyłącznie potwierdzone miejsce zamieszkania. Ręczna korekta
            ma pierwszeństwo przed kolejnym parsowaniem CV.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <div>
            <Label htmlFor="candidate-profile-city">Miasto</Label>
            <Input
              id="candidate-profile-city"
              className="mt-1 min-h-11"
              value={city}
              onChange={(event) => setCity(event.target.value)}
              placeholder="np. Warszawa"
            />
          </div>
          <div>
            <Label htmlFor="candidate-profile-country">Kraj (ISO-2)</Label>
            <Input
              id="candidate-profile-country"
              className="mt-1 min-h-11 uppercase"
              value={country}
              onChange={(event) =>
                setCountry(event.target.value.slice(0, 2).toUpperCase())
              }
              placeholder="PL"
              maxLength={2}
            />
          </div>
          <div>
            <Label htmlFor="candidate-profile-region">Region / województwo</Label>
            <Input
              id="candidate-profile-region"
              className="mt-1 min-h-11"
              value={region}
              onChange={(event) => setRegion(event.target.value)}
              placeholder="np. mazowieckie"
            />
          </div>
          <div>
            <Label htmlFor="candidate-profile-hub">Hub</Label>
            <Input
              id="candidate-profile-hub"
              className="mt-1 min-h-11"
              value={hub}
              onChange={(event) => setHub(event.target.value)}
              placeholder="np. Warszawa"
              list="candidate-profile-hub-suggestions"
            />
            <datalist id="candidate-profile-hub-suggestions">
              {HUB_SUGGESTIONS.map((suggestion) => (
                <option key={suggestion} value={suggestion} />
              ))}
            </datalist>
          </div>
          {mutationError ? (
            <p
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere] sm:col-span-2"
            >
              {mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            onClick={() => {
              setMutationError(null);
              if (Object.keys(locationPatch()).length === 0) {
                onOpenChange(false);
                return;
              }
              mutation.mutate();
            }}
          >
            Zapisz lokalizację
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AvailabilityEditor({
  open,
  onOpenChange,
  candidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidate: CandidateProfileFactsBarProps["candidate"];
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [initial, setInitial] = React.useState<AvailabilityDraft>(() =>
    availabilityDraft(candidate),
  );
  const [draft, setDraft] = React.useState<AvailabilityDraft>(initial);
  const [mutationError, setMutationError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const fresh = availabilityDraft(candidate);
    setInitial(fresh);
    setDraft(fresh);
    setMutationError(null);
    // Stan z chwili otwarcia — zapis wysyła tylko różnice względem niego.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const validationError = availabilityDraftError(draft);
  const patch = availabilityPatch(initial, draft);
  const mutation = useMutation({
    mutationFn: () => api.patch(`/api/candidates/${candidate.id}`, patch),
    onSuccess: () => {
      setMutationError(null);
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      onOpenChange(false);
      showSuccess("Dostępność zapisana");
    },
    onError: (error) => {
      const message = extractErrorMsg(error) || "Nie udało się zapisać dostępności";
      setMutationError(message);
      showError(message);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="candidate-availability-dialog-description">
        <DialogHeader>
          <DialogTitle>Dostępność kandydata</DialogTitle>
          <DialogDescription id="candidate-availability-dialog-description">
            Od kiedy kandydat może zacząć i czy szuka teraz pracy. Po tych
            polach filtruje lista kandydatów.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label htmlFor="candidate-availability-status">Czy szuka pracy</Label>
            <select
              id="candidate-availability-status"
              className="mt-1 min-h-11 w-full rounded-lg border border-border bg-card px-3 text-sm"
              value={draft.status}
              onChange={(event) => setDraft((d) => ({ ...d, status: event.target.value }))}
            >
              {AVAILABILITY_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="candidate-availability-date">Dostępny od</Label>
            <Input
              id="candidate-availability-date"
              type="date"
              className="mt-1 min-h-11"
              value={draft.date}
              onChange={(event) => setDraft((d) => ({ ...d, date: event.target.value }))}
            />
          </div>
          <div>
            <Label htmlFor="candidate-notice-period">Okres wypowiedzenia</Label>
            <div className="mt-1 grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-2">
              <Input
                id="candidate-notice-period"
                inputMode="numeric"
                className="min-h-11"
                value={draft.noticePeriod}
                onChange={(event) =>
                  setDraft((d) => ({ ...d, noticePeriod: event.target.value }))
                }
                placeholder="np. 30"
                aria-invalid={validationError ? true : undefined}
              />
              <select
                aria-label="Okres wypowiedzenia — jednostka"
                className="min-h-11 rounded-lg border border-border bg-card px-2 text-sm"
                value={draft.noticeUnit}
                onChange={(event) =>
                  setDraft((d) => ({ ...d, noticeUnit: event.target.value }))
                }
              >
                {NOTICE_PERIOD_UNITS.map((unit) => (
                  <option key={unit.value} value={unit.value}>
                    {unit.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {validationError || mutationError ? (
            <p
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere] sm:col-span-2"
            >
              {validationError ?? mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            disabled={Boolean(validationError) || Object.keys(patch).length === 0}
            onClick={() => {
              setMutationError(null);
              mutation.mutate();
            }}
          >
            Zapisz dostępność
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function WorkModeEditor({
  open,
  onOpenChange,
  candidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidate: CandidateProfileFactsBarProps["candidate"];
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [modes, setModes] = React.useState<WorkMode[]>([]);
  const [days, setDays] = React.useState("");
  const [mutationError, setMutationError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const current = profileWorkMode(
      candidate.preferences,
      candidate.max_onsite_days_per_week,
    );
    setModes(current.modes);
    setDays(current.days != null ? String(current.days) : "");
    setMutationError(null);
  }, [candidate.preferences, candidate.max_onsite_days_per_week, open]);

  const parsedDays = days.trim() === "" ? null : Number(days);
  const daysInvalid =
    parsedDays != null &&
    (!Number.isInteger(parsedDays) || parsedDays < 0 || parsedDays > 7);
  const coherenceError = daysInvalid
    ? null
    : workModeValidationError(modes, parsedDays);

  const mutation = useMutation({
    mutationFn: () =>
      candidateFactsApi.updateWorkMode(candidate.id, {
        remote_modes: modes,
        max_onsite_days_per_week: parsedDays,
      }),
    onSuccess: () => {
      setMutationError(null);
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notesFacts(candidate.id),
      });
      onOpenChange(false);
      showSuccess("Tryb pracy zapisany");
    },
    onError: (error) => {
      const message =
        extractErrorMsg(error) || "Nie udało się zapisać trybu pracy";
      setMutationError(message);
      showError(message);
    },
  });

  const toggle = (mode: WorkMode, on: boolean) => {
    setModes((prev) =>
      WORK_MODES.filter((m) => (m === mode ? on : prev.includes(m))),
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="candidate-work-mode-dialog-description">
        <DialogHeader>
          <DialogTitle>Tryb pracy kandydata</DialogTitle>
          <DialogDescription id="candidate-work-mode-dialog-description">
            Zaznacz wszystkie tryby, które kandydat akceptuje, i podaj, ile
            dni w tygodniu może być w biurze. Wyszukiwanie odrzuca rekrutacje
            wymagające więcej dni w biurze.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <fieldset>
            <legend className="text-sm font-medium">Akceptuje pracę</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {WORK_MODES.map((mode) => {
                const id = `candidate-work-mode-${mode}`;
                return (
                  <label
                    key={mode}
                    htmlFor={id}
                    className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-border px-3 text-sm"
                  >
                    <Checkbox
                      id={id}
                      checked={modes.includes(mode)}
                      onCheckedChange={(value) => toggle(mode, value === true)}
                    />
                    {WORK_MODE_LABELS[mode]}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <div>
            <Label htmlFor="candidate-work-mode-days">
              Maksymalnie dni w biurze w tygodniu
            </Label>
            <Input
              id="candidate-work-mode-days"
              className="mt-1 min-h-11 w-32"
              inputMode="numeric"
              value={days}
              onChange={(event) =>
                setDays(event.target.value.replace(/[^0-9]/g, "").slice(0, 1))
              }
              placeholder="np. 2"
              invalid={daysInvalid || Boolean(coherenceError)}
              aria-describedby="candidate-work-mode-days-hint"
            />
            <p
              id="candidate-work-mode-days-hint"
              className="mt-1 text-xs text-muted-foreground"
            >
              0 = wyłącznie zdalnie, 5 = cały tydzień w biurze. Puste = nie
              wiadomo.
            </p>
          </div>
          {daysInvalid || coherenceError ? (
            <p role="alert" className="text-sm text-destructive">
              {daysInvalid ? "Podaj liczbę od 0 do 7." : coherenceError}
            </p>
          ) : null}
          {mutationError ? (
            <p
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
            >
              {mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            disabled={daysInvalid || Boolean(coherenceError)}
            onClick={() => {
              setMutationError(null);
              mutation.mutate();
            }}
          >
            Zapisz tryb pracy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const SELECT_CLASS =
  "mt-1 min-h-11 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring";

/**
 * Korekta faktów z telefonu praktykanta (audyt 24.09.2026). „Nie wiadomo”
 * czyści odpowiedź — bramki dopasowań znowu przepuszczają kandydata.
 */
function CallFactsEditor({
  open,
  onOpenChange,
  candidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidate: CandidateProfileFactsBarProps["candidate"];
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [draft, setDraft] = React.useState<CallFactsDraft>(() =>
    callFactsDraft(candidate),
  );
  const [mutationError, setMutationError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setDraft(callFactsDraft(candidate));
    setMutationError(null);
    // Stan startowy tylko przy otwarciu — zmiana kandydata w tle nie może
    // nadpisać tego, co użytkownik właśnie wybiera.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const patch = callFactsPatch(candidate, draft);
  const unchanged = Object.keys(patch).length === 0;

  const mutation = useMutation({
    mutationFn: () => candidateFactsApi.updateCallFacts(candidate.id, patch),
    onSuccess: () => {
      setMutationError(null);
      invalidateCandidateMutation(queryClient, candidate.id, "edit");
      onOpenChange(false);
      showSuccess("Fakty z rozmowy poprawione");
    },
    onError: (error) => {
      const message =
        extractErrorMsg(error) || "Nie udało się poprawić faktów z rozmowy";
      setMutationError(message);
      showError(message);
    },
  });

  const set = <K extends keyof CallFactsDraft>(key: K, value: CallFactsDraft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="candidate-call-facts-dialog-description">
        <DialogHeader>
          <DialogTitle>Popraw fakty z rozmowy</DialogTitle>
          <DialogDescription id="candidate-call-facts-dialog-description">
            Zmienisz odpowiedzi zapisane po telefonie. „Tylko umowa o pracę”
            ukrywa kandydata we wszystkich dopasowaniach — „Nie wiadomo”
            przywraca go do nich. Zmiana zostaje w historii profilu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div>
            <Label htmlFor="call-facts-b2b">Forma współpracy</Label>
            <select
              id="call-facts-b2b"
              className={SELECT_CLASS}
              value={draft.b2b_willingness}
              onChange={(event) =>
                set(
                  "b2b_willingness",
                  event.target.value as CallFactsDraft["b2b_willingness"],
                )
              }
            >
              <option value="">Nie wiadomo</option>
              {B2B_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="call-facts-work-time">Wymiar pracy</Label>
            <select
              id="call-facts-work-time"
              className={SELECT_CLASS}
              value={draft.work_time_preference}
              onChange={(event) =>
                set(
                  "work_time_preference",
                  event.target.value as CallFactsDraft["work_time_preference"],
                )
              }
            >
              <option value="">Nie wiadomo</option>
              {WORK_TIME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="call-facts-below-min">
              Oferta poniżej minimalnej stawki
            </Label>
            <select
              id="call-facts-below-min"
              className={SELECT_CLASS}
              value={draft.accepts_below_min_rate}
              onChange={(event) =>
                set(
                  "accepts_below_min_rate",
                  event.target.value as CallFactsDraft["accepts_below_min_rate"],
                )
              }
            >
              <option value="">Nie wiadomo</option>
              <option value="yes">Można dzwonić</option>
              <option value="no">Nie dzwonić</option>
            </select>
          </div>
          <div>
            <Label htmlFor="call-facts-office">Więcej dni w biurze</Label>
            <select
              id="call-facts-office"
              className={SELECT_CLASS}
              value={draft.accepts_more_office_days}
              onChange={(event) =>
                set(
                  "accepts_more_office_days",
                  event.target.value as CallFactsDraft["accepts_more_office_days"],
                )
              }
            >
              <option value="">Nie wiadomo</option>
              <option value="yes">Można dzwonić</option>
              <option value="no">Nie dzwonić</option>
            </select>
          </div>
          {mutationError ? (
            <p
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
            >
              {mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            disabled={unchanged}
            onClick={() => {
              setMutationError(null);
              mutation.mutate();
            }}
          >
            Zapisz poprawkę
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RateEditor({
  open,
  onOpenChange,
  candidateId,
  queryData,
  initialMinimum = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  queryData: RateQueryData;
  /** Otwarte z „Ustaw minimum ręcznie” w historii stawek. */
  initialMinimum?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [amount, setAmount] = React.useState("");
  const [validationError, setValidationError] = React.useState<string | null>(
    null,
  );
  const [conflictMessage, setConflictMessage] = React.useState<string | null>(
    null,
  );
  const [mutationError, setMutationError] = React.useState<string | null>(null);
  // „To jego minimum” (0414): starsze niższe stawki przestają się liczyć do
  // „Stawki od”, którą czytają filtry i AI.
  const [isMinimum, setIsMinimum] = React.useState(false);
  const wasOpenRef = React.useRef(false);
  // 0418 (D4): zmiana stawki w profilu pyta o trwające procesy — w zaznaczonych
  // stawka zmienia się tą samą regułą co w panelu osoby (ślad, DL i HoR).
  const processes = useQuery({
    queryKey: activeProcessesQueryKey(candidateId),
    queryFn: () => rateChangesApi.activeProcesses(candidateId),
    enabled: open,
    staleTime: 15_000,
  });
  const [processJobs, setProcessJobs] = React.useState<Set<number> | null>(null);
  React.useEffect(() => {
    if (!open) {
      setProcessJobs(null);
      return;
    }
    if (processJobs === null && processes.data) {
      setProcessJobs(new Set(processes.data.map((p) => p.job_id)));
    }
  }, [open, processes.data, processJobs]);

  React.useEffect(() => {
    if (open && !wasOpenRef.current) {
      setAmount(queryData.data.amount ?? "");
      setIsMinimum(initialMinimum);
      setValidationError(null);
      setConflictMessage(null);
      setMutationError(null);
    }
    wasOpenRef.current = open;
  }, [open, queryData.data.amount, initialMinimum]);

  const mutation = useMutation({
    mutationFn: (nextAmount: string | null) => {
      if (!queryData.etag) {
        throw new Error("Brak wersji danych. Odśwież stawkę i spróbuj ponownie.");
      }
      return isMinimum && nextAmount !== null
        ? candidateFactsApi.updateProfileRate(
            candidateId,
            nextAmount,
            queryData.etag,
            true,
          )
        : candidateFactsApi.updateProfileRate(
            candidateId,
            nextAmount,
            queryData.etag,
          );
    },
    onSuccess: async (result, nextAmount) => {
      setMutationError(null);
      queryClient.setQueryData(
        candidateQueryKeys.profileRate(candidateId),
        result,
      );
      // Kolumna „Stawka” listy kandydatów czyta stawkę profilu — bez
      // unieważnienia lista pokazywała starą kwotę przez 30 s (staleTime).
      invalidateCandidateMutation(queryClient, candidateId, "rate");
      onOpenChange(false);
      const jobs = nextAmount !== null ? [...(processJobs ?? [])] : [];
      if (jobs.length === 0) {
        showSuccess("Stawka profilu zapisana");
        return;
      }
      const results = await Promise.allSettled(
        jobs.map((jobId) =>
          rateChangesApi.create({
            candidate_id: candidateId,
            job_id: jobId,
            amount: nextAmount as string,
            unit: "hourly",
            reason: "other",
            source: "profile",
          }),
        ),
      );
      queryClient.invalidateQueries({ queryKey: ["kanban"] });
      queryClient.invalidateQueries({ queryKey: ["rate-changes"] });
      const failed = results.filter((r) => r.status === "rejected").length;
      if (failed > 0) {
        showError(
          `Stawka profilu zapisana, ale w ${failed} z ${jobs.length} procesów nie udało się jej zmienić. Zmień ją w panelu osoby.`,
        );
      } else {
        showSuccess(
          `Stawka zapisana w profilu i w ${jobs.length} ${jobs.length === 1 ? "procesie" : "procesach"}.`,
        );
      }
    },
    onError: (error) => {
      const status = requestStatus(error);
      if (status === 409 || status === 412 || status === 428) {
        queryClient.invalidateQueries({
          queryKey: candidateQueryKeys.profileRate(candidateId),
        });
        const message =
          "Stawka zmieniła się w innym oknie. Zachowaliśmy Twój draft i pobieramy aktualną wersję — sprawdź go przed ponownym zapisem.";
        setMutationError(null);
        setConflictMessage(message);
        showError(message);
        return;
      }
      const message =
        extractErrorMsg(error) || "Nie udało się zapisać stawki";
      setMutationError(message);
      showError(message);
    },
  });

  const save = () => {
    setMutationError(null);
    const normalized = amount.trim().replace(",", ".");
    if (!normalized) {
      setValidationError(null);
      setConflictMessage(null);
      mutation.mutate(null);
      return;
    }
    if (!/^\d{1,8}(?:\.\d{1,2})?$/.test(normalized)) {
      setValidationError(
        "Podaj kwotę z maksymalnie 8 cyframi przed przecinkiem i 2 miejscami po przecinku.",
      );
      return;
    }
    setValidationError(null);
    setConflictMessage(null);
    mutation.mutate(normalized);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="candidate-rate-dialog-description">
        <DialogHeader>
          <DialogTitle>Stawka podana przez kandydata</DialogTitle>
          <DialogDescription id="candidate-rate-dialog-description">
            Stawka B2B w PLN netto za godzinę. Trafia do historii stawek —
            filtry i AI porównują budżet z najniższą stawką z ostatnich 18
            miesięcy („Stawka od”).
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Label htmlFor="candidate-profile-rate">Kwota</Label>
          <div className="relative mt-1">
            <Input
              id="candidate-profile-rate"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="np. 160,00"
              className="min-h-11 pr-32"
              invalid={Boolean(validationError || mutationError)}
              aria-describedby={
                [
                  validationError && "candidate-profile-rate-error",
                  conflictMessage && "candidate-profile-rate-conflict",
                  mutationError && "candidate-profile-rate-mutation-error",
                ]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
            />
            <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
              PLN netto/h
            </span>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Pozostaw puste, aby usunąć stawkę z profilu.
          </p>
          <label
            htmlFor="candidate-profile-rate-minimum"
            className="mt-3 flex items-start gap-2 text-sm"
          >
            <Checkbox
              id="candidate-profile-rate-minimum"
              checked={isMinimum}
              onCheckedChange={(value) => setIsMinimum(value === true)}
              className="mt-0.5"
            />
            <span>
              To jego minimum
              <span className="block text-xs text-muted-foreground">
                Niższe stawki podane wcześniej przestaną się liczyć do
                „Stawki od”. Zostaną w historii.
              </span>
            </span>
          </label>
          {processes.data && processes.data.length > 0 ? (
            <fieldset className="mt-3" data-testid="profile-rate-processes">
              <legend className="text-sm font-medium">Zmień też w trwających procesach</legend>
              <p className="text-xs text-muted-foreground">
                Delivery Lead i Head of Recruitment dostaną powiadomienie, a gdy CV
                jest już u klienta — DL dostanie zadanie.
              </p>
              <ul className="mt-1.5 space-y-1">
                {processes.data.map((p) => (
                  <li key={p.job_id}>
                    <label className="flex items-start gap-2 text-sm">
                      <Checkbox
                        checked={processJobs?.has(p.job_id) ?? true}
                        onCheckedChange={(value) =>
                          setProcessJobs((prev) => {
                            const next = new Set(prev ?? []);
                            if (value === true) next.add(p.job_id);
                            else next.delete(p.job_id);
                            return next;
                          })
                        }
                        className="mt-0.5"
                      />
                      <span className="min-w-0">
                        <span className="block truncate">{p.job_title}</span>
                        <span className="block text-xs text-muted-foreground">
                          {[p.client_name, p.current_label ? `teraz ${p.current_label}` : null]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>
          ) : null}
          {validationError ? (
            <p
              id="candidate-profile-rate-error"
              role="alert"
              className="mt-2 text-sm text-destructive"
            >
              {validationError}
            </p>
          ) : null}
          {conflictMessage ? (
            <p
              id="candidate-profile-rate-conflict"
              role="alert"
              className="mt-2 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              {conflictMessage}
            </p>
          ) : null}
          {mutationError ? (
            <p
              id="candidate-profile-rate-mutation-error"
              role="alert"
              className="mt-2 rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
            >
              {mutationError}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 min-w-11"
            onClick={() => onOpenChange(false)}
          >
            Anuluj
          </Button>
          <Button
            type="button"
            className="min-h-11 min-w-11"
            loading={mutation.isPending}
            onClick={save}
          >
            Zapisz stawkę
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditFactButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      size="icon-sm"
      variant="ghost"
      className="min-h-11 min-w-11 shrink-0 text-muted-foreground"
      aria-label={label}
      onClick={onClick}
    >
      <PencilLine aria-hidden="true" className="size-4" />
    </Button>
  );
}

export function CandidateProfileFactsBar({
  candidate,
  layout = "grid",
  children,
}: CandidateProfileFactsBarProps) {
  // GET/PATCH /api/candidates/{id}/profile-rate stoi na
  // CandidateProfileFacts{Read,Write}Access = _INTERNAL_OPERATIONAL_ROLES —
  // czyli KAŻDA rola operacyjna, w tym HoR i sourcer (polityka faktów
  // globalnych) oraz `finance` (tier recruitera od 19.08), którego ręczna
  // lista tu gubiła. To NIE jest RECRUITMENT_RATE_EDIT_ROLES: tamten zbiór
  // bramkuje stawkę w pipelinie, nie fakt globalny.
  //
  // Ta sama capability bramkuje KAŻDĄ edycję w pasku: PUT języków i PATCH
  // lokalizacji stoją na tym samym CandidateProfileFactsWriteAccess. Ołówek
  // bez prawa zapisu kończył się 403 po kliknięciu „Zapisz”.
  const canViewAndEditRate = useCapability("candidate.profile_fact.manage");
  const canEditFacts = canViewAndEditRate;
  // Dostępność zapisuje PATCH /api/candidates/{id} (jak „Edytuj dane”), więc
  // potrzebuje też prawa zapisu kandydata.
  const canWriteCandidate = useCapability("candidate.write");
  const canEditAvailability = canEditFacts && canWriteCandidate;
  const column = layout === "column";
  // Karta „Podsumowanie”: ołówki dopiero po „Edytuj” (jedno wejście w edycję
  // zamiast sześciu ikon stale na widoku). Pasek kafelków pokazuje je zawsze.
  const [editing, setEditing] = React.useState(false);
  const [languagesOpen, setLanguagesOpen] = React.useState(false);
  const [locationOpen, setLocationOpen] = React.useState(false);
  const [availabilityOpen, setAvailabilityOpen] = React.useState(false);
  const [rateOpen, setRateOpen] = React.useState(false);
  const [rateHistoryOpen, setRateHistoryOpen] = React.useState(false);
  const [rateAsMinimum, setRateAsMinimum] = React.useState(false);
  const [workModeOpen, setWorkModeOpen] = React.useState(false);
  const [callFactsOpen, setCallFactsOpen] = React.useState(false);

  React.useEffect(() => {
    setEditing(false);
    setLanguagesOpen(false);
    setLocationOpen(false);
    setAvailabilityOpen(false);
    setRateOpen(false);
    setRateHistoryOpen(false);
    setWorkModeOpen(false);
    setCallFactsOpen(false);
  }, [candidate.id]);

  const languagesQuery = useQuery<LanguagesQueryData>({
    queryKey: candidateQueryKeys.languages(candidate.id),
    queryFn: () => candidateFactsApi.getLanguages(candidate.id),
    enabled: candidate.id > 0,
    retry: false,
    staleTime: 30_000,
  });
  const rateQuery = useQuery<RateQueryData>({
    queryKey: candidateQueryKeys.profileRate(candidate.id),
    queryFn: () => candidateFactsApi.getProfileRate(candidate.id),
    enabled: candidate.id > 0 && canViewAndEditRate,
    retry: false,
    staleTime: 30_000,
  });

  const languageSummary = languagesQuery.data?.data.languages ?? [];
  const canonicalLocation = [candidate.city, candidate.country]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(", ");
  const location =
    canonicalLocation ||
    formatCandidateLocation(candidate.location) ||
    "";
  const workMode = profileWorkMode(
    candidate.preferences,
    candidate.max_onsite_days_per_week,
  );
  const workModeLabel = formatWorkMode(workMode.modes, workMode.days);
  const rateLabel = rateFactLabel(candidate, rateQuery.data?.data.updated_at);
  const verifiedLabel = callFactsVerifiedLabel(candidate);
  const callFacts = callFactItems(candidate);
  // Ustalenia z kart rekomendacji — dodatek: brak dostępu albo awaria odczytu
  // zostawia pasek bez linii źródła.
  const viewerScope = candidateViewerScopeKey(useAuthStore((state) => state.user));
  const cardOverview = useCandidateCardOverview(candidate.id, viewerScope);
  const cardFacts = cardFactsByKey(cardOverview.data?.facts);
  const profileRate =
    rateQuery.data?.data.amount != null ? Number(rateQuery.data.data.amount) : null;
  // „Stawka od” (0414): najniższa stawka z 18 miesięcy — ją czytają filtry
  // i AI. Pokazujemy ją, gdy różni się od stawki profilu albo profil jej nie ma
  // — inaczej kafel mówi to samo dwa razy.
  const rateFromAmount = toAmount(candidate.rate_from_hourly);
  const rateFrom =
    rateFromAmount !== null &&
    (profileRate === null ||
      Math.abs(rateFromAmount - profileRate) >= 0.005 ||
      Boolean(candidate.rate_from_stale) ||
      (candidate.rate_observation_count ?? 0) > 1)
      ? (rateFromText(candidate) ?? "").replace(/^od /, "")
      : null;
  const rateSecond = rateFrom ? rateSecondLine(candidate) : null;
  const languagesForbidden = requestStatus(languagesQuery.error) === 403;
  const rateForbidden = requestStatus(rateQuery.error) === 403;

  // Kolejność od 04.10.2026: najpierw to, o co rekruter pyta przed
  // zaproponowaniem osoby (dostępność, stawka, tryb, miasto), potem języki
  // i narodowość.
  const facts = (
    <>
      <FactShell
        icon={<CalendarClock className="size-4" />}
        label="Dostępność"
        muted={!candidate.availability_status}
        origin={cardOrigin(cardFacts.availability)}
        action={
          canEditAvailability ? (
            <EditFactButton
              label="Edytuj dostępność"
              onClick={() => setAvailabilityOpen(true)}
            />
          ) : null
        }
      >
        {availabilityValue(candidate)}
      </FactShell>

      {canViewAndEditRate && !rateForbidden ? (
        rateQuery.isPending ? (
          <FactLoading label={rateLabel} />
        ) : rateQuery.isError ? (
          <FactShell
            icon={<WalletCards className="size-4" />}
            label={rateLabel}
            muted
            actionAlways
            action={
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                className="min-h-11 min-w-11"
                aria-label="Ponów pobieranie stawki"
                onClick={() => rateQuery.refetch()}
              >
                <RefreshCw aria-hidden="true" className="size-4" />
              </Button>
            }
          >
            <span role="alert">Dane niedostępne</span>
          </FactShell>
        ) : rateQuery.data ? (
          <FactShell
            icon={<WalletCards className="size-4" />}
            label={rateFrom ? "Stawka od" : rateLabel}
            muted={rateQuery.data.data.amount == null && !rateFrom}
            origin={
              rateFrom
                ? rateSecond
                  ? {
                      text: rateSecond,
                      title: "Ostatnio podana stawka i liczba stawek w historii",
                    }
                  : undefined
                : cardOrigin(cardFacts.rate, profileRate)
            }
            action={
              <EditFactButton
                label="Edytuj globalną stawkę B2B"
                onClick={() => setRateOpen(true)}
              />
            }
            footer={
              <button
                type="button"
                className="mt-1 block min-h-6 text-xs font-medium text-primary hover:underline"
                onClick={() => setRateHistoryOpen(true)}
              >
                Historia stawek
                {candidate.rate_observation_count
                  ? ` (${candidate.rate_observation_count})`
                  : ""}
              </button>
            }
          >
            {rateFrom ?? formatRate(rateQuery.data.data.amount)}
          </FactShell>
        ) : null
      ) : null}

      <FactShell
        icon={<Briefcase className="size-4" />}
        label="Tryb pracy"
        muted={!workModeLabel}
        origin={cardOrigin(cardFacts.work_mode)}
        action={
          canEditFacts ? (
            <EditFactButton
              label="Edytuj tryb pracy"
              onClick={() => setWorkModeOpen(true)}
            />
          ) : null
        }
      >
        {workModeLabel ?? "Nie uzupełniono"}
      </FactShell>

      <FactShell
        icon={<MapPin className="size-4" />}
        label={column ? "Miasto" : "Lokalizacja"}
        muted={!location}
        action={
          canEditFacts ? (
            <EditFactButton
              label="Edytuj lokalizację"
              onClick={() => setLocationOpen(true)}
            />
          ) : null
        }
      >
        {location || "Nie uzupełniono"}
      </FactShell>

      {languagesQuery.isPending ? (
        <FactLoading label="Języki" />
      ) : languagesQuery.isError ? (
        <FactShell
          icon={
            languagesForbidden ? (
              <LockKeyhole className="size-4" />
            ) : (
              <Languages className="size-4" />
            )
          }
          label="Języki"
          muted
          actionAlways
          action={
            languagesForbidden ? null : (
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                className="min-h-11 min-w-11"
                aria-label="Ponów pobieranie języków"
                onClick={() => languagesQuery.refetch()}
              >
                <RefreshCw aria-hidden="true" className="size-4" />
              </Button>
            )
          }
        >
          <span role={languagesForbidden ? "status" : "alert"}>
            {languagesForbidden ? "Brak dostępu" : "Dane niedostępne"}
          </span>
        </FactShell>
      ) : (
        <FactShell
          icon={<Languages className="size-4" />}
          label="Języki"
          muted={languageSummary.length === 0}
          origin={cardOrigin(cardFacts.english)}
          action={
            canEditFacts ? (
              <EditFactButton
                label="Edytuj języki"
                onClick={() => setLanguagesOpen(true)}
              />
            ) : null
          }
        >
          {languageSummary.length ? (
            <span className="flex flex-wrap gap-1">
              {languageSummary.slice(0, 2).map((language) => (
                <Badge
                  key={language.id}
                  variant="soft"
                  size="sm"
                  className="h-auto max-w-full whitespace-normal break-words py-0.5"
                >
                  {languageLabel(language)}
                </Badge>
              ))}
              {languageSummary.length > 2 ? (
                <Badge variant="neutral" size="sm">
                  +{languageSummary.length - 2}
                </Badge>
              ) : null}
            </span>
          ) : (
            "Nie uzupełniono"
          )}
        </FactShell>
      )}

      {cardFacts.nationality ? (
        <FactShell
          icon={<Globe2 className="size-4" />}
          label="Narodowość"
          origin={{
            text: cardFactOrigin(cardFacts.nationality),
            title: cardFactTitle(cardFacts.nationality),
          }}
        >
          {cardFacts.nationality.raw}
        </FactShell>
      ) : null}
    </>
  );

  const callFactsRow =
    verifiedLabel || callFacts.length ? (
      <div
        aria-label="Fakty z rozmowy telefonicznej"
        className="mt-2 flex flex-wrap items-center gap-1.5"
      >
        {verifiedLabel ? (
          <Badge
            variant="success"
            className="h-auto max-w-full whitespace-normal break-words py-0.5"
          >
            {verifiedLabel}
          </Badge>
        ) : null}
        {callFacts.map((fact) => (
          <Badge
            key={fact.key}
            variant={fact.tone === "danger" ? "danger" : "outline"}
            className="h-auto max-w-full whitespace-normal break-words py-0.5"
          >
            {fact.label}
          </Badge>
        ))}
        {canEditFacts && callFacts.length && (!column || editing) ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="min-h-11"
            aria-label="Popraw fakty z rozmowy"
            onClick={() => setCallFactsOpen(true)}
          >
            <PencilLine aria-hidden="true" className="size-4" />
            Popraw
          </Button>
        ) : null}
      </div>
    ) : null;

  const editors = (
    <>
      {canEditFacts ? (
        <CallFactsEditor
          open={callFactsOpen}
          onOpenChange={setCallFactsOpen}
          candidate={candidate}
        />
      ) : null}

      {canEditFacts && languagesQuery.data ? (
        <LanguagesEditor
          open={languagesOpen}
          onOpenChange={setLanguagesOpen}
          candidateId={candidate.id}
          queryData={languagesQuery.data}
        />
      ) : null}
      {canEditFacts ? (
        <LocationEditor
          open={locationOpen}
          onOpenChange={setLocationOpen}
          candidate={candidate}
        />
      ) : null}
      {canEditAvailability ? (
        <AvailabilityEditor
          open={availabilityOpen}
          onOpenChange={setAvailabilityOpen}
          candidate={candidate}
        />
      ) : null}
      {canEditFacts ? (
        <WorkModeEditor
          open={workModeOpen}
          onOpenChange={setWorkModeOpen}
          candidate={candidate}
        />
      ) : null}
      {rateQuery.data ? (
        <RateEditor
          open={rateOpen}
          onOpenChange={(next) => {
            setRateOpen(next);
            if (!next) setRateAsMinimum(false);
          }}
          candidateId={candidate.id}
          queryData={rateQuery.data}
          initialMinimum={rateAsMinimum}
        />
      ) : null}
      {canViewAndEditRate ? (
        <RateHistoryDialog
          open={rateHistoryOpen}
          onOpenChange={setRateHistoryOpen}
          candidateId={candidate.id}
          canEdit={canEditFacts}
          onSetMinimum={
            rateQuery.data
              ? () => {
                  setRateHistoryOpen(false);
                  setRateAsMinimum(true);
                  setRateOpen(true);
                }
              : undefined
          }
        />
      ) : null}
    </>
  );

  if (column) {
    return (
      <FactsLayoutContext.Provider value={{ column: true, editing }}>
        <section
          aria-labelledby="candidate-summary-heading"
          data-help="candidate.profile.facts"
          className="rounded-xl border border-border bg-card px-4 py-3 md:max-2xl:px-3"
        >
          <div className="flex min-h-9 items-center justify-between gap-2">
            <h2
              id="candidate-summary-heading"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Podsumowanie
            </h2>
            {canEditFacts ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="min-h-9 px-2 text-primary"
                aria-pressed={editing}
                onClick={() => setEditing((value) => !value)}
              >
                {editing ? "Gotowe" : "Edytuj"}
              </Button>
            ) : null}
          </div>
          <div
            aria-label="Najważniejsze fakty o kandydacie"
            className="divide-y divide-border"
          >
            {facts}
          </div>
          {callFactsRow}
          {children}
        </section>
        {editors}
      </FactsLayoutContext.Provider>
    );
  }

  return (
    <>
      <section
        aria-label="Najważniejsze fakty o kandydacie"
        data-help="candidate.profile.facts"
        // Liczba kolumn wynika z szerokości PASKA, nie okna: obok listy
        // „Kandydaci — ostatnio wyświetlani” pasek bywa o połowę węższy niż
        // ekran, a `xl:grid-cols-5` wciskało pięć kafelków w ~900 px. Kafelek
        // ma najmniej 15rem (ikona, etykieta, wartość i przycisk edycji), resztę
        // dzieli po równo; za mało miejsca = kolejny wiersz.
        className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,15rem),1fr))] gap-3 md:max-2xl:gap-2"
      >
        {facts}
      </section>
      {callFactsRow}
      {children}
      {editors}
    </>
  );
}

export default CandidateProfileFactsBar;
