import * as React from "react"

import { cn } from "@/lib/utils"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

export interface BreadcrumbEntry {
  label: string
  href?: string
}

export type PageHeaderDensity = "default" | "compact"

export interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  breadcrumb?: BreadcrumbEntry[]
  actions?: React.ReactNode
  /** Compact is intended for dense application screens and drawers. */
  density?: PageHeaderDensity
  className?: string
}

export function PageHeader({
  eyebrow,
  title,
  description,
  breadcrumb,
  actions,
  density = "default",
  className,
}: PageHeaderProps) {
  const hasBreadcrumb = breadcrumb && breadcrumb.length > 0
  const isCompact = density === "compact"

  return (
    <header
      className={cn(
        "border-b border-border",
        isCompact ? "pb-4" : "pb-5",
        className,
      )}
    >
      {hasBreadcrumb ? (
        <Breadcrumb className={isCompact ? "mb-2" : "mb-3"}>
          <BreadcrumbList>
            {breadcrumb.map((entry, index) => {
              const isLast = index === breadcrumb.length - 1

              return (
                <React.Fragment key={`${entry.label}-${index}`}>
                  <BreadcrumbItem>
                    {isLast || !entry.href ? (
                      <BreadcrumbPage>{entry.label}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink href={entry.href}>
                        {entry.label}
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                  {!isLast ? <BreadcrumbSeparator /> : null}
                </React.Fragment>
              )
            })}
          </BreadcrumbList>
        </Breadcrumb>
      ) : null}

      <div
        className={cn(
          "flex flex-col sm:flex-row sm:items-start sm:justify-between",
          isCompact ? "gap-3" : "gap-4",
        )}
      >
        <div className={cn("min-w-0", isCompact ? "space-y-1" : "space-y-1.5")}>
          {eyebrow ? (
            <p className="text-xs uppercase tracking-[0.18em] text-primary">
              {eyebrow}
            </p>
          ) : null}
          <h1
            className={cn(
              "font-semibold tracking-tight",
              isCompact ? "text-xl sm:text-2xl" : "text-2xl sm:text-3xl",
            )}
          >
            {title}
          </h1>
          {description ? (
            <p className="max-w-2xl text-sm text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>

        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  )
}
