import { ReactNode } from "react";
import { cn } from "@/lib/utils";

const COLOR_MAP: Record<string, string> = {
  blue:   "bg-primary/10 dark:bg-primary/30 text-primary dark:text-primary border-primary/15 dark:border-primary/30",
  green:  "bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 border-green-100 dark:border-green-800",
  purple: "bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 border-purple-100 dark:border-purple-800",
  orange: "bg-orange-50 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 border-orange-100 dark:border-orange-800",
  red:    "bg-destructive/10 dark:bg-red-900/30 text-destructive dark:text-destructive border-red-100 dark:border-red-800",
  teal:   "bg-teal-50 dark:bg-teal-900/30 text-teal-600 dark:text-teal-400 border-teal-100 dark:border-teal-800",
  gray:   "bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground border-border dark:border-border",
};

const SPARKLINE_COLORS: Record<string, string> = {
  blue:   "#3b82f6",
  green:  "#22c55e",
  purple: "#a855f7",
  orange: "#f97316",
  red:    "#ef4444",
  teal:   "#14b8a6",
  gray:   "#9ca3af",
};

// CSS-only sparkline using inline SVG polyline
function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 60;
  const h = 20;
  const step = w / (values.length - 1);

  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="overflow-visible">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.7"
      />
      {/* Last dot */}
      {(() => {
        const lastIdx = values.length - 1;
        const lx = lastIdx * step;
        const ly = h - ((values[lastIdx] - min) / range) * h;
        return <circle cx={lx.toFixed(1)} cy={ly.toFixed(1)} r="2" fill={color} />;
      })()}
    </svg>
  );
}

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: ReactNode;
  color?: keyof typeof COLOR_MAP;
  trend?: { value: number; label?: string };
  sparkline?: number[];
}

export function StatsCard({ title, value, subtitle, icon, color = "blue", trend, sparkline }: StatsCardProps) {
  const strokeColor = SPARKLINE_COLORS[color] ?? SPARKLINE_COLORS.blue;

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 flex flex-col gap-3 hover:shadow-md transition-all duration-200 cursor-default">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">{title}</span>
        <div className="flex items-center gap-2">
          {sparkline && <Sparkline values={sparkline} color={strokeColor} />}
          {icon && (
            <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center border", COLOR_MAP[color])}>
              {icon}
            </div>
          )}
        </div>
      </div>
      <div>
        <p className="text-3xl font-bold text-foreground dark:text-foreground leading-none">{value}</p>
        {subtitle && <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">{subtitle}</p>}
        {trend != null && (
          <p className={cn("text-xs mt-1 font-medium", trend.value >= 0 ? "text-green-600" : "text-destructive")}>
            {trend.value >= 0 ? "↑" : "↓"} {Math.abs(trend.value)}%
            {trend.label && <span className="text-muted-foreground dark:text-muted-foreground font-normal ml-1">{trend.label}</span>}
          </p>
        )}
      </div>
    </div>
  );
}
