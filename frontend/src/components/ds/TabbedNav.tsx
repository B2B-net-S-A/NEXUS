"use client";

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface TabbedNavItem {
  value: string;
  label: string;
  count?: number;
  icon?: LucideIcon;
}

export interface TabbedNavProps {
  tabs: TabbedNavItem[];
  value: string;
  onValueChange: (value: string) => void;
  children?: React.ReactNode;
  ariaLabel?: string;
  /** Scroll keeps a single row; wrap exposes every tab on wider layouts. */
  overflow?: "scroll" | "wrap";
  className?: string;
  listClassName?: string;
}

export function TabbedNav({
  tabs,
  value,
  onValueChange,
  children,
  ariaLabel = "Sekcje",
  overflow = "wrap",
  className,
  listClassName,
}: TabbedNavProps) {
  return (
    <Tabs
      value={value}
      onValueChange={onValueChange}
      className={cn("w-full", className)}
    >
      <div
        className={cn(
          "w-full",
          overflow === "scroll" && "overflow-x-auto overscroll-x-contain",
        )}
      >
        <TabsList
          aria-label={ariaLabel}
          className={cn(
            "w-full",
            overflow === "scroll" ? "min-w-max flex-nowrap" : "flex-wrap",
            listClassName,
          )}
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = tab.value === value;

            return (
              <TabsTrigger key={tab.value} value={tab.value}>
                {Icon ? <Icon className="h-4 w-4" aria-hidden /> : null}
                <span>{tab.label}</span>
                {typeof tab.count === "number" ? (
                  <Badge
                    size="sm"
                    variant={isActive ? "soft" : "neutral"}
                    className="tabular-nums"
                  >
                    {tab.count}
                  </Badge>
                ) : null}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </div>
      {children}
    </Tabs>
  );
}
