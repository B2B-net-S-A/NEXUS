"use client"

import { useQuery } from "@tanstack/react-query"
import { Inbox, Users } from "lucide-react"

import api from "@/lib/api"
import { Card } from "@/components/ui/card"

interface MyTeamRow {
  tac_user_id: number
  tac_name: string
  tac_email: string | null
  active_jobs: number
  active_candidates: number
  assignment_created_at: string
}

export function MyTeamTab() {
  const { data, isLoading, isError } = useQuery<MyTeamRow[]>({
    queryKey: ["my-team"],
    queryFn: () =>
      api.get<MyTeamRow[]>("/api/team-structure/my-team").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <Card className="p-4! text-sm text-muted-foreground">
        Ładowanie zespołu…
      </Card>
    )
  }
  if (isError) {
    return (
      <Card className="p-4! text-sm text-rose-700 bg-rose-50 border border-rose-200">
        Nie udało się pobrać zespołu.
      </Card>
    )
  }
  const rows = data ?? []
  if (rows.length === 0) {
    return (
      <Card className="p-8! text-center text-sm text-muted-foreground">
        <Inbox className="h-10 w-10 mx-auto mb-3 opacity-40" />
        Nie masz przypisanych TAC-ów. Skontaktuj się z HoR aby przypisać zespół.
      </Card>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-background/60 text-muted-foreground">
          <tr>
            <th className="text-left px-3 py-2 font-medium">Rekruter (TAC)</th>
            <th className="text-left px-3 py-2 font-medium">Email</th>
            <th className="text-right px-3 py-2 font-medium">Aktywne joby</th>
            <th className="text-right px-3 py-2 font-medium">Aktywni kandydaci</th>
            <th className="text-left px-3 py-2 font-medium">W zespole od</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.tac_user_id} className="border-t border-border hover:bg-background/40">
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1.5 font-medium">
                  <Users className="h-3.5 w-3.5 opacity-60" />
                  {row.tac_name}
                </span>
              </td>
              <td className="px-3 py-2 text-muted-foreground text-xs">
                {row.tac_email ?? "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {row.active_jobs}
              </td>
              <td className="px-3 py-2 text-right tabular-nums font-semibold">
                {row.active_candidates}
              </td>
              <td className="px-3 py-2 text-muted-foreground text-xs">
                {new Date(row.assignment_created_at).toLocaleDateString("pl-PL", {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
