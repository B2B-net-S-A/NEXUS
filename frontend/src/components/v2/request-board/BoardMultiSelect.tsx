"use client"

import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"

import { Checkbox } from "@/components/ui/checkbox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export interface BoardMultiSelectOption<V extends string> {
  value: V
  label: string
}

interface Props<V extends string> {
  /** Id przycisku — etykieta pola (`<label htmlFor>`) wskazuje na niego. */
  id: string
  value: readonly V[]
  onChange: (next: V[]) => void
  options: readonly BoardMultiSelectOption<V>[]
  /** Napis przy pustym wyborze: „Wszyscy klienci”, „Każdy termin”. */
  placeholder: string
  className?: string
  /** Pole zawęża listę — ten sam znacznik co dawne `<select>` (testy, style). */
  active?: boolean
  /** Dodatkowe pozycje wyboru spoza listy (np. przedział „Wysłani”). */
  extraLabels?: readonly string[]
  /** Treść pod listą, np. pola „od / do”. */
  footer?: ReactNode
}

/**
 * Lista wyboru pulpitu z kilkoma zaznaczeniami naraz. Przycisk wygląda jak
 * dawne pole `<select>`: jedna pozycja = jej nazwa, kilka = pierwsza i „+N”
 * (pełna lista w podpowiedzi). Okno zostaje otwarte przy zaznaczaniu —
 * zamyka je klik obok albo Esc.
 */
export function BoardMultiSelect<V extends string>({
  id,
  value,
  onChange,
  options,
  placeholder,
  className,
  active,
  extraLabels = [],
  footer,
}: Props<V>) {
  const [open, setOpen] = useState(false)
  const chosen = [
    ...options.filter((o) => value.includes(o.value)).map((o) => o.label),
    // Wartość z adresu, której nie ma już na liście (np. klient bez requestów),
    // nadal filtruje — pokazujemy ją, żeby pusta tabela miała wyjaśnienie.
    ...value.filter((v) => !options.some((o) => o.value === v)),
    ...extraLabels,
  ]
  const label =
    chosen.length === 0
      ? placeholder
      : chosen.length === 1
        ? chosen[0]
        : `${chosen[0]} +${chosen.length - 1}`
  const toggle = (item: V) =>
    onChange(value.includes(item) ? value.filter((v) => v !== item) : [...value, item])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          data-active={active ?? value.length > 0}
          title={chosen.length > 1 ? chosen.join(", ") : undefined}
          className={cn("flex items-center justify-between gap-2 text-left", className)}
        >
          <span className="truncate">{label}</span>
          <ChevronDown className="size-4 shrink-0 opacity-60" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-1">
        <ul className="flex flex-col" role="list">
          {options.map((option) => {
            const checked = value.includes(option.value)
            const optionId = `${id}-${option.value}`
            return (
              <li key={option.value}>
                <label
                  htmlFor={optionId}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
                >
                  <Checkbox
                    id={optionId}
                    // Nazwa wprost: przycisk Radixa nie zawsze dostaje ją z `label for`.
                    aria-label={option.label}
                    checked={checked}
                    onCheckedChange={() => toggle(option.value)}
                  />
                  <span className="truncate">{option.label}</span>
                </label>
              </li>
            )
          })}
        </ul>
        {footer}
        {value.length > 1 ? (
          <div className="border-t border-border px-2 pt-1.5 pb-1 text-xs text-muted-foreground">
            Pokazuję requesty pasujące do dowolnej z zaznaczonych pozycji.
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
