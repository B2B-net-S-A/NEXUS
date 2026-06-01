"use client";

import type { ElementType } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

export function formatPLN(value: number): string {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

export function fmtNumber(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "–";
  return num.toLocaleString("pl-PL");
}

const KPI_COLOR_MAP = {
  blue: "bg-primary/10 text-primary border-primary/15",
  green: "bg-green-50 text-green-600 border-green-100 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
  purple: "bg-purple-50 text-purple-600 border-purple-100 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800",
  orange: "bg-orange-50 text-orange-600 border-orange-100 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800",
  red: "bg-destructive/10 text-destructive border-red-100 dark:bg-red-900/30 dark:text-destructive dark:border-red-800",
  indigo: "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-400 dark:border-indigo-800",
} as const;

export type KpiColor = keyof typeof KPI_COLOR_MAP;

interface KpiCardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: ElementType;
  color?: KpiColor;
  trend?: "up" | "down";
}

export function KpiCard({ label, value, sub, icon: Icon, color = "blue", trend }: KpiCardProps) {
  return (
    <div className="bg-card rounded-xl border border-border p-5 shadow-sm">
      <div className="flex items-start justify-between mb-3">
        <div className={cn("p-2 rounded-lg border", KPI_COLOR_MAP[color])}>
          <Icon className="w-5 h-5" />
        </div>
        {trend === "up" && <TrendingUp className="w-4 h-4 text-green-500" />}
        {trend === "down" && <TrendingDown className="w-4 h-4 text-red-400" />}
      </div>
      <div className="text-2xl font-bold text-foreground">{value}</div>
      <div className="text-sm text-muted-foreground mt-0.5">{label}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}

interface HorizontalBarProps {
  label: string;
  value: number;
  max: number;
  color?: string;
  suffix?: string;
}

export function HorizontalBar({
  label,
  value,
  max,
  color = "bg-primary",
  suffix = "",
}: HorizontalBarProps) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 text-sm text-muted-foreground text-right truncate flex-shrink-0">
        {label}
      </div>
      <div className="flex-1 bg-muted rounded-full h-5 relative overflow-hidden">
        <div
          className={cn("h-5 rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
        <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground">
          {suffix ? `${value}${suffix}` : typeof value === "number" && value > 1000 ? formatPLN(value) : value}
        </span>
      </div>
      <div className="text-xs text-muted-foreground w-8 text-right">{pct}%</div>
    </div>
  );
}

interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

export function DonutChart({ segments }: { segments: DonutSegment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0)
    return <div className="text-sm text-muted-foreground text-center py-4">Brak danych</div>;

  let accumulated = 0;
  const gradientParts = segments.map((seg) => {
    const pct = (seg.value / total) * 100;
    const start = accumulated;
    accumulated += pct;
    return `${seg.color} ${start}% ${accumulated}%`;
  });

  return (
    <div className="flex items-center gap-6">
      <div
        className="w-28 h-28 rounded-full flex-shrink-0"
        style={{
          background: `conic-gradient(${gradientParts.join(", ")})`,
          mask: "radial-gradient(circle at center, transparent 40%, black 40%)",
          WebkitMask: "radial-gradient(circle at center, transparent 40%, black 40%)",
        }}
      />
      <div className="space-y-1.5">
        {segments.map((seg) => {
          const pct = total > 0 ? Math.round((seg.value / total) * 100) : 0;
          return (
            <div key={seg.label} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ background: seg.color }}
              />
              <span className="text-foreground">{seg.label}</span>
              <span className="text-muted-foreground ml-auto">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-6 h-6 border-4 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
