"use client"

// Kafelek „W zastępstwie” (17.10.2026): praca kolegi, którą osoba dziś
// prowadzi — rekrutacje, rozmowy u klienta do końca zastępstwa i kandydaci
// w procesie. Liczy silnik zastępstw (`GET /api/hr/dashboard/substitution`):
// to te same rekrutacje, które są teraz w „Moich”. Ostrzeżenie „zastępca też
// jest nieobecny” trafia do wpisanego zastępcy i do przełożonego. Rodzaju
// nieobecności tu nie ma (D6).

import Link from "next/link"
import { AlertTriangle } from "lucide-react"

import { dayLabel, eventLabel } from "@/components/hr/leave/leave-format"
import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import {
  useMySubstitution,
  type SubstitutionItem,
  type SubstitutionWarning,
} from "@/lib/api/hr-dashboard"
import { pluralPl } from "@/lib/plural-pl"
import { resolveViewState } from "@/lib/view-state"

/** Zdanie ostrzeżenia — inne dla samego zastępcy, inne dla przełożonego. */
export function warningText(warning: SubstitutionWarning): string {
  const owner = warning.owner_name ?? "Osoba z zespołu"
  if (warning.you_are_substitute) {
    return `Jesteś zastępcą: ${owner}. Masz dziś nieobecność, więc ta praca czeka bez zastępcy — daj znać przełożonemu.`
  }
  const substitute = warning.substitute_name ?? "zastępca"
  return `${owner} — zastępca (${substitute}) też ma dziś nieobecność. Praca czeka bez zastępcy.`
}

/** „Java Developer · Klient A, QA · Klient B” — podgląd z nazwy, reszta to liczba. */
export function jobsPreview(item: SubstitutionItem): string {
  return item.recruitments.items
    .map((job) => (job.client_name ? `${job.title} · ${job.client_name}` : job.title))
    .join(", ")
}

export function meetingsPreview(item: SubstitutionItem): string {
  return item.client_meetings.items
    .map((meeting) =>
      [eventLabel(meeting.starts_at), meeting.client_name].filter(Boolean).join(" · "),
    )
    .join(", ")
}

function WorkRow({ count, label, detail }: { count: number; label: string; detail?: string }) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="w-8 shrink-0 text-right font-mono text-xl font-semibold leading-tight tabular-nums text-foreground">
        {count}
      </span>
      <div className="min-w-0">
        <p className="text-sm text-foreground">{label}</p>
        {detail ? <p className="truncate text-xs text-muted-foreground">{detail}</p> : null}
      </div>
    </div>
  )
}

function CoverCard({ item }: { item: SubstitutionItem }) {
  return (
    <section
      aria-label={`Zastępstwo: ${item.owner_name ?? "osoba z zespołu"}`}
      className="flex flex-col gap-2"
    >
      <p className="text-sm font-semibold text-foreground">
        Zastępujesz: {item.owner_name ?? "osobę z zespołu"}
        <span className="font-normal text-muted-foreground"> · do {dayLabel(item.end_date)}</span>
      </p>
      <WorkRow
        count={item.recruitments.count}
        label={pluralPl(item.recruitments.count, "rekrutacja", "rekrutacje", "rekrutacji")}
        detail={jobsPreview(item) || undefined}
      />
      <WorkRow
        count={item.client_meetings.count}
        label={pluralPl(
          item.client_meetings.count,
          "rozmowa u klienta",
          "rozmowy u klienta",
          "rozmów u klienta",
        )}
        detail={meetingsPreview(item) || undefined}
      />
      <WorkRow
        count={item.pipeline_cards}
        label={pluralPl(
          item.pipeline_cards,
          "kandydat w procesie",
          "kandydaci w procesie",
          "kandydatów w procesie",
        )}
      />
    </section>
  )
}

export function HrSubstitutionTile() {
  const query = useMySubstitution()
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: Boolean(query.data && !query.data.items.length && !query.data.warnings.length),
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const { items, warnings, enabled, fresh } = query.data
  return (
    <div className="flex h-full flex-col gap-3">
      {warnings.map((warning) => (
        <p
          key={`${warning.owner_user_id}-${warning.substitute_user_id}`}
          role="status"
          className="flex items-start gap-2 rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{warningText(warning)}</span>
        </p>
      ))}
      {state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          {enabled
            ? "Dziś nikogo nie zastępujesz."
            : "Zastępstwa ruszą, gdy NEXUS dostanie dane o urlopach."}
        </p>
      ) : (
        items.map((item) => <CoverCard key={item.owner_user_id} item={item} />)
      )}
      {enabled && !fresh ? (
        <p className="text-xs text-muted-foreground">Dane o nieobecnościach mogą być nieaktualne.</p>
      ) : null}
      {items.length ? (
        <Link
          href="/jobs?mine=1"
          className="mt-auto self-start text-sm font-medium text-primary hover:underline"
        >
          Otwórz pracę w „Moich” rekrutacjach
        </Link>
      ) : null}
    </div>
  )
}
