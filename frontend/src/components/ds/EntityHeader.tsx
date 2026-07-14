import * as React from "react"

import { cn } from "@/lib/utils"

export type EntityHeaderDensity = "default" | "compact"

export interface EntityHeaderProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  avatar?: React.ReactNode
  eyebrow?: React.ReactNode
  title: React.ReactNode
  subtitle?: React.ReactNode
  badges?: React.ReactNode
  metadata?: React.ReactNode
  actions?: React.ReactNode
  density?: EntityHeaderDensity
  headingLevel?: 1 | 2 | 3
  titleId?: string
}

/**
 * Shared identity header for profile pages and quick-view drawers.
 * Domain components provide the avatar, badges, metadata and actions; this
 * component owns the responsive hierarchy and heading semantics.
 */
export function EntityHeader({
  avatar,
  eyebrow,
  title,
  subtitle,
  badges,
  metadata,
  actions,
  density = "default",
  headingLevel = 1,
  titleId,
  className,
  ...props
}: EntityHeaderProps) {
  const Heading = `h${headingLevel}` as "h1" | "h2" | "h3"
  const isCompact = density === "compact"

  return (
    <header
      className={cn(
        "flex min-w-0 flex-col sm:flex-row sm:items-start sm:justify-between",
        isCompact ? "gap-3" : "gap-4",
        className,
      )}
      {...props}
    >
      <div className={cn("flex min-w-0", isCompact ? "gap-3" : "gap-4")}>
        {avatar ? <div className="shrink-0">{avatar}</div> : null}

        <div className="min-w-0">
          {eyebrow ? (
            <div className="mb-1 text-xs font-medium uppercase tracking-eyebrow text-primary">
              {eyebrow}
            </div>
          ) : null}

          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
            <Heading
              id={titleId}
              className={cn(
                "min-w-0 break-words font-semibold tracking-heading-tight text-foreground",
                isCompact ? "text-xl sm:text-2xl" : "text-2xl sm:text-3xl",
              )}
            >
              {title}
            </Heading>
            {badges ? (
              <div className="flex flex-wrap items-center gap-1.5">{badges}</div>
            ) : null}
          </div>

          {subtitle ? (
            <div className="mt-1 text-sm text-muted-foreground">{subtitle}</div>
          ) : null}
          {metadata ? (
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
              {metadata}
            </div>
          ) : null}
        </div>
      </div>

      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
          {actions}
        </div>
      ) : null}
    </header>
  )
}
