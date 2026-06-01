"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

import { DashboardV2 } from "@/components/v2/pages/DashboardV2"
import { useAuthStore, type UserRole } from "@/store/auth"

// Role → dedykowany panel. Role bez wpisu lądują na ogólnym DashboardV2.
const ROLE_PANEL: Partial<Record<UserRole, string>> = {
  delivery_lead: "/dashboard/delivery-lead",
  tac: "/dashboard/recruiter",
  recruiter: "/dashboard/recruiter",
  sourcer: "/dashboard/recruiter",
  head_of_recruitment: "/dashboard/head-of-recruitment",
}

export default function DashboardPage() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  useEffect(() => {
    if (!hydrated || !user) return
    const target = ROLE_PANEL[user.role]
    if (target) {
      router.replace(target)
    }
  }, [hydrated, user, router])

  // Admin/user widzą generyczny dashboard. Inne role przeszły przez redirect
  // powyżej; zanim se react-router przeniesie – pokazujemy ten sam widok.
  return <DashboardV2 />
}
