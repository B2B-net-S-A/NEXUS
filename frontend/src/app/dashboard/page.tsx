import { Suspense } from "react"

import { RoleDashboard } from "@/components/v2/dashboard/RoleDashboard"

export default function DashboardPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>}
    >
      <RoleDashboard />
    </Suspense>
  )
}
