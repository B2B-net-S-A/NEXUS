"use client"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  TEAM_ROLE_OPTIONS,
  type ClientOption,
  type TeamFilters,
  type TeamRoleFilter,
} from "@/lib/team-filters"
import { cn } from "@/lib/utils"

const ALL_CLIENTS = "all"

/**
 * „Rola” (przyciski jak okres na pasku) i „Klient” (lista) — te same kontrolki
 * na pulpicie, w liście „Kto się liczy”, w tabeli Ludzie i w kaflu „Wyniki
 * zespołu” (decyzja Artura z 10.11.2026). Bez `clients` nie ma wyboru klienta.
 */
export function TeamFilterControls({
  value,
  onChange,
  clients,
  roles = TEAM_ROLE_OPTIONS.map((option) => option.value),
  showCounts = true,
  className,
}: {
  value: TeamFilters
  onChange: (next: TeamFilters) => void
  clients?: ClientOption[]
  /** Które przyciski roli pokazać; jeden = bez przycisków. */
  roles?: TeamRoleFilter[]
  /** Liczba przy kliencie ma sens tylko dla jednego etapu (lista), nie dla pulpitu. */
  showCounts?: boolean
  className?: string
}) {
  const roleOptions = TEAM_ROLE_OPTIONS.filter((option) => roles.includes(option.value))
  const selectedMissing =
    value.clientId !== null && !(clients ?? []).some((client) => client.id === value.clientId)
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2", className)}>
      {roleOptions.length > 1 ? (
        <div role="group" aria-label="Rola" className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">Rola</span>
          {roleOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={value.role === option.value}
              onClick={() => onChange({ ...value, role: option.value })}
              className={cn(
                "h-7 whitespace-nowrap rounded-md border px-2.5 text-[13px] font-medium transition-colors pointer-coarse:h-9",
                value.role === option.value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
      {clients ? (
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">Klient</span>
          <Select
            value={value.clientId === null ? ALL_CLIENTS : String(value.clientId)}
            onValueChange={(next) => {
              if (next === ALL_CLIENTS) {
                onChange({ ...value, clientId: null, clientName: null })
                return
              }
              const id = Number(next)
              const name =
                clients.find((client) => client.id === id)?.name ?? value.clientName ?? null
              onChange({ ...value, clientId: id, clientName: name })
            }}
          >
            <SelectTrigger
              className="h-7 w-56 min-w-0 text-[13px]"
              aria-label="Klient"
              data-tour="team-filters.client"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_CLIENTS}>Wszyscy klienci</SelectItem>
              {clients.map((client) => (
                <SelectItem key={client.id} value={String(client.id)}>
                  {client.name}
                  {showCounts ? (
                    <span className="tabular-nums text-muted-foreground"> · {client.count}</span>
                  ) : null}
                </SelectItem>
              ))}
              {/* Klient wybrany w innym okresie: zostaje na liście, z zerem. */}
              {selectedMissing ? (
                <SelectItem value={String(value.clientId)}>
                  {value.clientName ?? `Klient #${value.clientId}`}
                  {showCounts ? <span className="text-muted-foreground"> · 0</span> : null}
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  )
}
