import { Suspense } from "react"

import { CustomDashboard } from "@/components/v2/dashboard/custom/CustomDashboard"

export default function DashboardPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>}
    >
      <CustomDashboard />
    </Suspense>
  )
}
