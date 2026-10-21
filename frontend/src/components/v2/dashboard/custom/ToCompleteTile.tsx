"use client"

// Kafelek „Do uzupełnienia” (prośba Olafa, decyzje Artura 21.10.2026, wariant A
// z makiet https://claude.ai/artifact/2UPJU2mB69Xf25QdtH8KuY): umowy do
// zamknięcia, rekrutacje do dokończenia albo zamknięcia i wymagania do poprawy
// w jednym kafelku, który stawia się w dowolnym miejscu pulpitu.
//
// Te same sekcje co w „Czeka na Ciebie” — opakowane, nie przepisane. Gdy
// kafelek stoi na pulpicie, panel tych list nie pokazuje
// (`withoutToCompleteLists`). Szeroki kafelek ma listy obok siebie, wąski —
// przełącznik i jedną listę naraz. Listy odznaczone w „Listy nad pulpitem”
// są tu puste, tak jak w panelu.

import { useMemo, useState, type ReactNode } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { AgreementTasksSection } from "@/components/v2/dashboard/AgreementTasksSection"
import { PendingJobsSection } from "@/components/v2/dashboard/PendingJobsSection"
import { RequirementFixesSection } from "@/components/v2/dashboard/RequirementFixesSection"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useBoardTasks } from "@/lib/api/boardTasks"
import { useUserDashboard } from "@/lib/api/userDashboard"
import { effectiveHiddenPanels, withoutHiddenPanels } from "@/lib/dashboard-panels"
import { toCompleteCounts } from "@/lib/dashboard-to-complete"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

type ListKey = "agreements" | "jobs" | "fixes"

// Od tej szerokości kafelka listy stoją obok siebie (A1), niżej — przełącznik (A3).
const COLUMNS: Record<number, string> = {
  1: "",
  2: "@min-[880px]/todo:grid-cols-2",
  3: "@min-[880px]/todo:grid-cols-3",
}

export function ToCompleteTile() {
  const user = useAuthStore((s) => s.user)
  const query = useBoardTasks()
  const dashboard = useUserDashboard()
  const storedHidden = dashboard.data?.hidden_panels
  const hidden = useMemo(() => effectiveHiddenPanels(user, storedHidden), [user, storedHidden])
  const [picked, setPicked] = useState<ListKey | null>(null)

  if (!query.data) {
    if (query.isError) {
      return (
        <WidgetErrorBlock
          title="Nie udało się wczytać list „Do uzupełnienia”."
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      )
    }
    return <Skeleton className="h-full min-h-24 w-full" />
  }

  const data = withoutHiddenPanels(query.data, hidden)
  const counts = toCompleteCounts(data)
  const fixesFailed = data.requirement_fixes === null
  const lists: { key: ListKey; label: string; count: number; node: ReactNode }[] = []
  if (counts.agreements > 0 && data.agreements) {
    lists.push({
      key: "agreements",
      label: "Umowy",
      count: counts.agreements,
      // Do potwierdzenia podpisu to zadanie — zostaje w „Czeka na Ciebie”.
      node: (
        <AgreementTasksSection
          tasks={{ ...data.agreements, to_confirm: [], waiting_on_others: [] }}
        />
      ),
    })
  }
  if (counts.jobs > 0) {
    lists.push({
      key: "jobs",
      label: "Rekrutacje",
      count: counts.jobs,
      node: <PendingJobsSection pending={data.pending_jobs} forms={data.unfinished_forms} />,
    })
  }
  if (counts.fixes > 0 || fixesFailed) {
    lists.push({
      key: "fixes",
      label: "Wymagania",
      count: counts.fixes,
      node: fixesFailed ? (
        <p role="status" className="text-sm text-muted-foreground">
          Nie udało się policzyć „Wymagań do poprawy” — odśwież pulpit.
        </p>
      ) : (
        <RequirementFixesSection rows={data.requirement_fixes} />
      ),
    })
  }

  if (lists.length === 0) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Nic do uzupełnienia.
      </p>
    )
  }

  const active = lists.some((l) => l.key === picked) ? picked : lists[0].key
  return (
    <div className="@container/todo flex min-w-0 flex-col gap-3">
      {lists.length > 1 ? (
        <div
          role="group"
          aria-label="Rodzaj zaległości"
          className="flex flex-wrap gap-1.5 @min-[880px]/todo:hidden"
        >
          {lists.map((list) => (
            <button
              key={list.key}
              type="button"
              aria-pressed={list.key === active}
              onClick={() => setPicked(list.key)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium",
                list.key === active
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-foreground hover:bg-muted",
              )}
            >
              {list.label}
              <span className="tabular-nums">{list.count}</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className={cn("grid min-w-0 gap-4", COLUMNS[lists.length])}>
        {lists.map((list) => (
          <div
            key={list.key}
            data-testid={`to-complete-${list.key}`}
            className={cn("min-w-0", list.key !== active && "hidden @min-[880px]/todo:block")}
          >
            {list.node}
          </div>
        ))}
      </div>
    </div>
  )
}
