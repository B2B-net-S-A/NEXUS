"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

interface KanbanBoardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

const KanbanBoard = React.forwardRef<HTMLDivElement, KanbanBoardProps>(
  ({ className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("flex gap-4 overflow-x-auto pb-2", className)}
      {...props}
    >
      {children}
    </div>
  )
);
KanbanBoard.displayName = "KanbanBoard";

interface KanbanColumnProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  count?: number;
  children: React.ReactNode;
}

const KanbanColumn = React.forwardRef<HTMLDivElement, KanbanColumnProps>(
  ({ title, count, className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg border border-border bg-muted/40",
        className
      )}
      {...props}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2.5">
        <h3 className="truncate text-sm font-medium text-foreground">{title}</h3>
        {count !== undefined ? (
          <Badge variant="soft" size="sm" className="tabular-nums">
            {count}
          </Badge>
        ) : null}
      </div>
      <ScrollArea className="max-h-[calc(100vh-16rem)] flex-1">
        <div className="space-y-2 px-2 pb-2">{children}</div>
      </ScrollArea>
    </div>
  )
);
KanbanColumn.displayName = "KanbanColumn";

interface KanbanCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  highlighted?: boolean;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
}

const KanbanCard = React.forwardRef<HTMLDivElement, KanbanCardProps>(
  ({ children, highlighted = false, onClick, className, ...props }, ref) => {
    const isInteractive = typeof onClick === "function";

    return (
      <div
        ref={ref}
        onClick={onClick}
        role={isInteractive ? "button" : undefined}
        tabIndex={isInteractive ? 0 : undefined}
        onKeyDown={
          isInteractive
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onClick?.(
                    event as unknown as React.MouseEvent<HTMLDivElement>
                  );
                }
              }
            : undefined
        }
        className={cn(
          "rounded-lg border bg-card p-3 text-sm text-card-foreground transition-colors",
          "hover:border-primary/40",
          isInteractive &&
            "cursor-pointer focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
          highlighted ? "border-primary/60 ring-1 ring-primary/30" : "border-border",
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
KanbanCard.displayName = "KanbanCard";

export { KanbanBoard, KanbanColumn, KanbanCard };
export type { KanbanBoardProps, KanbanColumnProps, KanbanCardProps };
