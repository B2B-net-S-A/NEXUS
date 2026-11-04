"use client"

// Kafelek „Umowy przedwstępne” (0506, 21.10.2026): ile próśb czeka na
// wystawienie lub podpis, ile umów wygasa w 7 dni, ile osób ma termin umowy
// B2B z przedwstępnej i ile rezygnacji czeka na decyzję o karze. Zakres liczy
// serwer (HoR wszystko, DL swoi klienci i swoje prośby, rekruter swoje).

import Link from "next/link"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { usePreContractList, type PreContractTab } from "@/lib/api/preContracts"

const ROWS: ReadonlyArray<{ tab: PreContractTab; label: string; urgent?: boolean }> = [
  { tab: "todo", label: "Do zrobienia" },
  { tab: "expiring", label: "Wygasają w 7 dni", urgent: true },
  { tab: "b2b", label: "Termin umowy B2B", urgent: true },
  { tab: "penalty", label: "Do decyzji o karze", urgent: true },
]

export function PreContractsTile() {
  const list = usePreContractList("todo")
  if (list.isLoading) return <Skeleton className="h-24 w-full" />
  if (list.isError) {
    return <WidgetErrorBlock error={list.error} title="Nie udało się wczytać umów przedwstępnych." onRetry={() => void list.refetch()} />
  }
  if (!list.isSuccess) return null
  const counts = list.data.counts
  return (
    <div className="space-y-2 text-sm" data-testid="pre-contracts-tile">
      <ul className="space-y-1">
        {ROWS.map((row) => {
          const n = counts[row.tab] ?? 0
          return (
            <li key={row.tab}>
              <Link
                href={row.tab === "todo" ? "/jobs/umowy-przedwstepne" : `/jobs/umowy-przedwstepne?tab=${row.tab}`}
                className="flex items-center justify-between rounded-md px-2 py-1 hover:bg-muted"
              >
                <span>{row.label}</span>
                <span className={row.urgent && n > 0 ? "font-semibold tabular-nums text-destructive" : "font-semibold tabular-nums"}>
                  {n}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
