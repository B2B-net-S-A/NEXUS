"use client";

import type { ElementType, ReactNode } from "react";
import {
  AlertTriangle,
  HelpCircle,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";
import type { DashboardQualityStatus } from "@/lib/dashboard-v2-api";
import {
  QueryStateNotice,
  type BlockingViewState,
} from "@/components/ds/QueryStateNotice";

export function formatPLN(value: number): string {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

export function fmtNumber(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}

const KPI_COLOR_MAP = {
  blue: "bg-primary/10 text-primary border-primary/15",
  green:
    "bg-green-50 text-green-600 border-green-100 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
  purple:
    "bg-purple-50 text-purple-600 border-purple-100 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800",
  orange:
    "bg-orange-50 text-orange-600 border-orange-100 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800",
  red: "bg-destructive/10 text-destructive border-red-100 dark:bg-red-900/30 dark:text-destructive dark:border-red-800",
  indigo:
    "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-400 dark:border-indigo-800",
} as const;

export type KpiColor = keyof typeof KPI_COLOR_MAP;

interface KpiCardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: ElementType;
  color?: KpiColor;
  trend?: "up" | "down";
}

export function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  color = "blue",
  trend,
}: KpiCardProps) {
  return (
    <div className="bg-card rounded-xl border border-border p-5 shadow-xs">
      <div className="flex items-start justify-between mb-3">
        <div className={cn("p-2 rounded-lg border", KPI_COLOR_MAP[color])}>
          <Icon className="w-5 h-5" />
        </div>
        {trend === "up" && <TrendingUp className="w-4 h-4 text-green-500" />}
        {trend === "down" && <TrendingDown className="w-4 h-4 text-red-400" />}
      </div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
      <div className="text-sm text-muted-foreground mt-0.5">{label}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}

interface HorizontalBarProps {
  label: string;
  value: number;
  max: number;
  color?: string;
  suffix?: string;
}

export function HorizontalBar({
  label,
  value,
  max,
  color = "bg-primary",
  suffix = "",
}: HorizontalBarProps) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 text-sm text-muted-foreground text-right truncate shrink-0">
        {label}
      </div>
      <div className="flex-1 bg-muted rounded-full h-5 relative overflow-hidden">
        <div
          className={cn("h-5 rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
        <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground">
          {suffix
            ? `${value}${suffix}`
            : typeof value === "number" && value > 1000
              ? formatPLN(value)
              : value}
        </span>
      </div>
      <div className="text-xs text-muted-foreground w-8 text-right">{pct}%</div>
    </div>
  );
}

interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

export function DonutChart({ segments }: { segments: DonutSegment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0)
    return (
      <div className="text-sm text-muted-foreground text-center py-4">
        Brak danych
      </div>
    );

  let accumulated = 0;
  const gradientParts = segments.map((seg) => {
    const pct = (seg.value / total) * 100;
    const start = accumulated;
    accumulated += pct;
    return `${seg.color} ${start}% ${accumulated}%`;
  });

  return (
    <div className="flex items-center gap-6">
      <div
        className="w-28 h-28 rounded-full shrink-0"
        style={{
          background: `conic-gradient(${gradientParts.join(", ")})`,
          mask: "radial-gradient(circle at center, transparent 40%, black 40%)",
          WebkitMask:
            "radial-gradient(circle at center, transparent 40%, black 40%)",
        }}
      />
      <div className="space-y-1.5">
        {segments.map((seg) => {
          const pct = total > 0 ? Math.round((seg.value / total) * 100) : 0;
          return (
            <div key={seg.label} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded-full shrink-0"
                style={{ background: seg.color }}
              />
              <span className="text-foreground">{seg.label}</span>
              <span className="text-muted-foreground ml-auto">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-6 h-6 border-4 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

/**
 * Awaria sekcji raportowej.
 *
 * Kit miał `LoadingSpinner`, ale nie miał NIC na awarię — i to jest powód, dla
 * którego sześć sekcji robiło `if (!data) return null` albo pisało „Brak
 * danych.". 403 z bramki RBAC i 500 z raportu wyglądały wtedy jak pusty lejek,
 * czyli jak informacja, a nie jak jej brak. Cienka nakładka na
 * `QueryStateNotice`, żeby każda sekcja nie powtarzała mapowania statusu HTTP.
 */
export function SectionError({
  label,
  error,
  onRetry,
}: {
  /** Nazwa sekcji w mianowniku — wchodzi w komunikat o braku uprawnień. */
  label: string;
  error: unknown;
  onRetry?: () => void;
}) {
  // `isLoading: false` + `isError: true` gwarantuje jeden z trzech stanów
  // blokujących — `resolveViewState` nie ma tu innej gałęzi do zwrócenia.
  const state = resolveViewState({
    isLoading: false,
    isError: true,
    error,
  }) as BlockingViewState;
  const description =
    state === "forbidden"
      ? `Twoja rola nie ma dostępu do sekcji „${label}". Dane NIE są puste — poproś administratora o uprawnienia.`
      : state === "error" && httpStatusFromError(error) === undefined
        ? `Nie udało się połączyć z serwerem („${label}"). Sprawdź internet lub VPN i spróbuj ponownie.`
        : state === "error"
          ? `Nie udało się pobrać danych sekcji „${label}". Dane mogą istnieć — spróbuj ponownie za chwilę.`
          : undefined;
  return (
    <QueryStateNotice
      state={state}
      description={description}
      onRetry={state === "error" ? onRetry : undefined}
    />
  );
}

/** Statusy koperty `data_quality` inne niż „complete" — tylko one degradują kafel. */
export type DegradedStatus = Exclude<DashboardQualityStatus, "complete">;

const DEGRADED_TITLE: Record<DegradedStatus, string> = {
  partial: "Dane niepełne",
  stale: "Dane nieaktualne",
  unavailable: "Część danych niedostępna",
};

/**
 * Degradacja POJEDYNCZEGO kafla, gdy koperta zwraca `quality != "complete"`
 * (wzorzec `_Quality` z `backend/app/services/dashboard_v2.py`).
 *
 * Świadomie NIE baner na górze strony (R6): koperta niesie jakość per sekcja,
 * więc baner zbiorczy podważałby też te kafle, które policzyły się w całości —
 * a to uczy ignorować ostrzeżenie. Liczby zostają widoczne: „niepełne" to nie
 * to samo co „nieznane", a schowanie ich cofnęłoby nas do pustki udającej dane.
 */
export function Degraded({
  reason,
  status = "partial",
  className,
}: {
  /** Ostrzeżenia z koperty (`data_quality.warnings`) albo jedno zdanie. */
  reason: string | string[];
  status?: DegradedStatus;
  className?: string;
}) {
  // Puste ostrzeżenia po odsianiu = nie ma czego napisać. Pasek bez treści
  // mówiłby „coś jest nie tak" i nie dawał żadnego tropu, więc go nie ma.
  const reasons = (Array.isArray(reason) ? reason : [reason])
    .map((r) => r?.trim())
    .filter((r): r is string => Boolean(r));
  if (reasons.length === 0) return null;

  return (
    <div
      role="status"
      className={cn(
        // Tokeny, nie `amber-*`: te ostatnie znają wyłącznie motyw domyślny
        // i ciemny, więc w paletach soft/kids stoją obok stokenizowanych
        // bursztynów sąsiednich sekcji jako drugi, inny bursztyn. Para
        // `warning-muted` przełącza się sama, więc blok `dark:` znika.
        "flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground",
        className,
      )}
    >
      <AlertTriangle
        className="mt-0.5 h-3.5 w-3.5 shrink-0"
        aria-hidden="true"
      />
      <div className="space-y-0.5">
        <p className="font-medium">{DEGRADED_TITLE[status]}</p>
        {reasons.map((r) => (
          <p key={r} className="opacity-90">
            {r}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * Kody powodów, dla których wiersza NIE DA SIĘ ocenić.
 *
 * `no_workday_data` / `no_compass_profile` / `calendar_gap` — trzecia lista
 * Power Callingu (brak mianownika dni roboczych). `no_data` — D6, ścieżka
 * rozwoju bez ani jednego atrybuowanego placementu.
 */
const NOT_ASSESSABLE_REASON: Record<string, string> = {
  no_workday_data:
    "Brak danych o nieobecnościach — nie ma z czego policzyć dziennego mianownika.",
  // Zero dni roboczych w oknie to najczęściej URLOP. Dzielenie przez zero nie
  // jest oceną, więc ten wiersz nie może trafić do „poniżej progu”.
  zero_workdays:
    "Zero dni roboczych w tym oknie (np. urlop) — nie ma czego dzielić, więc nie oceniamy.",
  no_compass_profile:
    "Brak powiązanego profilu w COMPASSIE — nie znamy dni roboczych tej osoby.",
  calendar_gap:
    "Luka w kalendarzu dni roboczych — okres nie jest pokryty w całości.",
  stale_workday_data:
    "Dane o nieobecnościach starsze niż jeden interwał synchronizacji.",
  no_data: "Brak przypisanych placementów w NEXUSIE — poziom nie jest liczony.",
};

export interface NotAssessableRow {
  /** Klucz listy: `user_id` z Power Callingu, `id` z D6. */
  id?: string | number | null;
  name?: string | null;
  /** Kod powodu z backendu. */
  reason?: string | null;
  /** Doprecyzowanie z backendu, np. „dane od 03.2026". */
  hint?: string | null;
}

/**
 * Lista osób, których w tym okresie NIE OCENIAMY.
 *
 * Sedno: ten komponent nie ma gdzie wyrenderować liczby. Wiersz bez mianownika
 * wrzucony do zwykłej tabeli dostaje `0` i czerwony próg, czyli „wiemy, że
 * słabo" zamiast „nie wiemy" — dokładnie ten defekt zamyka rozbicie Power
 * Callingu na trzy listy. Dlatego wychodzi stąd nazwisko i powód po polsku,
 * i nic poza tym.
 */
export function NotAssessable({
  rows,
  title = "Nieoceniani w tym okresie",
  footnote,
}: {
  rows: NotAssessableRow[];
  title?: string;
  footnote?: ReactNode;
}) {
  // Wiersz bez nazwiska I bez powodu nie ma treści — pusty wiersz na takiej
  // liście czyta się jak błąd renderowania, nie jak informacja.
  const visible = rows.filter(
    (row) => row?.name?.trim() || row?.reason?.trim(),
  );
  // Pusta lista = wszyscy są oceniani. Nagłówek nad zerem wierszy sugerowałby,
  // że dane się nie doczytały.
  if (visible.length === 0) return null;

  return (
    <div className="rounded-lg border border-dashed border-border p-4">
      <div className="mb-2 flex items-center gap-2">
        <HelpCircle
          className="h-4 w-4 text-muted-foreground"
          aria-hidden="true"
        />
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <span className="ml-auto text-xs text-muted-foreground">
          {visible.length}
        </span>
      </div>
      <ul className="space-y-1.5">
        {visible.map((row, index) => {
          const code = row.reason?.trim();
          // Nieznany kod NADAL musi coś powiedzieć — milczący wiersz wygląda
          // jak brak powodu, a powód zawsze istnieje, tylko my go nie znamy.
          const explanation = code
            ? (NOT_ASSESSABLE_REASON[code] ?? `Powód: ${code}.`)
            : "Powód nieznany — dane wejściowe niekompletne.";
          return (
            <li
              key={row.id ?? `${row.name ?? "?"}-${index}`}
              className="text-sm"
            >
              <span className="text-foreground">
                {row.name?.trim() || "Nieznany użytkownik"}
              </span>
              <span className="text-muted-foreground"> — {explanation}</span>
              {row.hint?.trim() ? (
                <span className="text-xs text-muted-foreground">
                  {" "}
                  ({row.hint.trim()})
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      {footnote ? (
        <p className="mt-2 text-xs text-muted-foreground">{footnote}</p>
      ) : null}
    </div>
  );
}
