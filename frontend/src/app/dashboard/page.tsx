"use client"

import { useEffect, useMemo } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { BarChart3 } from "lucide-react"

import { PageHeader } from "@/components/ds"
import { KlienciPanel } from "@/components/insights/KlienciPanel"
import { RekrutacjaPanel } from "@/components/insights/RekrutacjaPanel"
import { ZarzadPanel } from "@/components/insights/ZarzadPanel"
import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { DashboardV2 } from "@/components/v2/pages/DashboardV2"
import { cn } from "@/lib/utils"
import {
  DASHBOARD_VIEW_LABELS,
  getAvailableDashboardViews,
  getPreferredDashboardView,
  getUserRoles,
  useAuthStore,
  type DashboardView,
} from "@/store/auth"

function isDashboardView(value: string | null): value is DashboardView {
  return (
    value === "operations" ||
    value === "recruitment" ||
    value === "delivery" ||
    value === "executive"
  )
}

function ExecutiveDashboardView() {
  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <PageHeader
        eyebrow="Panel zarządczy"
        title="Wyniki organizacji"
        description="Operacje, finanse w PLN i wyniki przetargów z kanonicznego Analytics v1."
      />
      <ZarzadPanel />
    </div>
  )
}

function RecruitmentDashboardView() {
  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <PageHeader
        eyebrow="Panel rekrutacji"
        title="Wyniki rekrutacji"
        description="Kanoniczny lejek, źródła i KPI zespołu."
      />
      <RekrutacjaPanel />
    </div>
  )
}

function DeliveryDashboardView() {
  return (
    <div className="mx-auto max-w-[1400px] space-y-6 p-4 md:p-6">
      <PageHeader
        eyebrow="Panel delivery"
        title="Klienci i delivery"
        description="Operacyjne wyniki klientów bez danych finansowych."
      />
      <KlienciPanel />
    </div>
  )
}

export default function DashboardHubPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)

  const availableViews = useMemo(() => getAvailableDashboardViews(user), [user])
  const preferredView = getPreferredDashboardView(user)
  const rawView = searchParams.get("view")
  const requestedView = isDashboardView(rawView) ? rawView : null
  const activeView =
    requestedView && availableViews.includes(requestedView)
      ? requestedView
      : preferredView

  useEffect(() => {
    if (!hydrated || !user) return
    if (rawView === activeView) return
    const params = new URLSearchParams(searchParams.toString())
    params.set("view", activeView)
    router.replace(`/dashboard?${params.toString()}`, { scroll: false })
  }, [activeView, hydrated, rawView, router, searchParams, user])

  if (!hydrated) {
    return (
      <div className="mx-auto max-w-[1400px] p-4 md:p-6">
        <StatsBoundary isLoading>
          <span />
        </StatsBoundary>
      </div>
    )
  }

  if (!user || availableViews.length === 0) {
    return (
      <div className="mx-auto max-w-[1400px] p-4 md:p-6">
        <StatsBoundary
          isError
          error={{ response: { status: 403 } }}
        >
          <span />
        </StatsBoundary>
      </div>
    )
  }

  const showViewSwitcher =
    getUserRoles(user).length > 1 && availableViews.length > 1

  return (
    <>
      {showViewSwitcher && (
        <div className="mx-auto max-w-[1400px] px-4 pt-4 md:px-6">
          <div
            className="inline-flex flex-wrap rounded-lg border border-border bg-card p-1"
            role="navigation"
            aria-label="Widok dashboardu"
          >
            {availableViews.map((view) => (
              <button
                key={view}
                type="button"
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString())
                  params.set("view", view)
                  router.push(`/dashboard?${params.toString()}`, { scroll: false })
                }}
                aria-current={activeView === view ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  activeView === view
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <BarChart3 className="h-3.5 w-3.5" />
                {DASHBOARD_VIEW_LABELS[view]}
              </button>
            ))}
          </div>
        </div>
      )}

      {activeView === "operations" && <DashboardV2 />}
      {activeView === "recruitment" && <RecruitmentDashboardView />}
      {activeView === "delivery" && <DeliveryDashboardView />}
      {activeView === "executive" && <ExecutiveDashboardView />}
    </>
  )
}
