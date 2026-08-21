"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
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
import { useCapability } from "@/hooks/useCapability";
import { formatCandidateLocation } from "./candidate-list-helpers";
import { candidateQueryKeys } from "./candidate-query-keys";

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
const COMMON_LANGUAGE_CODES: Record<string, string> = {
  angielski: "en",
  english: "en",
  polski: "pl",
  polish: "pl",
  niemiecki: "de",
  german: "de",
  francuski: "fr",
  french: "fr",
  hiszpanski: "es",
  spanish: "es",
  wloski: "it",
  italian: "it",
  ukrainski: "uk",
  ukrainian: "uk",
  rosyjski: "ru",
  russian: "ru",
  czeski: "cs",
  czech: "cs",
  slowacki: "sk",
  slovak: "sk",
  niderlandzki: "nl",
  holenderski: "nl",
  dutch: "nl",
  portugalski: "pt",
  portuguese: "pt",
};

function normalizedLanguageToken(value: string): string {
  return value
    .normalize("NFKD")
    .toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l")
    .trim();
}

function inferredLanguageCode(languageName: string): string {
  const normalizedName = normalizedLanguageToken(languageName);
  if (!normalizedName) return "";
  const knownCode = COMMON_LANGUAGE_CODES[normalizedName];
  if (knownCode) return knownCode;
  return normalizedName
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 16);
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
  candidate: {
    id: number;
    city?: string | null;
    country?: string | null;
    location?: string | null;
    availability_status?: string | null;
    availability_date?: string | null;
    notice_period?: number | null;
    notice_period_unit?: string | null;
  };
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

