"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type Density = "cozy" | "compact";

const densityRowClass: Record<Density, string> = {
  cozy: "h-12",
  compact: "h-9",
};

const densityCellClass: Record<Density, string> = {
  cozy: "px-4 py-2",
  compact: "px-3 py-1.5",
};

const densityContext = React.createContext<Density>("cozy");

interface TableProps extends React.HTMLAttributes<HTMLTableElement> {
  density?: Density;
}

export const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, density = "cozy", ...props }, ref) => (
    <densityContext.Provider value={density}>
      <div className="relative w-full overflow-auto rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))]">
        <table
          ref={ref}
          className={cn("w-full caption-bottom text-sm", className)}
          {...props}
        />
      </div>
    </densityContext.Provider>
  )
);
Table.displayName = "Table";

export const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn(
      "bg-[hsl(var(--bg-canvas))] border-b border-[hsl(var(--border-subtle))]",
      "[&_tr]:border-b-0",
      className
    )}
    {...props}
  />
));
TableHeader.displayName = "TableHeader";

export const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

export const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "bg-[hsl(var(--bg-canvas))] border-t border-[hsl(var(--border-subtle))] font-medium",
      className
    )}
    {...props}
  />
));
TableFooter.displayName = "TableFooter";

export const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement> & { interactive?: boolean; selected?: boolean }
>(({ className, interactive, selected, ...props }, ref) => {
  const density = React.useContext(densityContext);
  return (
    <tr
      ref={ref}
      data-selected={selected || undefined}
      className={cn(
        "border-b border-[hsl(var(--border-subtle))]/60 transition-colors",
        densityRowClass[density],
        interactive && "cursor-pointer hover:bg-[hsl(var(--accent-soft))]/40",
        selected && "bg-[hsl(var(--accent-soft))] hover:bg-[hsl(var(--accent-soft))]",
        className
      )}
      {...props}
    />
  );
});
TableRow.displayName = "TableRow";

export const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement> & { sortable?: boolean }
>(({ className, sortable, ...props }, ref) => {
  const density = React.useContext(densityContext);
  return (
    <th
      ref={ref}
      className={cn(
        "text-left align-middle font-semibold",
        "text-[10px] uppercase tracking-[0.08em] text-[hsl(var(--text-muted))]",
        densityCellClass[density],
        sortable && "cursor-pointer hover:text-[hsl(var(--text-title))] select-none",
        className
      )}
      {...props}
    />
  );
});
TableHead.displayName = "TableHead";

export const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
  const density = React.useContext(densityContext);
  return (
    <td
      ref={ref}
      className={cn(
        "align-middle text-[hsl(var(--text-body))]",
        densityCellClass[density],
        className
      )}
      {...props}
    />
  );
});
TableCell.displayName = "TableCell";

export const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-xs text-[hsl(var(--text-muted))]", className)}
    {...props}
  />
));
TableCaption.displayName = "TableCaption";
