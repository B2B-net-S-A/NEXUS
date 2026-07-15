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

interface BreadcrumbEntry {
  label: string
  href?: string
}

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  breadcrumb?: BreadcrumbEntry[]
  actions?: React.ReactNode
  className?: string
}

export function PageHeader({
  eyebrow,
  title,
  description,
  breadcrumb,
  actions,
  className,
}: PageHeaderProps) {
  const hasBreadcrumb = breadcrumb && breadcrumb.length > 0

  return (
    <header className={cn("border-b border-border pb-5", className)}>
      {hasBreadcrumb ? (
        <Breadcrumb className="mb-3">
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

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1.5">
          {eyebrow ? (
            <p className="text-xs uppercase tracking-[0.18em] text-primary">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {title}
          </h1>
          {description ? (
            <p className="max-w-2xl text-sm text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>

        {actions ? (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        ) : null}
      </div>
    </header>
  )
}
