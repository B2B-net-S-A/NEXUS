"use client"

// „Listy nad pulpitem” — Head of Recruitment i admin wybierają, które listy panelu
// „Czeka na Ciebie” stoją nad jego kafelkami (06.10.2026). Każda zmiana
// zapisuje się od razu na koncie (`PUT /api/users/me/dashboard/panels/…`).

import { ListChecks } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  DASHBOARD_PANEL_KEYS,
  PANEL_LABELS,
  type DashboardPanelKey,
} from "@/lib/dashboard-panels"

interface BoardPanelsMenuProps {
  hidden: ReadonlySet<DashboardPanelKey>
  disabled?: boolean
  onChange: (panel: DashboardPanelKey, hidden: boolean) => void
}

export function BoardPanelsMenu({ hidden, disabled, onChange }: BoardPanelsMenuProps) {
  const shownCount = DASHBOARD_PANEL_KEYS.length - hidden.size
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">
          <ListChecks className="h-4 w-4" aria-hidden />
          Listy nad pulpitem
          {hidden.size > 0 ? (
            <span className="text-xs tabular-nums text-muted-foreground">
              {shownCount}/{DASHBOARD_PANEL_KEYS.length}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="font-normal normal-case tracking-normal">
          <span className="block text-sm font-semibold text-foreground">
            Listy w „Czeka na Ciebie”
          </span>
          <span className="block text-xs text-muted-foreground">
            Odznacz listę, której nie chcesz widzieć. Zmianę widzisz tylko Ty.
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {DASHBOARD_PANEL_KEYS.map((key) => (
          <DropdownMenuCheckboxItem
            key={key}
            checked={!hidden.has(key)}
            disabled={disabled}
            // Menu zostaje otwarte — kilka list odznacza się jednym podejściem.
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={(checked) => onChange(key, checked !== true)}
          >
            {PANEL_LABELS[key]}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
