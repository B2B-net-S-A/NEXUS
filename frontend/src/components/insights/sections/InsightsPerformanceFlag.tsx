"use client";

import { AlertCircle, AlertTriangle, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  isBlockingViewState,
  resolveViewState,
  httpStatusFromError,
} from "@/lib/view-state";
import type {
  PerformanceFlag,
  PerformanceFlagSeverity,
} from "@/lib/insights-flags-api";

/**
 * Plakietki ostrzeżeń pod nazwiskiem w tabeli „Performance per osoba”
 * (odpowiednik czerwonej „Słabe wyniki” i bursztynowej „Procedury”
 * z DynaReportera) plus chip „były pracownik”.
 *
 * Komponent jest CZYSTO PREZENTACYJNY — nie pobiera danych sam. Tabela ma
 * kilkanaście wierszy, a zapytanie per wiersz dałoby kilkanaście odczytów
 * i stan, w którym część wierszy ma już plakietki, a część jeszcze nie —
 * czyli ekran, który przez chwilę kłamie o tym, kto jest oflagowany.
 * Rodzic robi JEDEN odczyt (`insightsFlagsApi.list()`) i rozdaje wiersze.
 *
 * Konsekwencją tego podziału jest `PerformanceFlagsLoadNotice` niżej: skoro
 * komponent nie zna stanu zapytania, to awaria tego zapytania renderowałaby
 * się tutaj jako „nikt nie ma ostrzeżeń” — czyli awaria w przebraniu
 * informacji. Notka jest tego lekarstwem i nie jest opcjonalna.
 *
 * Etykieta, opis i `severity` przychodzą Z SERWERA razem z flagą. Świadomie
 * NIE ma tu mapy `flag_type → tekst/kolor`: druga kopia brzmienia rozjeżdża
 * się cicho, bo obie wersje się renderują.
 */

const SEVERITY_STYLE: Record<
  PerformanceFlagSeverity,
  {
    badge: "danger" | "warning";
    description: string;
    Icon: typeof AlertTriangle;
  }
> = {
  critical: {
    badge: "danger",
    description: "text-destructive-muted-foreground",
    Icon: AlertTriangle,
  },
  warning: {
    badge: "warning",
    description: "text-warning-muted-foreground",
    Icon: AlertCircle,
  },
};

// Nieznana wartość `severity` (backend dorzucił typ, front jeszcze o nim nie
// wie) ma się renderować jako ostrzeżenie, nie zniknąć. Plakietka, która nie
// wyświetla się przez nierozpoznany kolor, gubi całą treść oceny.
function styleFor(severity: PerformanceFlagSeverity) {
  return SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.warning;
}

function formatStamp(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("pl-PL", { dateStyle: "short" }).format(date);
}

/** Podpis pod oceną — jedzie w `title`, żeby nie rozpychać wiersza tabeli. */
function provenance(flag: PerformanceFlag): string {
  const who = flag.created_by_name ?? "konto autora usunięte";
  const when = formatStamp(flag.created_at);
  return when
    ? `Ostrzeżenie postawił: ${who} · ${when}`
    : `Ostrzeżenie postawił: ${who}`;
}

/**
 * Chip „były pracownik”. Wyprowadzany z `User.is_active`, NIE z flagi —
 * odejście z firmy to zdarzenie kadrowe, nie ocena jakości pracy, a wygaszanie
 * ostrzeżeń nie może nikogo „przywracać” do zespołu.
 */
export function FormerEmployeeChip({ className }: { className?: string }) {
  return (
    <Badge
      variant="outline"
      size="sm"
      className={cn("text-muted-foreground", className)}
    >
      były pracownik
    </Badge>
  );
}

export interface InsightsPerformanceFlagsProps {
  /** Aktywne flagi TEJ osoby. Pusta lista = brak ostrzeżeń (poprawny stan). */
  flags: PerformanceFlag[];
  /** `!user.is_active` — chip stoi OBOK ostrzeżeń, nie zamiast nich. */
  isFormerEmployee?: boolean;
  className?: string;
}

export function InsightsPerformanceFlags({
  flags,
  isFormerEmployee = false,
  className,
}: InsightsPerformanceFlagsProps) {
  // Zero flag u czynnego pracownika to nie „brak danych”, tylko dobra
  // wiadomość — nie rysujemy pustego stanu ani zastępczej kreski.
  if (flags.length === 0 && !isFormerEmployee) return null;

  // Ten sam komentarz przypięty do dwóch plakietek drukujemy RAZ. DynaReporter
  // pokazuje pod dwiema plakietkami jedno zdanie; powtórzone brzmi jak dwa
  // różne zarzuty o tej samej treści.
  const notes = Array.from(
    new Set(
      flags.map((f) => f.note?.trim()).filter((n): n is string => Boolean(n)),
    ),
  );

  return (
    <div className={cn("mt-1 space-y-0.5", className)}>
      {isFormerEmployee && <FormerEmployeeChip />}

      {flags.map((flag) => {
        const { badge, description, Icon } = styleFor(flag.severity);
        return (
          <div
            key={flag.id}
            className="flex flex-wrap items-center gap-1.5"
            title={provenance(flag)}
          >
            <Badge variant={badge} size="sm">
              <Icon className="h-3 w-3" aria-hidden="true" />
              {flag.label}
            </Badge>
            {flag.description && (
              <span className={cn("text-xs", description)}>
                {flag.description}
              </span>
            )}
          </div>
        );
      })}

      {notes.map((note) => (
        <p key={note} className="text-xs text-muted-foreground">
          {note}
        </p>
      ))}
    </div>
  );
}

export interface PerformanceFlagsLoadNoticeProps {
  /** React Query `isPending` — pierwsze ładowanie. */
  isPending: boolean;
  isSuccess: boolean;
  isError: boolean;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}

/**
 * Jednolinijkowy pasek NAD tabelą, gdy odczyt ostrzeżeń nie doszedł do skutku.
 *
 * Bez niego awaria tego zapytania renderuje się jako brak plakietek przy
 * wszystkich nazwiskach — czyli jako zdanie „nikt nie ma ostrzeżeń”, którego
 * nikt nie wypowiedział. Reszta tabeli (liczby performance) przychodzi z innego
 * zapytania i ma prawo się renderować, więc pasek zamiast pustego ekranu.
 */
export function PerformanceFlagsLoadNotice({
  isPending,
  isSuccess,
  isError,
  error,
  onRetry,
  className,
}: PerformanceFlagsLoadNoticeProps) {
  const state = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    // Zero aktywnych ostrzeżeń to WYNIK, nie pusty stan — pudełko „brak
    // danych” ogłaszałoby brak ocen jako usterkę.
    isEmpty: false,
  });

  if (state === "loading") {
    return (
      <p
        role="status"
        className={cn(
          "flex items-center gap-1.5 text-xs text-muted-foreground",
          className,
        )}
      >
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        Wczytuję ostrzeżenia…
      </p>
    );
  }

  if (!isBlockingViewState(state)) return null;

  const message =
    state === "forbidden"
      ? "Twoja rola nie ma dostępu do ostrzeżeń. Lista NIE jest pusta — poproś administratora o uprawnienia."
      : httpStatusFromError(error) === undefined
        ? "Nie udało się połączyć z serwerem. Ostrzeżenia mogą istnieć — sprawdź internet lub VPN."
        : "Nie udało się pobrać ostrzeżeń. Mogą istnieć — spróbuj ponownie za chwilę.";

  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground",
        className,
      )}
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{message}</span>
      {state === "error" && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="underline underline-offset-2 hover:no-underline"
        >
          Ponów
        </button>
      )}
    </div>
  );
}
