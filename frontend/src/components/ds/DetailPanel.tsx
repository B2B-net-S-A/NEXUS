"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { TabbedNav, type TabbedNavItem } from "@/components/ds/TabbedNav";

/**
 * Szkielet bocznego panelu szczegółów: nagłówek, opcjonalne zakładki,
 * przewijana treść i stopka z akcjami. Wypełnia `ListDetailLayout`.
 * Akcje w stopce otwierają TE SAME okna co przyciski na dawnych kartach.
 */
export interface DetailPanelProps {
  title: ReactNode;
  badges?: ReactNode;
  subtitle?: ReactNode;
  leading?: ReactNode;
  onClose: () => void;
  closeLabel?: string;
  tabs?: TabbedNavItem[];
  tab?: string;
  onTabChange?: (value: string) => void;
  tabsLabel?: string;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Czcionka jak w tabeli obok (zakładka „Zamówienia”): nagłówek text-sm, treść text-xs. */
  compact?: boolean;
  "data-testid"?: string;
}

export function DetailPanel({
  title,
  badges,
  subtitle,
  leading,
  onClose,
  closeLabel = "Zamknij panel",
  tabs,
  tab,
  onTabChange,
  tabsLabel = "Sekcje panelu",
  footer,
  children,
  className,
  compact = false,
  "data-testid": testId,
}: DetailPanelProps) {
  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col", className)} data-testid={testId}>
      <header className="grid gap-1.5 border-b border-border px-4 pb-3 pt-3">
        <div className="flex items-start gap-2">
          {leading}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 className={cn("min-w-0 truncate font-semibold text-foreground", compact ? "text-sm" : "text-base")}>{title}</h2>
              {badges}
            </div>
            {subtitle && <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            title={`${closeLabel} (Esc)`}
            className="hit-area -mr-1 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>
      {tabs && tab && onTabChange && (
        <div className="border-b border-border px-3 pt-1">
          <TabbedNav tabs={tabs} value={tab} onValueChange={onTabChange} ariaLabel={tabsLabel} overflow="scroll" dense />
        </div>
      )}
      <div
        className={cn(
          "grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-4 overflow-y-auto overflow-x-hidden px-4 py-3",
          compact ? "text-xs" : "text-sm",
        )}
      >
        {children}
      </div>
      {footer && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-muted/40 px-4 py-2.5">{footer}</footer>
      )}
    </div>
  );
}

export function DetailSection({
  title,
  aside,
  children,
  className,
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5", className)}>
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>{title}</span>
        {aside}
      </h3>
      {children}
    </section>
  );
}

export function DetailFacts({
  items,
  compact = false,
}: {
  items: Array<[ReactNode, ReactNode] | null | false>;
  compact?: boolean;
}) {
  const rows = items.filter(Boolean) as Array<[ReactNode, ReactNode]>;
  return (
    <dl className={cn("grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-x-3 gap-y-1", compact ? "text-xs" : "text-sm")}>
      {rows.map(([label, value], i) => (
        <div key={i} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
