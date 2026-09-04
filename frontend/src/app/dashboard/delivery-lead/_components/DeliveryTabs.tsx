"use client"

import { useRouter, useSearchParams } from "next/navigation"
import { Briefcase, Building2, ListChecks, Users } from "lucide-react"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PriorityRequestsPanel } from "@/components/v2/priority-work"

import { ActiveJobsTab } from "./tabs/ActiveJobsTab"
import { MyClientsTab } from "./tabs/MyClientsTab"
import { MyTeamTab } from "./tabs/MyTeamTab"

type TabValue = "clients" | "team" | "jobs" | "priorities"

interface DeliveryTabsProps {
  /** Current user id — passed to ActiveJobsTab as delivery_lead_id filter. */
  userId: number
}

const DEFAULT_TAB: TabValue = "clients"

function isValidTab(value: string | null): value is TabValue {
  return (
    value === "clients" ||
    value === "team" ||
    value === "jobs" ||
    value === "priorities"
  )
}

export function DeliveryTabs({ userId }: DeliveryTabsProps) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const raw = searchParams.get("tab")
  const active: TabValue = isValidTab(raw) ? raw : DEFAULT_TAB

  const setActive = (next: TabValue) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set("tab", next)
    router.replace(`/dashboard/delivery-lead?${params.toString()}`, { scroll: false })
  }

  return (
    <Tabs value={active} onValueChange={(v) => setActive(v as TabValue)}>
      <TabsList>
        <TabsTrigger value="clients">
          <Building2 className="h-3.5 w-3.5" />
          Klienci
        </TabsTrigger>
        <TabsTrigger value="team">
          <Users className="h-3.5 w-3.5" />
          Mój zespół
        </TabsTrigger>
        <TabsTrigger value="jobs">
          <Briefcase className="h-3.5 w-3.5" />
          Aktywne joby
        </TabsTrigger>
        <TabsTrigger value="priorities">
          <ListChecks className="h-3.5 w-3.5" />
          Priorytety
        </TabsTrigger>
      </TabsList>
      <TabsContent value="clients">
        <MyClientsTab />
      </TabsContent>
      <TabsContent value="team">
        <MyTeamTab />
      </TabsContent>
      <TabsContent value="jobs">
        <ActiveJobsTab deliveryLeadId={userId} />
      </TabsContent>
      <TabsContent value="priorities">
        <PriorityRequestsPanel deliveryLeadId={userId} />
      </TabsContent>
    </Tabs>
  )
}
