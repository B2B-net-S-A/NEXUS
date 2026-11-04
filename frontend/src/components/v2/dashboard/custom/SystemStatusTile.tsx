"use client"

// Kafelek „Stan systemu" (admin): wybrane sondy z `GET /api/health`.
//
// Wartość sondy to zwykle napis — sam stan („healthy”) albo stan z opisem
// („unhealthy: stalled a,b”, „degraded: stale 3d”). Obiekt też jest obsłużony
// (pole `status` + opis, jeśli serwer go niesie). `unknown` i brak sondy to
// „Nie wiadomo” — nigdy „OK”: sonda, której nikt nie sprawdził, nie jest
// zdrowa.

import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

export const SYSTEM_STATUS_QUERY_KEY = ["system-status", "health"] as const

type CheckValue = string | { status?: string; [key: string]: unknown } | null | undefined

export interface HealthResponse {
  status?: string
  version?: string
  checks?: Record<string, CheckValue>
}

/** Sondy na kafelku, w tej kolejności. */
export const SYSTEM_CHECKS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "database", label: "Baza danych" },
  { key: "traffit", label: "Synchronizacja Traffita" },
  { key: "order_mail", label: "Poczta zamówień" },
  { key: "background_tasks", label: "Zadania w tle" },
  { key: "migrations", label: "Migracje bazy" },
  { key: "m365_mail", label: "Wysyłka maili (M365)" },
  { key: "qdrant", label: "Wyszukiwanie wektorowe" },
  { key: "voyage", label: "Embeddingi (Voyage)" },
  { key: "anthropic", label: "Model AI (Anthropic)" },
]

export type CheckTone = "ok" | "warn" | "fail" | "off" | "unknown"

const TONE_LABEL: Record<CheckTone, string> = {
  ok: "OK",
  warn: "Uwaga",
  fail: "Awaria",
  off: "Wyłączone",
  unknown: "Nie wiadomo",
}

const TONE_CLASS: Record<CheckTone, string> = {
  ok: "bg-success/10 text-success",
  warn: "bg-warning-muted text-warning-muted-foreground",
  fail: "bg-destructive/10 text-destructive",
  off: "bg-muted text-muted-foreground",
  unknown: "bg-muted text-muted-foreground",
}

const STATUS_TONE: Record<string, CheckTone> = {
  healthy: "ok",
  ok: "ok",
  configured: "ok",
  degraded: "warn",
  stalled: "warn",
  warning: "warn",
  unhealthy: "fail",
  critical: "fail",
  crashed: "fail",
  misconfigured: "fail",
  unconfigured: "off",
  disabled: "off",
}

const DETAIL_PREFIXES: ReadonlyArray<[RegExp, string]> = [
  [/^stalled\s+/i, "Zawieszone: "],
  [/^stale\s+/i, "Nieaktualne od "],
]

function translateDetail(detail: string): string {
  for (const [pattern, replacement] of DETAIL_PREFIXES) {
    if (pattern.test(detail)) return detail.replace(pattern, replacement)
  }
  return detail
}

/** Stan sondy → ton pigułki i opis (tylko to, co serwer przysłał). */
export function readCheck(value: CheckValue): { tone: CheckTone; detail: string | null } {
  if (value == null) return { tone: "unknown", detail: null }
  if (typeof value === "string") {
    const [head, ...rest] = value.split(":")
    const status = head.trim().toLowerCase()
    const detail = rest.join(":").trim()
    return {
      tone: STATUS_TONE[status] ?? "unknown",
      detail: detail ? translateDetail(detail) : status === "misconfigured" ? "Brak konfiguracji." : null,
    }
  }
  const status = typeof value.status === "string" ? value.status.trim().toLowerCase() : ""
  const raw = [value.detail, value.message].find((v) => typeof v === "string" && v.trim())
  const lastSuccess =
    typeof value.last_success_at === "string" && value.last_success_at
      ? `Ostatni sukces: ${new Intl.DateTimeFormat("pl-PL", {
          timeZone: "Europe/Warsaw",
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }).format(new Date(value.last_success_at))}`
      : null
  return {
    tone: STATUS_TONE[status] ?? "unknown",
    detail: typeof raw === "string" ? translateDetail(raw.trim()) : lastSuccess,
  }
}

export function SystemStatusTile() {
  const query = useQuery({
    queryKey: SYSTEM_STATUS_QUERY_KEY,
    queryFn: () =>
      api
        .get<HealthResponse>("/api/health", {
          // 503 = baza nie odpowiada; treść i tak niesie sondy, więc ją pokazujemy.
          validateStatus: (status) => status === 200 || status === 503,
        })
        .then((r) => r.data),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const checks = query.data.checks ?? {}
  const version = query.data.version && query.data.version !== "unknown"
    ? query.data.version.slice(0, 7)
    : null

  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      <p className="text-xs text-muted-foreground">
        Wersja produkcji:{" "}
        <span className="font-mono text-foreground">{version ?? "nie wiadomo"}</span>
      </p>
      <ul className="flex flex-col gap-1.5">
        {SYSTEM_CHECKS.map(({ key, label }) => {
          const { tone, detail } = readCheck(checks[key])
          return (
            <li key={key} className="flex items-start justify-between gap-3" data-check={key}>
              <span className="min-w-0">
                <span className="block text-foreground">{label}</span>
                {detail ? (
                  <span className="block truncate text-xs text-muted-foreground" title={detail}>
                    {detail}
                  </span>
                ) : null}
              </span>
              <span
                data-tone={tone}
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                  TONE_CLASS[tone],
                )}
              >
                {TONE_LABEL[tone]}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
