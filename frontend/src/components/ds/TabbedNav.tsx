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

interface TabbedNavProps {
  tabs: TabbedNavItem[];
  value: string;
  onValueChange: (value: string) => void;
  children?: React.ReactNode;
  className?: string;
  listClassName?: string;
}

export function TabbedNav({
  tabs,
  value,
  onValueChange,
  children,
  className,
  listClassName,
}: TabbedNavProps) {
  return (
    <Tabs
      value={value}
      onValueChange={onValueChange}
      className={cn("w-full", className)}
    >
      <TabsList className={cn("w-full", listClassName)}>
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
      {children}
    </Tabs>
  );
}