function FactShell({
  icon,
  label,
  children,
  action,
  muted,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
  action?: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card p-3">
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
              "mt-0.5 min-w-0 break-words text-sm font-medium leading-5 text-foreground [overflow-wrap:anywhere]",
              muted && "font-normal text-muted-foreground",
            )}
          >
            {children}
          </div>
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
  const [rows, setRows] = React.useState<CandidateLanguageInput[]>([]);
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

  const updateRow = (
    index: number,
    update: Partial<CandidateLanguageInput>,
  ) => {
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
        language_code:
          row.language_code.trim().toLocaleLowerCase() ||
          inferredLanguageCode(row.language_name),
      }))
      .filter((row) => row.language_name);
    const invalidCode = normalized.find(
      (row) => !LANGUAGE_CODE_RE.test(row.language_code),
    );
    if (invalidCode) {
      setValidationError(
        `Podaj poprawny kod języka dla „${invalidCode.language_name}” (2–16 małych liter, cyfr lub łączników).`,
      );
      return;
    }
    const nameKeys = normalized.map((row) =>
      normalizedLanguageToken(row.language_name),
    );
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
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_6rem_9rem_auto]">
                <div>
                  <Label htmlFor={`candidate-language-${index}`}>Język</Label>
                  <Input
                    id={`candidate-language-${index}`}
                    className="mt-1 min-h-11"
                    value={row.language_name}
                    onChange={(event) => {
                      const languageName = event.target.value;
                      const previousInferredCode = inferredLanguageCode(
                        row.language_name,
                      );
                      updateRow(index, {
                        language_name: languageName,
                        language_code:
                          !row.language_code ||
                          row.language_code === previousInferredCode
                            ? inferredLanguageCode(languageName)
                            : row.language_code,
                      });
                    }}
                    placeholder="np. angielski"
                    autoComplete="off"
                  />
                </div>
                <div>
                  <Label htmlFor={`candidate-language-code-${index}`}>
                    Kod
                  </Label>
                  <Input
                    id={`candidate-language-code-${index}`}
                    className="mt-1 min-h-11 font-mono lowercase"
                    value={row.language_code}
                    onChange={(event) =>
                      updateRow(index, {
                        language_code: event.target.value
                          .toLocaleLowerCase()
                          .replace(/[^a-z0-9-]/g, "")
                          .slice(0, 16),
                      })
                    }
                    placeholder="en"
                    maxLength={16}
                    autoComplete="off"
                  />
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
  const [mutationError, setMutationError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setCity(candidate.city ?? "");
    setCountry(candidate.country ?? "");
    setMutationError(null);
  }, [candidate.city, candidate.country, open]);

  const mutation = useMutation({
    mutationFn: () =>
      candidateProfileApi.updateLocation(candidate.id, {
        city: city.trim() || null,
        country: country.trim().toUpperCase() || null,
      }),
    onSuccess: () => {
      setMutationError(null);
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.detail(candidate.id),
      });
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

function RateEditor({
  open,
  onOpenChange,
  candidateId,
  queryData,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  queryData: RateQueryData;
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
  const wasOpenRef = React.useRef(false);

  React.useEffect(() => {
    if (open && !wasOpenRef.current) {
      setAmount(queryData.data.amount ?? "");
      setValidationError(null);
      setConflictMessage(null);
      setMutationError(null);
    }
    wasOpenRef.current = open;
  }, [open, queryData.data.amount]);

  const mutation = useMutation({
    mutationFn: (nextAmount: string | null) => {
      if (!queryData.etag) {
        throw new Error("Brak wersji danych. Odśwież stawkę i spróbuj ponownie.");
      }
      return candidateFactsApi.updateProfileRate(
        candidateId,
        nextAmount,
        queryData.etag,
      );
    },
    onSuccess: (result) => {
      setMutationError(null);
      queryClient.setQueryData(
        candidateQueryKeys.profileRate(candidateId),
        result,
      );
      onOpenChange(false);
      showSuccess("Stawka profilu zapisana");
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
          <DialogTitle>Globalna stawka kandydata</DialogTitle>
          <DialogDescription id="candidate-rate-dialog-description">
            To oczekiwana stawka B2B w PLN netto za godzinę. Nie zmienia stawek
            przypisanych do konkretnych rekrutacji.
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
            Pozostaw puste, aby usunąć globalną stawkę.
          </p>
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
}: CandidateProfileFactsBarProps) {
  // GET/PATCH /api/candidates/{id}/profile-rate stoi na
  // CandidateProfileFacts{Read,Write}Access = _INTERNAL_OPERATIONAL_ROLES —
  // czyli KAŻDA rola operacyjna, w tym HoR i sourcer (polityka faktów
  // globalnych) oraz `finance` (tier recruitera od 19.08), którego ręczna
  // lista tu gubiła. To NIE jest RECRUITMENT_RATE_EDIT_ROLES: tamten zbiór
  // (bez HoR i sourcera) bramkuje stawkę w pipelinie, nie fakt globalny.
  const canViewAndEditRate = useCapability("candidate.profile_fact.manage");
  const [languagesOpen, setLanguagesOpen] = React.useState(false);
  const [locationOpen, setLocationOpen] = React.useState(false);
  const [rateOpen, setRateOpen] = React.useState(false);

  React.useEffect(() => {
    setLanguagesOpen(false);
    setLocationOpen(false);
    setRateOpen(false);
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
  const languagesForbidden = requestStatus(languagesQuery.error) === 403;
  const rateForbidden = requestStatus(rateQuery.error) === 403;

  return (
    <>
      <section
        aria-label="Najważniejsze fakty o kandydacie"
        className={cn(
          "grid gap-3",
          canViewAndEditRate && !rateForbidden
            ? "sm:grid-cols-2 xl:grid-cols-4"
            : "sm:grid-cols-3",
        )}
      >
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
            action={
              <EditFactButton
                label="Edytuj języki"
                onClick={() => setLanguagesOpen(true)}
              />
            }
          >
            {languageSummary.length ? (
              <span className="flex flex-wrap gap-1">
                {languageSummary.slice(0, 2).map((language) => (
                  <Badge
                    key={language.id}
                    variant="soft"
                    size="sm"
                    className="h-auto max-w-full whitespace-normal py-0.5 [overflow-wrap:anywhere]"
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

        <FactShell
          icon={<MapPin className="size-4" />}
          label="Lokalizacja"
          muted={!location}
          action={
            <EditFactButton
              label="Edytuj lokalizację"
              onClick={() => setLocationOpen(true)}
            />
          }
        >
          {location || "Nie uzupełniono"}
        </FactShell>

        <FactShell
          icon={<CalendarClock className="size-4" />}
          label="Dostępność"
          muted={!candidate.availability_status}
        >
          {availabilityValue(candidate)}
        </FactShell>

        {canViewAndEditRate && !rateForbidden ? (
          rateQuery.isPending ? (
            <FactLoading label="Stawka B2B" />
          ) : rateQuery.isError ? (
            <FactShell
              icon={<WalletCards className="size-4" />}
              label="Stawka B2B"
              muted
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
              label="Stawka B2B"
              muted={rateQuery.data.data.amount == null}
              action={
                <EditFactButton
                  label="Edytuj globalną stawkę B2B"
                  onClick={() => setRateOpen(true)}
                />
              }
            >
              {formatRate(rateQuery.data.data.amount)}
            </FactShell>
          ) : null
        ) : null}
      </section>

      {languagesQuery.data ? (
        <LanguagesEditor
          open={languagesOpen}
          onOpenChange={setLanguagesOpen}
          candidateId={candidate.id}
          queryData={languagesQuery.data}
        />
      ) : null}
      <LocationEditor
        open={locationOpen}
        onOpenChange={setLocationOpen}
        candidate={candidate}
      />
      {rateQuery.data ? (
        <RateEditor
          open={rateOpen}
          onOpenChange={setRateOpen}
          candidateId={candidate.id}
          queryData={rateQuery.data}
        />
      ) : null}
    </>
  );
}

export default CandidateProfileFactsBar;
