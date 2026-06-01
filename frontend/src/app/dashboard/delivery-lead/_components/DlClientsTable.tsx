import { Crown } from "lucide-react"

import { cn } from "@/lib/utils"

import type { DlClientsSummary } from "./types"

interface DlClientsTableProps {
  rows: DlClientsSummary[]
}

export function DlClientsTable({ rows }: DlClientsTableProps) {
  return (
    <div className="rounded-lg overflow-hidden border border-border shadow-sm">
      <div className="bg-gradient-to-r from-teal-500 via-cyan-600 to-teal-600 px-4 py-3 text-white flex items-center gap-2">
        <Crown className="h-5 w-5" />
        <div>
          <div className="font-semibold text-lg">
            Delivery Lead · Przypisani Klienci
          </div>
          <div className="text-xs text-white/70">
            ⭐ = Head (główny opiekun klienta)
          </div>
        </div>
      </div>
      <div className="bg-card">
        <table className="w-full text-sm">
          <thead className="border-b border-border">
            <tr>
              <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-4 py-2 w-48">
                Delivery Lead
              </th>
              <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-4 py-2">
                Klienci
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => {
              const initials = row.delivery_lead.name
                .split(" ")
                .map((p) => p[0])
                .join("")
                .slice(0, 2)
                .toUpperCase()
              return (
                <tr key={row.delivery_lead.id}>
                  <td className="px-4 py-3 align-top">
                    <span className="inline-flex items-center gap-2">
                      <span className="inline-flex items-center justify-center h-7 w-7 rounded-full bg-teal-100 text-teal-800 text-xs font-bold">
                        {initials}
                      </span>
                      <span className="font-medium text-foreground">
                        {row.delivery_lead.name}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {row.clients.length === 0 && (
                      <span className="text-xs text-muted-foreground">–</span>
                    )}
                    <div className="flex flex-wrap gap-1.5">
                      {row.clients.map((c) => (
                        <span
                          key={c.id}
                          className={cn(
                            "inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium",
                            c.is_head
                              ? "bg-amber-100 text-amber-900 ring-1 ring-amber-300"
                              : "bg-amber-50 text-amber-800",
                          )}
                        >
                          {c.is_head && "⭐"}
                          {c.name}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="text-center text-sm text-muted-foreground py-6">
            Brak przypisań DL → klient. Dodaj w /settings/team-structure.
          </p>
        )}
      </div>
    </div>
  )
}
