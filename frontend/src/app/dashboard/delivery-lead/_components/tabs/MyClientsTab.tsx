"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Building2, Inbox } from "lucide-react"

import api from "@/lib/api"
import { Card } from "@/components/ui/card"

interface MyClientRow {
  client_id: number
  name: string
  industry: string | null
  is_head_dl: boolean
  active_orders_count: number
  total_revenue_all_time: number
  active_revenue: number
  expiring_soon_count: number
  framework_contract_status: string | null
  framework_expiry_date: string | null
}

function formatPln(value: number): string {
  return new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 }).format(value)
}

export function MyClientsTab() {
  const { data, isLoading, isError } = useQuery<MyClientRow[]>({
    queryKey: ["my-clients"],
    queryFn: () => api.get<MyClientRow[]>("/api/my-clients").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <Card className="!p-4 text-sm text-muted-foreground">Ładowanie klientów…</Card>
    )
  }
  if (isError) {
    return (
      <Card className="!p-4 text-sm text-rose-700 bg-rose-50 border border-rose-200">
        Nie udało się pobrać listy klientów.
      </Card>
    )
  }
  const rows = data ?? []
  if (rows.length === 0) {
    return (
      <Card className="!p-8 text-center text-sm text-muted-foreground">
        <Inbox className="h-10 w-10 mx-auto mb-3 opacity-40" />
        Brak przypisanych klientów. Skontaktuj się z HoR aby dostać przypisanie.
      </Card>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-background/60 text-muted-foreground">
          <tr>
            <th className="text-left px-3 py-2 font-medium">Klient</th>
            <th className="text-left px-3 py-2 font-medium">Branża</th>
            <th className="text-right px-3 py-2 font-medium">Aktywne ordery</th>
            <th className="text-right px-3 py-2 font-medium">Active revenue</th>
            <th className="text-left px-3 py-2 font-medium">Framework</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.client_id} className="border-t border-border hover:bg-background/40">
              <td className="px-3 py-2">
                <Link
                  href={`/clients/${row.client_id}`}
                  className="font-medium text-primary hover:underline inline-flex items-center gap-1.5"
                >
                  {row.is_head_dl && (
                    <span title="Head DL" className="text-amber-500">
                      ⭐
                    </span>
                  )}
                  <Building2 className="h-3.5 w-3.5 opacity-60" />
                  {row.name}
                </Link>
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {row.industry ?? "–"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {row.active_orders_count}
              </td>
              <td className="px-3 py-2 text-right tabular-nums font-mono text-xs">
                {formatPln(row.active_revenue)} PLN
              </td>
              <td className="px-3 py-2">
                {row.framework_contract_status ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-emerald-50 text-emerald-900">
                    {row.framework_contract_status}
                    {row.framework_expiry_date && (
                      <span className="opacity-60">
                        · do {new Date(row.framework_expiry_date).toLocaleDateString("pl-PL")}
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">brak</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
