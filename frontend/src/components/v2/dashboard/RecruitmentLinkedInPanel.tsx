"use client"

import { Linkedin } from "lucide-react"

import { cn } from "@/lib/utils"
import { ROLE_LABELS, type UserRole } from "@/store/auth"
import type { RecruitmentLinkedIn } from "@/lib/dashboard-v2-api"

// LinkedIn Performance — pierwszy FE konsument /summary (dane z composite'u).
// Metryki wpisywane ręcznie (linkedin_daily_metrics) — pusty zespół to stan
// „nikt nie raportował", nie zera.

const RESPONSE_RATE_GOOD = 20
const RESPONSE_RATE_OK = 10

function responseRateClass(pct: number): string {
  if (pct >= RESPONSE_RATE_GOOD) return "text-success font-semibold"
  if (pct >= RESPONSE_RATE_OK) return "text-warning font-semibold"
  return "text-muted-foreground"
}

export function RecruitmentLinkedInPanel({
  linkedin,
}: {
  linkedin: RecruitmentLinkedIn
}) {
  const totals = linkedin.totals
  const summary: { label: string; value: string }[] = [
    { label: "CV dodane", value: String(totals.cv_added) },
    { label: "Wiadomości", value: String(totals.messages_sent) },
    { label: "Odpowiedzi", value: String(totals.responses_received) },
    { label: "Response rate", value: `${totals.response_rate}%` },
    { label: "Aktywni", value: String(totals.active_users) },
  ]

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Linkedin className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">
            LinkedIn Performance
          </h3>
        </div>
        <span className="text-xs text-muted-foreground">
          {linkedin.date_from} – {linkedin.date_to}
        </span>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {summary.map((item) => (
          <div
            key={item.label}
            className="rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
          >
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {item.label}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-foreground">
              {item.value}
            </p>
          </div>
        ))}
      </div>

      {linkedin.per_user.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          Nikt nie zaraportował aktywności LinkedIn w tym okresie.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="py-2 pr-3 text-left font-medium">Osoba</th>
                <th className="px-2 py-2 text-right font-medium">CV dodane</th>
                <th className="px-2 py-2 text-right font-medium">Wiadomości</th>
                <th className="px-2 py-2 text-right font-medium">Odpowiedzi</th>
                <th
                  className="px-2 py-2 text-right font-medium"
                  title="Odpowiedzi ÷ wysłane wiadomości"
                >
                  Response rate
                </th>
                <th className="px-2 py-2 text-right font-medium">
                  Dni raportowane
                </th>
              </tr>
            </thead>
            <tbody>
              {linkedin.per_user.map((row) => (
                <tr
                  key={row.user_id}
                  className="border-b border-border/50 last:border-0 hover:bg-muted/40"
                >
                  <td className="py-2 pr-3">
                    <div className="flex flex-col">
                      <span className="font-medium text-foreground">
                        {row.name}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        {ROLE_LABELS[row.role as UserRole] ?? row.role}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {row.cv_added}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {row.messages_sent}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-foreground">
                    {row.responses_received}
                  </td>
                  <td
                    className={cn(
                      "px-2 py-2 text-right tabular-nums",
                      responseRateClass(row.response_rate),
                    )}
                  >
                    {row.response_rate}%
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">
                    {row.days_reported}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default RecruitmentLinkedInPanel
