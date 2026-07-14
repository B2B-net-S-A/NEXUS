import * as React from "react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export interface KeyFact {
  id: string
  label: React.ReactNode
  value?: React.ReactNode
  hint?: React.ReactNode
  icon?: LucideIcon
}

export interface KeyFactsProps
  extends Omit<React.HTMLAttributes<HTMLDListElement>, "children"> {
  facts: KeyFact[]
  columns?: 1 | 2 | 3 | 4
  density?: "default" | "compact"
  emptyValue?: React.ReactNode
}

const columnClasses: Record<NonNullable<KeyFactsProps["columns"]>, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4",
}

/** A semantic, responsive dl for the decision-making facts of an entity. */
export function KeyFacts({
  facts,
  columns = 3,
  density = "default",
  emptyValue = "—",
  className,
  ...props
}: KeyFactsProps) {
  return (
    <dl
      className={cn(
        "grid",
        columnClasses[columns],
        density === "compact" ? "gap-x-4 gap-y-3" : "gap-x-6 gap-y-5",
        className,
      )}
      {...props}
    >
      {facts.map((fact) => {
        const Icon = fact.icon
        const hasValue = fact.value !== null && fact.value !== undefined && fact.value !== ""

        return (
          <div key={fact.id} className="min-w-0">
            <dt className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              {Icon ? <Icon aria-hidden className="size-3.5 shrink-0" /> : null}
              <span>{fact.label}</span>
            </dt>
            <dd
              className={cn(
                "mt-1 break-words text-sm font-medium",
                hasValue ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {hasValue ? fact.value : emptyValue}
            </dd>
            {fact.hint ? (
              <dd className="mt-0.5 text-xs text-muted-foreground">{fact.hint}</dd>
            ) : null}
          </div>
        )
      })}
    </dl>
  )
}
